# Inspector Frontend Refactor Notes

## Overview

The inspector frontend is a Flask-served SPA with three tabs (Timestamps, Segments, Audio). The backend (Flask, ~4,000 lines) is well-structured and stays unchanged across both refactor stages. Two stages, landed in order: **Stage 1 — TypeScript + Vite**, **Stage 2 — Svelte on top**.

## Why Refactor

### Problems with vanilla JS at this scale

- **DOM-manipulation tax**: every UI feature is imperative `createElement` / `addEventListener` boilerplate. Before the refactor, roughly 60% of frontend code was DOM plumbing, not business logic.
- **State–DOM sync bugs**: mutating state (e.g. `state.activeFilters`) without manually calling the corresponding render function leaves the UI stale. Invisible to linters; only caught by manual testing.
- **No type safety**: typos in state property names silently create new properties. Refactoring across 40+ files is grep-and-pray.
- **Duplication without a component model**: `playback.js` existed in both tabs, `validation.js` too. Shared UI patterns got copy-pasted and diverged.
- **Untestable UI**: JS modules mix logic and DOM manipulation in the same functions. Can't unit-test rendering without a browser.

### Why Svelte over other frameworks (the Stage-2 choice)

- **Compile-time, not runtime**: no virtual DOM, no framework runtime shipped. Output is vanilla JS — similar to what we write today, just generated correctly.
- **Minimal new syntax**: `.svelte` files are HTML + CSS + JS in one file. `{variable}`, `on:click` (or `onclick={...}` in Svelte 5), `class:selected`. Not a new language.
- **Component testing**: `@testing-library/svelte` renders components in isolation without a browser. Props in, events out.
- **Low cognitive cost for future contributors**: a collaborator reading `SegmentRow.svelte` sees markup that looks like HTML. Reading the pre-refactor `history-rendering.js` (631 lines of nested `createElement` calls) requires mentally executing the code.
- **Developer is Claude**: the "rewrite cost" argument is weaker when the primary maintainer can systematically convert modules without fatigue.

---

## Stage 1 — TypeScript + Vite ✅ DONE

Landed as 9 commits on the `worktree-refactor+inspector-modularize` branch (Phases 0–7 + a docs-hygiene follow-up).

### Delivered

- `inspector/frontend/` workspace with Vite + TypeScript + ESLint + Prettier. Dev server at :5173 (HMR, proxies `/api` + `/audio` to Flask :5000). Prod build to `inspector/frontend/dist/`, served by Flask.
- All 44 source files moved from `inspector/static/js/` to `inspector/frontend/src/`, renamed `.js` → `.ts`, sub-foldered (`segments/{edit,history,validation,waveform,playback}/`, `timestamps/`, `audio/`, `shared/`, `types/`).
- Chart.js migrated from CDN to npm (`chart.js` + `chartjs-plugin-annotation`). Single registration point in `shared/chart.ts`; no more `window.Chart` global.
- Shared surface introduced: `shared/api.ts` (typed `fetchJson<T>` boundary), `shared/animation.ts` (`createAnimationLoop`, wired into both playback modules), `shared/accordion.ts`, `shared/audio.ts` (`safePlay` — AbortError handling).
- Type foundation: `types/api.ts` (every `/api/*` response shape, hand-mirrored from the Flask routes), `types/domain.ts` (13 core shapes, 11 per-category validation item types), `types/registry.ts` (typed signatures for the `registerHandler` / `registerKeyboardHandler` / `registerEditModes` / `registerEditDrawFns` / `registerWaveformHandlers` / `setClassifyFn` injection pattern), `segments/waveform/types.ts` (typed `SegCanvas` extension for ad-hoc canvas fields).
- Both tab `state.ts` files fully typed with a `_UNSET` sentinel convention for DOM refs.
- All 44 files pass TSC under `strict: true` + `noImplicitAny: true` + `strictNullChecks: true` + `noUncheckedIndexedAccess: true` + `allowJs: false`. Zero `@ts-nocheck` pragmas anywhere in `src/`.
- Lint: 0 errors, 9 warnings (all trivial unused-import nits).

