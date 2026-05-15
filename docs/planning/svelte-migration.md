# Svelte 4 → 5 Migration Plan (Inspector frontend)

## Status

- **Policy**: Svelte 5 is the default for **new** code. Svelte 4 syntax is **legacy** — kept compiling via Svelte 5's legacy-mode but migrated either opportunistically (when touched for a feature) or in the dedicated phases below.
- **Maintainer**: a single AI agent (Claude Code). The plan optimizes for *future-session-read* clarity and refactor safety, not human migration ergonomics.
- **Mixed-mode is the steady state.** Some files will stay legacy indefinitely. That is fine and intended.
- **Single file = single mode.** A given `.svelte` file is fully runes or fully legacy. No mixing inside one file.

## Why migrate at all

Concrete wins specific to this codebase, in order of how often they bite during normal work:

1. **`SegmentRow.svelte` and the validation card cluster** are heavy `$:` users. Reactive blocks re-run on dependency changes that are *implicit* — every read of this file requires re-deriving what triggers each block. `$derived` makes the dependency graph readable inline.
2. **`createEventDispatcher` strings are untyped.** Renaming an event in a child without updating a parent is silent at compile time. Callback props (`onSplitConfirm: (op: SplitOp) => void`) are type-checked end-to-end across 96 `dispatch()` call sites.
3. **`export let` walls** (SegmentRow: 19 props) become a single `$props()` destructure with a `Props` type — one Read to understand a component's interface.
4. **Tab-scoped stores** in `tabs/segments/stores/` (14 files) and `tabs/timestamps/stores/` (4 files) are private to one tab. They can collapse to `$state` + `$derived` in `.svelte.ts` modules, deleting `writable()` / `derived()` / `get()` ceremony.
5. **`$bindable()`** makes two-way binding a contract at the prop site, not archaeology — useful in `TimeEdit.svelte`, `SegmentRow.svelte`, `RequestForm.svelte`.

## Why **not** migrate parts of it

- **Canvas + audio-sync imperative code does not benefit.** `$state`/`$derived` add zero value over local `let` in `requestAnimationFrame` draw loops or audio `currentTime` polling. Tests don't cover playback timing, so a regression lands in production-for-the-user.
- **Trivial UI components** (small dumb-display files <100 lines, low prop count, no events) get marginal improvement. Migrate only when they're already being edited.

## Audit findings (as of 2026-05-15)

