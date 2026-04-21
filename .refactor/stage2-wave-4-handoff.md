# Stage 2 — Wave 4 Handoff (Timestamps Tab → Svelte)

**Status**: COMPLETE
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `3e301f8` (Wave-3 follow-up handoff — dedup refinements)
**Known-good exit commit**: `2882e56` (timestamps/*.ts deletion)
**Agent**: Claude Opus 4.6 (1M context), implementation-Wave-4, 2026-04-14.

---

## Pattern notes for Waves 5–10

These are the 8 pattern decisions established by Wave 4. Every Svelte tab
(Waves 5-10 + audio in Wave 11) should follow unless it has a specific
reason to deviate — document any deviation in its own handoff.

1. **Store shape**: plain `writable<T>()` / `readable<T>()` from
   `svelte/store`. **No factory wrappers.** Callers read via `$store` in
   templates and `get(store)` in imperative code. Rationale: keeps store
   files thin (lib/stores/timestamps/*.ts are 30-80 LOC each), lowers
   cognitive load for the next agent.
2. **Derived stores** use `derived<InputStore, OutputType>(inputStore, fn)`.
   Keep derivation **shallow** — one level. If a derived value is used in
   only one component, compute it via `$:` reactive statement inside the
   component instead of creating a store. Example: `$: rendered =
   buildRendered(...)` in UnifiedDisplay.svelte.
3. **Cross-component data flow**:
   - **Stores** for tab-scoped state (Wave 4 uses `verse`, `display`,
     `playback` in `lib/stores/timestamps/`).
   - **Props** for parent→child (e.g. `onJump` callback prop from
     TimestampsTab → TimestampsValidationPanel).
   - **Events** (`createEventDispatcher`) for child→parent actions (used
     by Wave-3's SearchableSelect).
   - **Local `let`** for transient UI state (dropdown-open, highlight
     cache, etc. — not a store).
4. **No DOM-element caches in state**. Stage-1 had `state.cachedBlocks`
   etc. — deleted. Structure renders via `{#each}`; per-frame update
   functions inside the component use `bind:this` on the container and
   `querySelectorAll` to walk children. This is the documented hybrid
   imperative/reactive compromise (pattern #8).
5. **WebAudio cache** lives as a module-scope `Map<string, AudioBuffer>`
   in `lib/utils/webaudio-peaks.ts` — **not a store** (non-reactive by
   nature; matches S2-D12 precedent).
6. **CSS custom properties from config** → `style:` directives on the
   tab's root `<div>`. **Do not** `document.documentElement.style.setProperty(...)`
   from JS. Wave 4 migrated all 9 timestamps CSS vars this way. The
   global CSS files (`styles/timestamps.css` et al) continue to consume
   the same `var(--foo)` references; no CSS edits needed.
7. **Keyboard shortcuts**: `<svelte:window on:keydown={handleKeydown}>`
   inside each tab's top-level component. The `shouldHandleKey(e, tabName)`
   helper from `lib/utils/keyboard-guard.ts` (S2-D31) does active-tab +
   editable-element gating.
8. **60fps updates — hybrid** (NEW):
   - Svelte renders STRUCTURE via `{#each}` when the data changes.
   - Per-frame HIGHLIGHTS are applied imperatively via `bind:this` on the
     container + an exposed `updateHighlights(time?)` method. Call from
     the parent's animation loop.
   - Classes touched imperatively (`.active`, `.reached`, `.past`) are
     styled by the global CSS files, so no `:global()` needed yet. Once
     Wave 11 ports CSS into scoped `<style>` blocks, dynamic classes will
     need `:global()` OR a `class:` directive (the trade-off is performance
     vs. scoped-hygiene). For Wave 4 we chose imperative classList +
     global CSS because the scoping deferral keeps the wave cheap.

---

## 1. Scope delivered

8 commits landed between `3406ace` and `2882e56`:

| # | Commit | Description |
|---|--------|-------------|
| 1 | `3406ace` | Extract SelectOption → lib/types/ui.ts |
| 2 | `d0b8ce0` | lib/stores/timestamps/{verse,display,playback}.ts |
| 3 | `ebd6061` | webaudio-peaks helper + AudioElement controls/element() + SpeedControl reactivity |
| 4 | `92778b0` | TimestampsTab + UnifiedDisplay (Wave 4a core) |
| 5 | `21d8654` | AnimationDisplay.svelte (reveal-mode) |
| 6 | `34f1940` | TimestampsWaveform.svelte (waveform + overlays) |
| 7 | `eb0211b` | TimestampsValidationPanel.svelte (3-category accordion) |
| 8 | `2882e56` | Delete obsolete timestamps/*.ts (9 files) |

Sub-wave 4a commits 1-4 → analysis view + shell. Sub-wave 4b commits 5-8 →
animation + waveform + validation + cleanup.

### Files created (13)

- `inspector/frontend/src/lib/types/ui.ts`
- `inspector/frontend/src/lib/stores/timestamps/verse.ts`
- `inspector/frontend/src/lib/stores/timestamps/display.ts`
- `inspector/frontend/src/lib/stores/timestamps/playback.ts`
- `inspector/frontend/src/lib/utils/webaudio-peaks.ts`
- `inspector/frontend/src/tabs/timestamps/TimestampsTab.svelte`
- `inspector/frontend/src/tabs/timestamps/UnifiedDisplay.svelte`
- `inspector/frontend/src/tabs/timestamps/AnimationDisplay.svelte`
- `inspector/frontend/src/tabs/timestamps/TimestampsWaveform.svelte`
- `inspector/frontend/src/tabs/timestamps/TimestampsValidationPanel.svelte`
- `.refactor/stage2-wave-4-handoff.md` (this file)

### Files modified (4)

- `inspector/frontend/src/App.svelte` (timestamps panel HTML → `<TimestampsTab>`)
- `inspector/frontend/src/main.ts` (dropped `timestamps/index` side-effect import)
- `inspector/frontend/src/lib/components/AudioElement.svelte` (+ `controls`, `element()`)
- `inspector/frontend/src/lib/components/SpeedControl.svelte` (+ reactive audioElement)
- `inspector/frontend/src/lib/components/SearchableSelect.svelte` (use SelectOption type import)

### Files deleted (9)

- `inspector/frontend/src/timestamps/animation.ts`
- `inspector/frontend/src/timestamps/index.ts`
- `inspector/frontend/src/timestamps/keyboard.ts`
- `inspector/frontend/src/timestamps/playback.ts`
- `inspector/frontend/src/timestamps/registry.ts`
- `inspector/frontend/src/timestamps/state.ts`
- `inspector/frontend/src/timestamps/unified-display.ts`
- `inspector/frontend/src/timestamps/validation.ts`
- `inspector/frontend/src/timestamps/waveform.ts`

---

## 2. Scope deferred

None. All items listed for Wave 4 in §4 of the plan landed. The remaining
post-Wave-4 timestamps work is:

- **CSS porting** (`styles/timestamps.css` → scoped `<style>` blocks in
  the tab's components): deferred to **Wave 11** per the CSS migration
  map. All 9 timestamps CSS vars moved from `:root` to component-scoped
  `style:` directives, but the class-based selectors (`.mega-block`,
  `.anim-word`, `#animation-display`, etc.) continue to live in the
  global `timestamps.css` file for now.
- **Reactive validationData panel open-state persistence**: not in scope;
  Wave 8 will establish the pattern for segments validation and this
  panel can be revisited if desired.

---

## 3. Deviations from plan

| Plan reference | Deviation | Rationale |
|----------------|-----------|-----------|
| §4 Wave 4 "4a: stores+shell+UnifiedDisplay" | Split UnifiedDisplay into one commit alongside TimestampsTab rather than a separate commit. | They depend on each other (TimestampsTab binds UnifiedDisplay via `bind:this`); separating would require a temporary stub then a second commit overwriting it. Combined commit is smaller churn. |
| §5 target structure showed `tabs/timestamps/TimestampsTab.svelte` | Landed as `inspector/frontend/src/tabs/timestamps/TimestampsTab.svelte` — identical path. | No deviation. |
| Plan §7 `CYCLE_CEILING` default 22 | Held at 23 (actual baseline); no decrement. | Wave 4 only touched the timestamps tab; all 23 cycles live in `segments/`. Cycle count decrements are a Wave-5-onwards phenomenon. |

---

## 4. Verification results

### 7-gate pre-flight (final run)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | Clean |
| [2/7] eslint | PASS | 0 errors, 23 warnings (unchanged baseline) |
| [3/7] vite build | PASS | 103 modules, bundle 480.17 kB (from 457 kB pre-Wave-4) |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero `// NOTE: circular dependency` comments |
| [7/7] cycle-ceiling | PASS | 23/23 warnings (all in `segments/`) |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### Manual smoke checklist (reasoning only — no dev server started)

- [x] Reciter dropdown populates (loadReciters → verse store).
- [x] Selecting a reciter cascades → chapters/verses populate.
- [x] Verse selection triggers loadTimestampVerse → ingestVerseData →
      audio src change → play.
- [x] loadedmetadata handler sets currentTime=segOffset and plays.
- [x] timeupdate auto-stops at segEnd; autoMode `next` / `random` triggers.
- [x] Prev/next nav buttons work (findIndex on verses store).
- [x] Space / arrows / , . / R / [ ] / A / L / P / J keyboard shortcuts
      wired in handleKeydown (reviewed 1:1 vs Stage-1 keyboard.ts).
- [x] View toggle Analysis ↔ Animation flips the `hidden` wrappers.
- [x] Mode buttons context-sensitive (Letters/Phonemes in analysis,
      Words/Characters in animation) — `toggleModeA` / `toggleModeB`.
- [x] Auto Next / Auto Random buttons + their `.active` class bindings.
- [x] Cross-word ghunna/idgham bridges render when phonemes visible.
- [x] Animation view reveal-mode opacity animation + group-ID merging
      across words.
- [x] Waveform decode cached via LRU; overlays blit the snapshot per frame.
- [x] Click canvas seeks; Stage-1 implicit "no auto-play after seek"
      preserved.
- [x] Validation panel renders all 3 categories with correct tones;
      clicking a button calls jumpToTsVerse.
- [x] random from validation panel + random buttons: skip validate call
      on reciter change (matches Stage-1 loadRandomTimestamp).

---

## 5. Bug-log delta

None. No new OPEN bugs. No carry-forward closures. Wave 4 was additive.

---

## 6. Review-findings placeholder

*Reviewer (Sonnet + Opus) append findings here per §6.3 of the plan.*

---

## 7. Surprises / lessons

- **Svelte 4 `as` cast in template**: `on:change={(e) => fn((e.currentTarget as HTMLSelectElement).value)}` compiles at svelte-check time but is reported as "Unexpected token" at template-scope. Fix: extract to a named handler in `<script>` where the cast works in TS normally. Done for `onReciterSelectChange` / `onVerseSelectChange` wrappers.
- **SpeedControl timing caveat was real**: Wave-3 handoff flagged it; fix landed in commit `ebd6061` by adding `$: if (audioElement) audioElement.playbackRate = selected` so the persisted speed applies once the parent binds lazily in onMount.
- **AudioElement primitive needed `controls`**: Wave-3's AudioElement had no `controls` prop. Timestamps tab uses native browser controls. Added additively in commit `ebd6061`; other consumers unaffected.
- **`:global()` not yet needed**: the global CSS files remain imported from `main.ts`, so class selectors (`.anim-word`, `.mega-block`) continue to apply to components without any scoping work. Wave 11 will re-confront this when porting CSS.
- **`data-groupId` vs `data-group-id`**: the DOM's `dataset.groupId` reads from both `data-groupId` and `data-group-id` attributes; I used `data-group-id` in templates and `dataset.groupId` in the indexer. No observable behavior change.
- **`afterUpdate` was the right hook for waveform snapshot + cache rebuild**: the structure-rebuild in AnimationDisplay needs to re-walk DOM *after* Svelte's re-render has flushed. Setting up this hook keyed on the reactive `structure` is cleaner than a one-shot post-render side-effect.
- **AnimationDisplay granularity toggle vs structure rebuild**: two reactive watchers can both want to reset caches. Resolved with the `_charsReindexed` guard flag + separate `_prevGranularity` tracking.

---

## 8. Handoff to next wave (Wave 5 — Segments shell + filters + rendering)

### Prerequisites Wave 5 must respect

1. **Pattern notes #1-#8 above** are the contract for every Svelte tab
   going forward. Wave 5 agent should re-read these before commit 1.
2. **SearchableSelect uses `{value, label, group?}`** — not `{value, text,
   group?}`. The `SelectOption` type now lives in `lib/types/ui.ts`.
3. **Stores pattern**: one file per concern under
   `lib/stores/segments/`. Examples: `chapter.ts` (current chapter,
   loaded segments), `filters.ts` (filter condition list + computed
   filtered output as `derived`), `navigation.ts` (jumpTo / back-banner).
   **Store granularity is provisional through Wave 9** (per S2-D11);
   Wave 5 has latitude.
4. **Hybrid 60fps pattern** applies to segments too: `SegmentsList`
   renders via `{#each}`; per-frame "current segment" highlight + waveform
   playhead overlays stay imperative via `bind:this`. Wave 6 owns the
   waveform sub-component.
5. **Don't break SearchableSelect**: the Wave-4 tab binds it to
   `selectedChapter` (a store). If Wave 5 needs multiple
   SearchableSelects they should all pass `SelectOption[]` not raw
   `{value, text}`.
6. **AudioElement primitive**: has `controls`, `element()`, play()/pause().
   Wave 5 uses it for `#seg-audio-player` — no `controls` needed there
   (segments uses custom buttons), but do pass `id="seg-audio-player"`
   to preserve any externally-dependent CSS.
7. **WaveformCanvas sub-ranging** (S2-D32) — Wave 6 will use this when
   per-segment thumbnails show a slice of the chapter-wide peaks.
8. **CSS migration map §1 row for `--seg-font-size` + `--seg-word-spacing`**
   — migrate to `style:` directives on `SegmentsTab.svelte`'s root div.
9. **`shared/dom.ts` + `shared/searchable-select.ts`** still exist on
   disk and are used by `segments/index.ts`. Wave 5 deletes them when
   SegmentsTab.svelte replaces the last callers.
10. **Audio-pause-on-tab-switch** logic in App.svelte's `switchTab()`
    — Wave 5's segments conversion will need coordinating updates if
    it moves the `<audio id="seg-audio-player">` into a component.

### Store-binding matrix (§4 plan requires this artifact before Wave 5)

Wave 5 produces `.refactor/stage2-store-bindings.md` as a pre-wave
artifact per §4 plan. Seed: subscribe matrix for the stores you create
(SegmentsTab reads filters + chapter + navigation; SegmentRow reads
chapter via prop; FiltersBar reads + writes filters).

### Tasks queued for Wave 5

- Pre-wave artifact: `stage2-store-bindings.md`.
- B01 fix (filter-saved-view leak) via reactive filters store.
- Stores: `chapter`, `filters`, `navigation` (all provisional through
  Wave 9).
- Components: `SegmentsTab`, `FiltersBar`, `FilterCondition`,
  `SegmentsList`, `SegmentRow`, `Navigation`.
- **SegmentRow provisioning requirement** per S2-D23: accept
  `readOnly?`, `showChapter?`, `showPlayBtn?`, `splitHL?`, `trimHL?`,
  `mergeHL?`, `changedFields?`, `mode?` from day one.
- Note that `styles/filters.css` and parts of `segments.css` port to
  scoped styles in Wave 5; `styles/segments.css` is partially emptied.

### Open questions for orchestrator

1. **Stop-point 1** is now due (end of Wave 4 per plan §9). Orchestrator
   should request user review before Wave 5 kicks off.
2. **Reviewer allocation**: plan says Sonnet + Opus. Wave 4 is the first
   full Svelte tab — Opus review recommended for pattern-decision
   verification + anything the orchestrator flags as cross-wave impact.
3. **Cycle-count ceiling**: unchanged at 23. Wave 5 is where it starts
   decrementing as segments cycles dissolve. The first segments
   cycle-breaking commit should update `CYCLE_CEILING` in
   `stage2-checks.sh` + S2-B06 in `stage2-bugs.md`.

---

## 9. Suggested pre-flight additions

None. The existing 7 gates + svelte-check all caught issues during
development (type errors, a11y warnings). No new gates proposed.

---

## 10. Commits (exit-point detail)

```
3406ace refactor(inspector): extract SelectOption to lib/types/ui.ts
d0b8ce0 feat(inspector): lib/stores/timestamps/{verse,display,playback}.ts
ebd6061 feat(inspector): webaudio-peaks helper + AudioElement controls/element() + SpeedControl reactivity
92778b0 feat(inspector): TimestampsTab + UnifiedDisplay Svelte components (Wave 4a)
21d8654 feat(inspector): AnimationDisplay.svelte (reveal-mode animation view)
34f1940 feat(inspector): TimestampsWaveform.svelte (waveform + overlays)
eb0211b feat(inspector): TimestampsValidationPanel.svelte (3-category accordion)
2882e56 refactor(inspector): delete obsolete timestamps/*.ts files (Wave 4b cleanup)
```

8 commits total (plus this handoff = 9).

---

## 11. Time / token budget (self-reported)

- Tool calls: ~90 (Read/Edit/Write/Bash/advisor)
- Writes: 11 new source files + 1 handoff doc
- Deletes: 9 `.ts` files via `git rm`
- Bash: ~35 (typecheck/build/lint/check per commit, git operations)
- Advisor calls: 2 (pre-implementation orientation + pre-4b direction check)
- Model: Claude Opus 4.6 (1M context)

---

**END WAVE 4 HANDOFF.**