### Bug-log outcomes

Twenty tracked rows (`.refactor/stage1-bugs.md`):

- **Seeded** (pre-refactor): 8 total. 4 CLOSED during the refactor (2 as not-a-bug after re-audit, 2 mitigated by the shared helpers). **4 remain OPEN** — see the Stage-1.5 section below.
- **TS-caught**: 3 total, all CLOSED (B13 null-race in validation rAF, B14 `silence_after_ms` null type, B17 boundary-mismatch tooltip using wrong field names).
- **API drift**: 9 total, all CLOSED. Every row was a type-level alignment to actual server emit; zero runtime changes.
- **New introduced**: **0** across all 7 phases.

### What Stage 1 did NOT solve (by design)

Stage 1 was scoped to types-only. Explicitly out of scope:

- State-DOM sync is type-checked but still manually invoked. Every mutation must call the right render function.
- ~60% of the code is still imperative DOM plumbing (`history/rendering.ts` is still 631 lines of `createElement`).
- Shared UI patterns (`SearchableSelect`, the audio-player controls, waveform canvas) are typed but not yet components; the duplication is structural, not eliminated.
- CSS is still 9 separate files under `src/styles/`; not co-located with the code it styles.
- UI behavior is still untestable — only pure logic gained testability.
- The registration pattern (`registerHandler` etc.) was typed, not redesigned.

---

## Stage 1.5 — Open bugs (orthogonal to Stage 2)

Four seeded logic bugs remain OPEN because fixing them requires state-shape changes that Stage 1's anti-goals prohibited. They can be addressed either as a dedicated short sprint before Stage 2, or absorbed into Stage 2's reactivity model (several would disappear by construction).

| ID  | Priority | Summary | Location |
|-----|----------|---------|----------|
| B01 | medium | Filter state saved-view leak — UI wedges with no segments while `segAllData.segments` is still populated | `segments/filters.ts:166-168, 255-258` |
| B02 | **medium-high** | `segData` / `segAllData` chapter-index desync on delete — data-integrity risk at save time | `segments/edit/delete.ts:30-43` |
| B04 | low-medium | Waveform peaks orphaned after audio-proxy URL rewrite — cosmetic black canvas until re-fetch | `segments/playback/audio-cache.ts:27-40` |
| B05 | low | `state._splitChainUid` not restored after undo — minor history-view state loss | `segments/state.ts` |

B01, B04, and B05 are all "forgot to update derived state" patterns that Svelte's reactivity eliminates by design. B02 is a genuine logic bug that needs a fix regardless.

---

## Post-Stage-1 deferred work

### Timestamps tab — apply segments' registration/injection pattern to break circular imports

**Status:** DEFERRED — flagged by the post-Stage-1 structure critique (2026-04).

Five files in `inspector/frontend/src/timestamps/` still carry `// NOTE: circular dependency` comments where a sibling imports `./index`:
- `timestamps/waveform.ts:11`
- `timestamps/validation.ts:10`
- `timestamps/unified-display.ts:14`
- `timestamps/animation.ts:16`
- `timestamps/keyboard.ts:14`

These are function-level cycles that work at runtime because calls only happen after all modules have loaded, but they are timing footguns and ESLint `import/no-cycle` (being added in this cleanup pass) will flag them.

The segments tab solved the same problem in Phases 3–6 via registration / injection (`setClassifyFn`, `registerEditModes`, `registerEditDrawFns`, `registerWaveformHandlers`, `registerHandler`, `registerKeyboardHandler` — all typed through `src/segments/registry.ts`). Timestamps never received that treatment because the tab isn't an editor and the cycles are lighter.

**When to do this**: fold into Stage 2 (Svelte migration), since any component extraction will force the coupling question anyway. Estimated effort: 2-3 hours.

**What to do**:
1. Identify the 5 function calls that cross the cycle (each sibling calls something in `timestamps/index.ts`).
2. Create `timestamps/registry.ts` typing each function with a `Ts*Fn` signature.
3. Replace each `import { foo } from './index'` in the siblings with a registry lookup.
4. Have `timestamps/index.ts` register the functions at module init.
5. Verify typecheck and that all five `// NOTE: circular dependency` comments can be removed cleanly.