```
.svelte files            83
.ts/.js helpers          219
Total .svelte lines      17,238

Reactive `$:` blocks     363
`export let`             182
`createEventDispatcher`  62 files
`dispatch(` calls        96
`bind:`                  88
`on:` directives         438
`<slot>` files           3   (AudioPlayer, AccordionPanel, Modal)
Store files              26  (6 lib, 14 segments, 4 timestamps, 2 dashboard)
Components importing svelte/store   18
Existing rune usage      0
```

**Top heaviest `$:` files (migration impact concentrated here):**

| Lines | `$:` | `export let` | `dispatch` | `bind:` | File |
|------:|-----:|-------------:|-----------:|--------:|------|
| 743 | 36 | 19 | 2 | 1 | `tabs/segments/components/list/SegmentRow.svelte` |
| 656 | 22 | 4 | 1 | 3 | `tabs/segments/components/validation/ValidationPanel.svelte` |
| 286 | 23 | 3 | 3 | 1 | `tabs/segments/components/validation/GenericIssueCard.svelte` |
| 423 | 13 | 2 | 1 | 0 | `tabs/segments/components/list/SegmentsList.svelte` |
| 324 | 13 | 1 | 0 | 0 | `tabs/segments/components/history/HistoryPanel.svelte` |
| 432 | 13 | 4 | 6 | 1 | `lib/components/picker/CombinationPicker.svelte` |
| 794 | 11 | 4 | 1 | 2 | `tabs/timestamps/components/TimestampsWaveform.svelte` *(do not migrate)* |
| 744 | 11 | 3 | 1 | 0 | `tabs/dashboard/views/ReciterDetail.svelte` |
| 734 |  ? | 4 | 4 | 9 | `tabs/dashboard/components/RequestForm.svelte` |

**Top dispatch-heavy files (callback-prop cascade hotspots):**

| dispatches | File |
|-----------:|------|
| 13 | `tabs/timestamps/components/TimestampsKeyboard.svelte` *(timestamps tab — deprioritized)* |
| 10 | `lib/components/AudioElement.svelte` *(do not migrate — audio core)* |
| 7  | `tabs/timestamps/components/TimestampsAudio.svelte` *(do not migrate — audio core)* |
| 6  | `tabs/segments/components/footer/SegmentsFooter.svelte` |
| 6  | `lib/components/picker/CombinationPicker.svelte` |
| 5  | `lib/components/player/PlayerControls.svelte` |

## Do-not-migrate list (legacy permanently)

These files are exempt. The cost-benefit is inverted: high regression risk, near-zero clarity gain.

- `tabs/timestamps/components/TimestampsWaveform.svelte` — 794L canvas + RAF + audio cursor sync.
- `tabs/timestamps/components/TimestampsAudio.svelte` — audio source & playback driver.
- `tabs/timestamps/components/AnimationDisplay.svelte` — RAF-driven karaoke.
- `lib/components/AudioElement.svelte` — `<audio>` element + media-session bridge.
- `lib/components/player/BottomPlayer.svelte` — playback UI tied to AudioElement.
- `lib/components/WaveformCanvas.svelte` — canvas peaks renderer.
- `tabs/segments/components/list/SegmentWaveformCanvas.svelte` — same.

If one of these *must* be edited for an unrelated reason, migrate the surrounding props/events but keep the canvas draw loop in plain `let` + `onMount` patterns.

---

## Phase 0 — Foundation (one session)

**Goal**: green build on Svelte 5 with every existing file still compiling in legacy mode.

Changes:

1. Bump `package.json` devDependencies:
   - `svelte` `^4` → `^5`
   - `svelte-check` `^3` → `^4`
   - `@sveltejs/vite-plugin-svelte` `^3` → `^5` (matches Vite 5 + Svelte 5)
   - `eslint-plugin-svelte` `^2.46` → `^2.46`+ verify v5 lint rules, or move to `^3` once stable
   - `@testing-library/svelte` `^5.3` — verify v5 support (5.x supports Svelte 5)
2. `svelte.config.js`: leave `compilerOptions` empty so per-file mode detection runs. Do **not** set `compilerOptions.runes = true` globally — that would force every file into rune mode.
3. Run `npm run check`, `npm run lint`, `npm run test`, `npm run build`. Fix any breakage.
4. Smoke-test in dev:
   - Dashboard browse + claim flow.
   - Segments tab open + edit + save on a known WIP slug.
   - Timestamps tab waveform + playback (regression-critical: audio sync).

**Acceptance**: zero code logic changes; only the dependency bumps and config tweaks. CI green. Manual smoke on the three tabs.

**Risk**: Vite plugin major bump may shift HMR behavior. Watch for canvas redraw glitches during HMR — if they appear, downgrade plugin version and pin.

---

## Phase 1 — Tab-scoped stores → `.svelte.ts` rune modules (highest payoff per risk)

**Why first**: stores are isolated. Converting `tabs/segments/stores/dirty.ts` doesn't force any component to change *immediately* — the existing `$store` autosubscribe syntax keeps working when reading rune-backed exports through a thin compat wrapper, or components can be updated incrementally. This is the largest single delete-boilerplate win with the smallest blast radius.

**Targets (ordered by impact):**

1. `tabs/segments/stores/dirty.ts` (310L, 1 derived) — central to save UX.
2. `tabs/segments/stores/edit.ts` (219L, unified writable + 8 field-views) — the comment in the file itself complains about the writable pattern; runes fix this.
3. `tabs/segments/stores/segments.ts` (217L, 1 derived).
4. `tabs/segments/stores/chapter.ts` (199L, 2 derived).
5. `tabs/segments/stores/playback.ts` (178L) — *audit playback sync regression risk first; this one talks to AudioElement*.
6. `tabs/segments/stores/filters.ts` (281L, 4 derived).
7. `tabs/segments/stores/history.ts`, `save.ts`, `stats.ts`, `navigation.ts`, `validation.ts`, `config.ts`, `merge-redirect.ts`, `autosave.ts`.
8. `tabs/timestamps/stores/*` (4 files) — except `playback.ts` which couples to AudioElement (audit first).
9. `tabs/dashboard/stores/*` (2 files).

**What changes per store file:**

- `writable<T>(initial)` → `let value = $state<T>(initial)` + `export function getValue() { return value }` + `export function setValue(...)`. Or simpler: export a single object holder `export const state = $state<T>({...})` and mutate fields.
- `derived(a, $a => f($a))` → `export const computed = $derived.by(() => f(state.value))` in a `.svelte.ts` module (note: rune `$derived` requires `.svelte.js` / `.svelte.ts` extension — the file must be renamed).
- `get(store)` → direct property read (`state.value`).
- `.update(fn)` → direct mutation (`state.value = fn(state.value)`).

**Component-side fallout:**

- `$store` autosubscribe stops working on rune modules. Components that read these stores need to import the module and read properties directly (`segmentsState.foo`) — but only when the consuming component itself is converted to runes.
- Bridge strategy: keep a thin `writable`-shaped export alongside the rune state for one transition window, then drop it after consuming components are migrated.

**Keep as plain stores** (global, used by mixed-mode components from day one):

- `lib/stores/toast.ts`
- `lib/stores/editing-mode.ts` — used everywhere; needs a stable interface
- `lib/stores/current-user.ts` — same
- `lib/stores/edit-popover.ts`, `sign-in-modal.ts`, `player-context.ts`

These convert *last*, after every consuming component is on runes.

**Acceptance**: each store conversion ships with its existing tests passing (the `__tests__/editing-mode.test.ts` pattern exists — extend it). Smoke-test the segments save flow after each batch.

---

## Phase 2 — Validation card cluster (high `$:` density, low cascade)

**Why second**: these components have the highest `$:` per-line density and are largely leaf components. Few parent dependencies. Big greppability win.

**Targets:**

- `tabs/segments/components/validation/ValidationPanel.svelte` (22 `$:`)
- `tabs/segments/components/validation/GenericIssueCard.svelte` (23 `$:`)
- `tabs/segments/components/validation/MissingWordsCard.svelte` (10 `$:`)
- `tabs/segments/components/validation/MissingVersesCard.svelte` (9 `$:`)
- `tabs/segments/components/validation/ErrorCard.svelte`
- `tabs/segments/components/validation/AccordionGuideModal.svelte` (302L, has slots — convert slots to snippets)

**Conversion recipe per file:**

| From (Svelte 4) | To (Svelte 5) |
|---|---|
| `export let foo: T` | `let { foo }: Props = $props()` with `type Props = { foo: T }` |
| `export let foo: T = default` | `let { foo = default }: Props = $props()` |
| `$: bar = f(foo)` | `const bar = $derived(f(foo))` |
| `$: { sideEffect(foo) }` | `$effect(() => { sideEffect(foo) })` |
| `let count = 0` (reactive let) | `let count = $state(0)` |
| `let arr: T[] = []` (mutated via `arr = [...arr, x]`) | `let arr = $state<T[]>([])` + `arr.push(x)` works |
| `createEventDispatcher` + `dispatch('foo', data)` | callback prop `onfoo: (data: D) => void` in `$props()`, called as `onfoo(data)` |
| `on:foo={handler}` on child | `onfoo={handler}` on child |
| `<slot name="x" />` | `{@render x?.()}` + `x: Snippet` in `$props()` |
| Default slot + named slots in same file | snippets for each (`children` for default) |
| `bind:value` (child accepts) | child declares with `$bindable()`: `let { value = $bindable() }: Props = $props()` |

**Acceptance**: visual diff of validation panel in dev for a slug with known issues; ValidationPanel renders identically and re-validation on save still triggers the same accordion order.

---

## Phase 3 — `SegmentRow.svelte` cluster (highest single-file payoff, highest blast radius)

**Why third (not first)**: this is the largest concrete win — 19 props, 36 `$:` blocks, the file you (and Claude) re-read most often. But it has the broadest interop surface: `SegmentsList.svelte` is its parent, `TimeEdit.svelte` is its child, `SegmentRow` consumes ~7 stores. Migrate after stores and validation cards so the surface around it is already runes.

**Targets (must migrate as one atomic unit):**

- `tabs/segments/components/list/SegmentRow.svelte` (743L, 19 props, 36 `$:`)
- `tabs/segments/components/list/SegmentsList.svelte` (423L, 13 `$:`) — parent
- `tabs/segments/components/list/TimeEdit.svelte` (374L, 6 props) — child, 4 `bind:`
- `tabs/segments/components/list/TimeRange.svelte` (7 props) — sibling
- Any leaf in `list/` that emits events SegmentRow forwards

**Sequence within the phase:**

1. Migrate leaves first (TimeRange, TimeEdit) so their events become callback-prop shapes.
2. Migrate SegmentRow, replacing all `dispatch(...)` with `on*` callback props and all `bind:` consumers with `$bindable()`.
3. Migrate SegmentsList parent, switching its `on:*` listeners to `on*=` callback props.

**Watch items:**

- `TimeEdit.svelte` has `bind:value`-style two-way binding for start/end times — must be `$bindable()`. Mis-flagging silently breaks save.
- SegmentRow's split/trim highlights are derived state — convert with `$derived`, verify the highlight rectangle still updates on hover.
- The 36 `$:` blocks include reactive guard conditions like `$: if (foo) { doX() }` — these become `$effect(() => { if (foo) doX() })`. Read each one and decide: is this a *derivation* (`$derived`) or a *side-effect* (`$effect`)?

**Acceptance**: full segments-tab manual run-through — claim a WIP slug, perform trim/split/merge/re-reference, save, undo, redo. Diff `segments.json` before/after; payload must be byte-identical to a pre-migration baseline produced via the same gestures.

---

## Phase 4 — `SegmentsFooter.svelte` cluster

- `tabs/segments/components/footer/SegmentsFooter.svelte` (787L, 6 dispatches, 3 binds)
- `lib/components/picker/CombinationPicker.svelte` (432L, 13 `$:`, 6 dispatches) — used by the footer and other tabs
- `tabs/segments/components/picker/*` if any wrap CombinationPicker

CombinationPicker is shared lib code — migrating it lets other consumers benefit too.

**Acceptance**: claim/release/state-pill clicks behave identically; picker selection flow works for chapter, verse, and segment scopes.

---

## Phase 5 — Dashboard and request flows

- `tabs/dashboard/components/RequestForm.svelte` (734L, 9 `bind:`, 4 dispatches) — heavy form bindings; high `$bindable` payoff.
- `tabs/dashboard/views/ReciterDetail.svelte` (744L, 11 `$:`)
- `tabs/dashboard/views/CatalogList.svelte` (334L, 10 `$:`)
- `tabs/dashboard/components/AdminActivityRail.svelte` (329L)
- `tabs/dashboard/views/Dashboard*.svelte` and remaining tab components.

These are read-heavy + form-heavy. Lower regression risk than the editor cluster because dashboard mutations route through admin endpoints with their own server-side guards.

---

## Phase 6 — History panel and remaining segments tab

- `tabs/segments/components/history/HistoryPanel.svelte` (324L, 13 `$:`)
- `tabs/segments/components/history/HistoryFilters.svelte` (13 `$:`)
- `tabs/segments/components/history/EditChainRow.svelte` (15 `$:`)
- `tabs/segments/components/history/HistoryOp.svelte` (9 `$:`, 5 props, 4 `bind:`)
- Stats: `tabs/segments/components/stats/StatsChart.svelte` (5 props)
- Filters: `tabs/segments/components/filters/FilterCondition.svelte`

---

## Phase 7 — `lib/components/*` and global stores

Last because everything else depends on these and breaking changes ripple.

- Global stores → rune modules: `editing-mode.ts`, `current-user.ts`, `toast.ts`, `edit-popover.ts`, `sign-in-modal.ts`, `player-context.ts`.
- `lib/components/SearchableSelect.svelte` (3 `bind:`)
- `lib/components/AccordionPanel.svelte` (slot → snippet)
- `lib/components/Modal.svelte` (slot → snippet)
- `lib/components/ClaimButton.svelte`
- Remaining `lib/components/picker/*`, `lib/components/player/PlayerControls.svelte` (keep audio-adjacent files legacy if they couple to AudioElement)

After this phase the do-not-migrate list above is the only legacy code remaining.

---

## Deletions enabled by migration

After each phase, these patterns should be removed (don't leave them as zombie code):

- `import { createEventDispatcher } from 'svelte'` in migrated files.
- `const dispatch = createEventDispatcher<...>()` declarations.
- `on:eventName` listeners on migrated children (use `oneventName=`).
- `<slot />` and `<slot name="...">` in migrated files (use `{@render}`).
- `get(store)` calls inside migrated components (read properties directly from rune modules).
- `writable()` / `derived()` imports in migrated `.svelte.ts` files.
- Manual `subscribe` + cleanup pairs (rune `$effect` handles teardown).

## Conventions for new (Svelte 5) code

These apply to every new `.svelte` and `.svelte.ts` file:

1. **Props**: always use one destructure with a `Props` type alias.

    ```svelte
    <script lang="ts">
        type Props = {
            seg: Segment;
            readOnly?: boolean;
            onSplit?: (op: SplitOp) => void;
        };
        let { seg, readOnly = false, onSplit }: Props = $props();
    </script>
    ```

2. **Events**: callback props named `on<event>` (lowercase, camelCase tail). Never `createEventDispatcher`.
3. **Reactive derivations**: prefer `$derived(expr)`. Use `$derived.by(() => { ... })` only when the body is multi-statement.
4. **Side effects**: `$effect(() => { ... })`. Return a teardown function when needed. Never use `$effect` for derivation.
5. **Two-way bindings**: opt-in only via `$bindable()`. If a value doesn't need to flow back to the parent, don't make it bindable.
6. **Shared reactive state**: lives in `.svelte.ts` modules. Components import named bindings. No more `writable()` wrapping for tab-local state.
7. **Slots**: use snippets (`children: Snippet` for default, named props for named slots) and `{@render foo()}`.
8. **Stores**: still permitted for the **global** singletons (toast, editing-mode, current-user) until Phase 7. Tab-scoped state should not introduce new stores — use rune modules.

## Tooling caveats

- `svelte-check` v4 is required for rune type-checking; v3 ignores runes.
- `eslint-plugin-svelte` must understand runes — verify rules on first rune-mode file or upgrade to a v5-aware release.
- `@testing-library/svelte` 5.x supports Svelte 5; component tests using `render(Component, { props })` keep working but the `component.$on('event')` API is gone — tests that asserted dispatched events need to pass callback-prop mocks instead.
- HMR with `@sveltejs/vite-plugin-svelte` v5 may behave differently for canvas — flag during Phase 0 smoke test.
- Don't enable `compilerOptions.runes = true` globally; per-file detection is intentional so legacy files stay legacy.

## Tracking

When a file is migrated, remove its row from the audit table at the top by re-running the audit script. The do-not-migrate list at the top is the steady-state target — when only those files have legacy syntax, the migration is "done".