## Stage 2 — Svelte on top of TypeScript + Vite

### Motivations (what Stage 2 targets)

The typed foundation is a bet on Stage 2. The explicit goals:

1. **Eliminate the state-sync bug class by construction.** Every filter, edit, save, undo, history, or validation mutation currently has to call the right render function. Svelte's reactivity makes that automatic — the compiler wires derivations to their dependencies. B01/B04/B05 disappear as categories, not as point fixes.
2. **Collapse duplication into real components.** `SearchableSelect`, `AudioPlayer` (duplicated across segments + timestamps tabs), `Waveform` (two drawing paths), `ValidationBadge`, `AccordionPanel` become single source definitions with props + events — not imperative DOM wrappers that export functions.
3. **Unlock UI testing.** `@testing-library/svelte` renders components in isolation. Edit-mode drag behavior, validation-panel toggle logic, history-batch diff rendering — all become unit-testable in Vitest instead of requiring manual click-through.
4. **Co-locate CSS with behavior.** 9 CSS files currently live in `src/styles/` and are imported by name from `main.ts`. Co-located `<style>` blocks per `.svelte` component give scoped class names by default and eliminate cross-file coupling.
5. **Retire the registration pattern.** `registerHandler` / `registerKeyboardHandler` / `registerEditModes` exist to break circular imports between event-delegation, keyboard, and concrete edit modules. Svelte's component tree inverts the dependency: parents pass handlers as props, children emit events. No registry needed.
6. **Reduce cognitive load of future contributors** (including future-me and future Claude sessions). Markup is visible where behavior lives; component boundaries mirror visual boundaries.

### Expected gains

- **Bugs eliminated** by reactivity (estimate ≥3 of the 4 remaining OPEN rows, plus every future bug of the same shape).
- **~40–50% LOC reduction** on the heavy rendering modules. `history-rendering.ts` (631 LOC) + `error-cards.ts` (452 LOC) + `validation/index.ts` (529 LOC) are the top three candidates. Template-based rendering is dramatically terser than equivalent imperative DOM code.
- **Component test suite** unblocks real CI coverage for the first time. Pure logic got Vitest in Stage 1; now the UI does too.
- **Fewer commits needed for UI tweaks**. A typical change becomes "edit one `.svelte` file" instead of "edit the state.ts field, the render function, the event handler, and the CSS file".
- **Bundle size roughly flat.** Svelte compiles to imperative DOM ops; the per-component overhead is small (~1–3 kB before gzip, typically less than the duplicated imperative code it replaces).

### Risks

Honest accounting — this is the harder stage.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Segments tab is the biggest conversion surface (~24 modules, 6,100 LOC, the most complex state machine of any tab) | High | High | Convert tab-by-tab; within segments, start with `edit/*` (clear modal-like boundaries), save `history/rendering.ts` for last. Each sub-tab is independently mergeable. |
| `history-rendering.ts` is 631 LOC of nested imperative DOM with SVG arrow drawing and split-chain layout | Certain | Medium | Treat as a rewrite, not a port. Pull the SVG-arrow geometry into a helper; render batches + ops declaratively; keep the DOM shape stable so the CSS file ports over cleanly. |
| Complex derived state: `state._splitChains: Map<string, SplitChain>`, `_findCoveringPeaks` memoization, `_segPeaksByUrl` caches don't map 1:1 to `writable`/`derived` | High | Medium | Keep non-reactive caches as plain `Map` fields on a context object, not in a store. Use stores for what the UI actually binds to; keep computation-caches outside reactivity. |
| IntersectionObserver + waveform canvas lifecycle (lazy peaks, segment observer, cleanup on chapter switch) | Medium | Medium | `onMount` / `onDestroy` cover this cleanly; `bind:this` exposes the canvas. The tricky bit is shared caching across component remounts — keep the cache in a module-scope Map, not in component state. |
| Chart.js integration (stats histograms) — imperative lifecycle inside `onMount`/`onDestroy` | Low | Low | Established pattern; one `<canvas bind:this={el}>` + an `onMount(() => new Chart(el, config))` is enough. Annotation plugin continues to work. |
| Svelte 5 runes (`$state` / `$derived`) vs Svelte 4 stores (`writable` / `derived`) — different reactivity models | Medium | Low–Medium | **Decision to make up-front** (see below). Svelte 5 is stable and the default; Svelte 4 is the better-documented legacy path. |
| TypeScript ↔ Svelte language-server quirks (type narrowing inside `{#if}` blocks, `$props()` vs prop syntax in Svelte 5) | Low | Low | Tooling is mature; VS Code + `svelte-check` covers most cases. Budget time for occasional workarounds. |
| Loss of direct state observability — a store mutated without `set`/`update` won't fire reactivity | Medium | Medium | Typed store wrappers (`createSegmentsStore(): Store` with methods instead of raw `writable`) prevent accidental direct mutation and document the intended surface. |
| The registration pattern's import-order invariants (edit modules register at module-init before DOMContentLoaded) don't translate to Svelte's lazy-instantiated components | Certain | Low | By construction, the problem it solved (circular imports) doesn't exist in a component tree — handlers flow via props/events. Delete the registry; don't port it. |
| CSS specificity: 9 imported CSS files have implicit global dependencies (e.g. `.segment-row.has-repetition .wrap-word`) | Medium | Low–Medium | Port styles to scoped `<style>` per-component in the same conversion pass; the compiler catches unused selectors. Keep `base.css` as the one remaining global file (resets, fonts, root variables). |
| Accessibility regressions from template-driven re-renders (e.g. focus loss on accordion toggle) | Medium | Medium | Svelte's `tick()` + `bind:this` + explicit `focus()` calls handle it, but manual review per-component is needed. Track as a review-checklist item per tab. |
| Virtualization: rendering 10,000+ segment rows as components may stress reactivity | Low at current scale | Medium | Current UI already only renders the filtered + visible subset; the risk is theoretical. If it materializes: `svelte-virtual-list` or similar drop-in. |
| Build output committed vs not — Flask currently serves `frontend/dist/` and expects it built | Certain | Low | Continue gitignoring `dist/`; `inspector/app.py` already fails loudly with a clear build command if `dist/index.html` is missing. |
| E2E tests still absent at start of Stage 2 | Certain | Medium | Stage 2 is the natural time to add Playwright — edit operations (trim drag, split confirm, merge with history re-render) especially benefit. |

### Design decisions to make up-front

These should be settled before Phase 2.0 starts, because changing them mid-conversion is expensive.

1. **Svelte 5 (runes) vs Svelte 4 (legacy stores).**
   - Svelte 5 is the default as of late 2024; runes (`$state`, `$derived`, `$effect`) are the modern reactivity primitive.
   - Svelte 4's `writable`/`derived` is better-documented, has more blog posts and Stack Overflow answers.
   - **Recommendation**: Svelte 5. New code deserves the current model; documentation is adequate; runes solve real ergonomic issues with stores.
2. **Component granularity: row vs panel vs widget.**
   - Coarse (`<SegmentsList>` that iterates internally): less reactivity overhead, easier to start, harder to style/test.
   - Fine (`<SegmentRow>` per segment): cleaner boundaries, per-row reactivity, best for testability. Main risk is render cost on large chapters (mitigated — see virtualization).
   - **Recommendation**: fine-grained `<SegmentRow>`, accept minor reactivity overhead, virtualize only if benchmarks say so.
3. **State model: one store per tab vs split by concern.**
   - Single mega-store per tab (closest to current `state.ts`): minimum disruption.
   - Split: `filtersStore`, `editModeStore`, `saveStore`, `historyStore`: cleaner testing, less prop-drilling, more modules to track.
   - **Recommendation**: split along the natural lines of the existing sub-folders (`edit/`, `history/`, `validation/`, `waveform/`, `playback/`, plus one `chapter/` store for the currently-loaded data). State-object pattern becomes store-per-concern pattern.
4. **Svelte routing: plain Svelte (vite-plugin-svelte) vs SvelteKit.**
   - Flask already owns server-side routing and auth. SvelteKit would conflict and add complexity.
   - **Recommendation**: plain Svelte. No SSR, no file-based routing, no client-side router (the inspector has no URLs beyond `/`).
5. **Testing framework: Vitest + @testing-library/svelte vs Playwright component tests.**
   - Vitest + testing-library is the dominant, fastest, best-documented option.
   - Playwright component tests run in a real browser — slower, but catches CSS-layout and animation bugs Vitest misses.
   - **Recommendation**: Vitest + testing-library for unit/component; add Playwright at the `App.svelte` level for E2E edit-flow smoke tests (split → save → undo → reload).
6. **Styling strategy.**
   - Co-located `<style>` blocks (scoped by default): most Svelte-idiomatic.
   - Tailwind: would require rewriting 2,000 LOC of CSS.
   - **Recommendation**: co-located `<style>`. `base.css` remains for resets, fonts, and CSS variables. The existing per-domain CSS files are ported into their respective components.
7. **Fix OPEN bugs before, during, or after conversion?**
   - B02 (data-integrity) should land BEFORE Stage 2 — it's a real bug, has no reactivity component, and shouldn't be bundled with a structural rewrite.
   - B01, B04, B05 either disappear during conversion (reactivity handles them) or become trivial one-liners after. Either path is fine.
   - **Recommendation**: fix B02 as a standalone pre-Stage-2 commit. Let Stage 2 absorb B01/B04/B05.
8. **Python-side schema layer (Pydantic / Marshmallow / Flask-Smorest).**
   - Not strictly needed for Stage 2, but the client hand-writes all response shapes today. Any divergence is caught via the bug log (worked 9 times in Stage 1), but it's reactive, not preventive.
   - **Recommendation**: adopt Pydantic on the Flask side as a parallel / follow-on task. Low effort, high value; prevents future drift at the server boundary. Can happen before, during, or after Stage 2.
9. **Migration order within Stage 2.**
   - **Audio tab first** (1 module) — lowest-risk warm-up.
   - **Shared components next** — extract `SearchableSelect`, `AudioPlayer`, `Waveform` so the harder tabs can use them.
   - **Timestamps tab** (7 modules) — medium complexity, relatively independent of segments.
   - **Segments tab** last, sub-foldered:
     1. `playback/` + `waveform/` (foundational for rendering)
     2. `edit/` (6 modules, clear per-mode boundaries)
     3. `filters/` + `navigation/` + `stats/`
     4. `validation/` (already reasonably factored)
     5. `save/undo/history/` — the tallest pole (`history-rendering.ts` is a rewrite).
10. **Conversion mechanics.**
    - One `.ts` module can be converted to one `.svelte` component when it has UI concerns. Pure logic (ref parsing, arabic-text helpers, peak math) stays as `.ts`.
    - Every conversion PR must preserve runtime behavior; typecheck + build + a manual smoke of the affected tab is the per-step gate.
    - Maintain an append-only Stage-2 bug log parallel to `.refactor/stage1-bugs.md`.

### Dependency impact

- **Collaborators using the inspector**: no change. `pip install -r requirements.txt` + `python3 inspector/app.py`. Pre-built assets at `inspector/frontend/dist/` (currently gitignored — decide whether to commit built artifacts for Python-only contributors, or document the one-time `npm install && npm run build` prerequisite).
- **Developers modifying frontend**: need Node 20+. `npm install && npm run dev`.
- **Backend contributors**: no change.

### Target folder structure (aspirational)

```
inspector/
├── app.py
├── config.py, constants.py, requirements.txt
├── routes/, services/, utils/         # unchanged
│
└── frontend/
    ├── package.json                   # adds svelte + @sveltejs/vite-plugin-svelte
    ├── svelte.config.js
    ├── tsconfig.json, vite.config.ts
    ├── index.html
    └── src/
        ├── App.svelte                 # tab router, top-level layout
        ├── main.ts                    # mounts App.svelte
        │
        ├── lib/                       # Svelte convention ($lib alias)
        │   ├── api/                   # typed fetch wrappers (from Stage 1 shared/api.ts)
        │   ├── stores/                # one per concern, not one per tab
        │   │   ├── segments/
        │   │   │   ├── chapter.ts     # currently-loaded chapter data
        │   │   │   ├── filters.ts
        │   │   │   ├── edit.ts        # active mode + trim/split buffers
        │   │   │   ├── save.ts
        │   │   │   ├── history.ts
        │   │   │   └── validation.ts
        │   │   ├── timestamps.ts
        │   │   └── audio.ts
        │   ├── types/                 # carried over from Stage 1 types/
        │   ├── utils/                 # pure logic (ref parsing, arabic-text, peaks math)
        │   └── components/            # shared UI
        │       ├── AudioPlayer.svelte
        │       ├── SearchableSelect.svelte
        │       ├── Waveform.svelte
        │       ├── AccordionPanel.svelte
        │       └── ValidationBadge.svelte
        │
        ├── tabs/
        │   ├── segments/
        │   │   ├── SegmentsTab.svelte
        │   │   ├── SegmentRow.svelte
        │   │   ├── EditToolbar.svelte
        │   │   ├── {Trim,Split,Merge,Delete,Reference}Panel.svelte
        │   │   ├── HistoryPanel.svelte + HistoryBatch.svelte
        │   │   ├── FiltersBar.svelte
        │   │   ├── StatsPanel.svelte
        │   │   ├── ValidationPanel.svelte + ErrorCard.svelte
        │   │   └── WaveformOverlay.svelte
        │   ├── timestamps/
        │   │   ├── TimestampsTab.svelte
        │   │   ├── UnifiedDisplay.svelte
        │   │   ├── WaveformCanvas.svelte
        │   │   └── ValidationPanel.svelte
        │   └── audio/
        │       └── AudioTab.svelte
        │
        └── styles/
            └── base.css               # global only: resets, fonts, :root vars
```

### Exit criteria

Stage 2 is done when:

- Every `.ts` module that had UI concerns has been converted to a `.svelte` component.
- Pure-logic modules remain `.ts`.
- Per-tab `state.ts` files are replaced by the split-by-concern stores.
- The registration pattern (`register*` functions) is deleted.
- Every `.svelte` component that handles non-trivial interaction has a Vitest + testing-library test.
- Playwright covers at least: load chapter → trim → save → undo → reload → verify.
- Bundle size is within ±25% of Stage 1's 436 kB.
- All 4 OPEN Stage-1 bugs are either CLOSED or have a Stage-2 bug-log successor.
- A Stage-2 bug log exists and has closed rows (= the refactor actually caught things).

---

## Testing matrix

| What | Pre-refactor | After Stage 1 ✅ | After Stage 2 (goal) |
|------|---|---|---|
| Python services | pytest | same | same |
| API routes | Flask test client | same | same |
| Frontend pure logic | untestable (DOM-coupled) | Vitest (pure functions extracted) | same |
| UI components | untestable | still untestable (imperative DOM) | `@testing-library/svelte` |
| User interactions | manual only | manual only | component-level simulation + Playwright E2E |
| State–DOM sync bugs | manual only | typed, but still manually invoked | eliminated by construction (reactivity) |
| Type errors | runtime crashes | caught at compile time (max strict) | same |
| API-contract drift | invisible until runtime | bug-log tracked (caught 9 rows in Stage 1) | add Pydantic on Flask → caught at server-response time |

---

## Open choices for the reader

These don't block starting Stage 2 but should be named decisions before the first `.svelte` commit lands:

- Svelte 5 or Svelte 4? (recommendation: 5)
- Fix B02 first, or include in Stage 2? (recommendation: fix first — it's a real data bug, not a reactivity pattern)
- Commit `frontend/dist/` to git for Python-only contributors, or make `npm run build` a hard prereq? (current state: gitignored + hard prereq; same policy probably carries forward)
- Start Pydantic on the Flask side now, later, or never? (recommendation: now — cheap, orthogonal, prevents a whole drift class)
- Accept one commit per component, or bundle related components per commit? (recommendation: bundle by sub-tab for readability, keep diffs reviewable)
