# Stage 2 — Retrospective

**Date**: 2026-04-14
**Branch**: `worktree-refactor+inspector-modularize`
**Final HEAD (Waves 0.5–11b)**: `8079a16`
**Total waves**: 0.5, 1, 2a, 2-mid, 2b, 3, 3-followup, 4, stop-point-1-hotfix, 5, 6a, 6b, 7a, 7b, 8a, 8a.2, 8b, 8b-review, 9, 10, 11a, 11b (22 agents/sub-waves)

---

## 1. What was done

Stage 2 migrated the Inspector frontend from vanilla TypeScript imperative DOM (Stage 1 result) to Svelte 4 reactive components, and added orthogonal backend polish for Docker distribution.

### Backend (Waves 1–2b)

- S2-B02 fixed: timestamps tab registry cleanup and keyboard-guard helper extracted.
- `config.py` gained `INSPECTOR_DATA_DIR` with all path constants centralised.
- `validators/` vendored from sibling directory into `inspector/validators/` (3 validators, clean package).
- Docker distribution: `Dockerfile` + `docker-compose.yml` + `.dockerignore` added under `inspector/`.
- `app.py`: structured logging, 3 thin routes extracted, `save_seg_data` decomposed into 4 phase helpers.
- Magic-number sweep: all timeouts/thresholds named in `config.py`.
- Wave 3 review follow-up: `requirements-dev.txt` placeholder added.

### Frontend — shared infrastructure (Wave 3)

- Svelte 4 installed. `App.svelte` created as tab shell (hidden-div pattern, no re-mount on switch).
- `shared/` modules migrated and extended to `lib/api/`, `lib/utils/`, `lib/components/`, `lib/types/`, `lib/stores/`.
- 8 shared primitives created: `AccordionPanel`, `AudioElement`, `Button`, `SearchableSelect`, `SpeedControl`, `ValidationBadge`, `WaveformCanvas`, `keyboard-guard.ts`.
- CSS migration map (`stage2-css-migration-map.md`) authored.
- `shared/active-tab.ts` extracted to `lib/utils/active-tab.ts` (breaks main.ts ↔ keyboard circular dep, S2-D25).
- `import/no-cycle` ESLint rule enabled with TS resolver; cycle ceiling gate added to `stage2-checks.sh` (S2-D26).

### Frontend — Timestamps tab (Wave 4)

- `timestamps/index.ts` (569 LOC) + 8 sibling `.ts` files (2,012 LOC total) deleted.
- 5 Svelte components: `TimestampsTab.svelte`, `UnifiedDisplay.svelte`, `AnimationDisplay.svelte`, `TimestampsWaveform.svelte`, `TimestampsValidationPanel.svelte`.
- 3 stores: `lib/stores/timestamps/{verse,display,playback}.ts`.
- `createAnimationLoop()` (`lib/utils/animation.ts`) replaces inline rAF chain.
- `webaudio-peaks.ts` extracted with LRU cache and sub-range slice logic.
- `WaveformCanvas` gained `startMs/endMs/totalDurationMs` sub-ranging props (S2-D32).

### Frontend — Segments tab (Waves 5–10)

This was the most complex portion due to the segments tab being a full editor.

- **Wave 5**: `SegmentsTab.svelte` shell + `FiltersBar.svelte` + `SegmentsList.svelte` + `SegmentRow.svelte` + `Navigation.svelte`. 9 stores created under `lib/stores/segments/`.
- **Wave 6a**: `segAllData`/`segData` store desync fix; chapter loading moved to stores.
- **Wave 6b**: Filter stores + `waveform-cache.ts` URL normalization fix (S2-B04 CLOSED).
- **Wave 7a**: Edit mode components — `EditOverlay`, `TrimPanel`, `SplitPanel`, `MergePanel`, `DeletePanel`, `ReferenceEditor.svelte`. Registration pattern partially preserved for imperative↔Svelte bridge.
- **Wave 7b**: History panel (`HistoryPanel`, `HistoryBatch`, `HistoryOp`, `HistoryArrows`, `HistoryFilters`, `SplitChainRow`) — the most complex Svelte migration.
- **Wave 8a**: `ValidationPanel.svelte` + `ErrorCard.svelte` (11-category accordion with `{#each}` per S2-D33).
- **Wave 8b**: `StatsPanel.svelte` + `StatsChart.svelte` + `ChartFullscreen.svelte` + `lib/utils/stats-chart-draw.ts`.
- **Wave 9**: S2-B05 fix (undo regression) + `clearSegDisplay` store desync + `SavePreview.svelte` + `lib/stores/segments/save.ts`. `state.segStatsData` field deleted.
- **Wave 10**: History panel full Svelte migration; `segments/history/rendering.ts` (695 LOC) substantially replaced. SVG arrow geometry (`svg-arrow-geometry.ts`) + `computeArrowLayout()` pure helper.

### Frontend — Audio tab (Wave 11b)

- `audio/index.ts` (341 LOC imperative) deleted.
- `tabs/audio/AudioTab.svelte` (310 LOC) created — all component-local state, no store.
- `styles/audio-tab.css` deleted; rule ported to scoped `<style>` in component.
- Dead `void _findCoveringPeaks` expression removed from `waveform/index.ts` (NB-3).

### Cycles and pre-flight (Wave 11a)

- Cycle ceiling decremented progressively from 22 → 0 as segments modules migrated.
- `import/no-cycle` severity promoted from `warn` → `error` (S2-D24 resolution).
- All 7 pre-flight gates green: tsc, ESLint (0 errors/warnings), Vite build, no-global, no-orphan-cache, no-cycle-comments, cycle count ≤ 0.
- `svelte-check`: 0 errors, 0 warnings.
- Build: 144 modules, 535 kB JS, 31.5 kB CSS.

---

## 2. What worked well

### Pre-flight gate script (`stage2-checks.sh`)
The 7-gate script run at every wave boundary caught regressions before they compounded. The cycle ceiling gate (Gate 7) in particular prevented any agent from silently introducing new cycles during the deferral window.

### Handoff documents per wave
Each wave produced a structured handoff (11 sections). The format preserved enough context for fresh sessions to orient in < 5 minutes. The pattern was load-bearing across 22 agents in a long multi-day refactor.

### Advisor calls before writing
Calling `advisor()` before substantive implementation work consistently improved approach selection and caught structural issues before they were coded in. Particularly valuable on Wave 4 (first Svelte tab, pattern setting) and Wave 7b (history view with SVG arrows).

### Registration pattern for circular dependencies
Retaining the registration pattern (`registerHandler`, `registerWaveformHandlers`, etc.) as a bridge between imperative segments modules and Svelte components allowed waves to proceed in series without needing to convert everything at once. The bridge will dissolve naturally as remaining imperative segments code is migrated.

### Incremental CSS deferral (S2-D34 softening)
Explicitly deferring CSS migration for files with imperative `classList` callers (pattern note #8) prevented analysis paralysis. Only `audio-tab.css` (one consumer, 6 lines) was safely portable; the other 7 files are tracked for Wave 12.

### Stop-points respected
Both user-declared stop-points (before Wave 4 and before Wave 10) were honoured. This prevented the orchestrator from racing ahead of user validation on the two highest-risk waves.

---

## 3. What was harder than expected

### S2-B07: Module-top-level DOM access
`audio/index.ts` was calling `mustGet()` at module-top-level, not inside `DOMContentLoaded`. The bug existed before Stage 2 started, was missed by Wave-3 and Wave-4 reviewers, and surfaced only when `audio/index.ts` was imported as a side-effect in `main.ts` (before Svelte's App mounted). Required a hotfix wave (stop-point-1-hotfix) between Waves 4 and 5 and retroactive updates to the reviewer prompt checklist.

**Lesson**: When auditing a tab for Svelte conversion, grep `"^[a-zA-Z].*mustGet\|addEventListener"` at module top-level before assuming the imperative code is safe.

### History view complexity underestimated
Wave 0.5 revealed that `history/rendering.ts` (695 LOC) contained 5 distinct arrow mapping patterns (1:1, 1:N, N:1, N:N, deletion-with-X) that the initial plan had simplified to "1:1 geometry helper". The `computeArrowLayout()` helper and full `HistoryBatch`/`HistoryOp`/`SplitChainRow` component tree required significantly more design work than planned.

### Store desync bugs (S2-B04, S2-B05)
Two store-desync bugs emerged during the middle waves:
- S2-B04: `waveform-cache.ts` used raw CDN URLs as keys; `data.ts` normalized them to proxy URLs. Reads always missed.
- S2-B05: `segAllData` store was cleared on reciter change before the undo module had finished reading from it.

Both were caught by pre-flight + manual reasoning (no automated tests). Each required a dedicated diagnosis + fix sub-wave.

**Lesson**: Store-reactive code is easier to reason about than imperative code, but the desync class of bugs migrates with you into stores if the key/identity conventions are inconsistent.

### `import/no-cycle` rule was silently no-op
The rule existed in `eslint.config.js` from Stage 1 but `eslint-plugin-import` had no TypeScript resolver configured, so it never fired. This was only discovered in Wave 1 when the TS resolver was installed. The fix was correct (downgrade to `warn`, apply ceiling gate, re-promote at Wave 11), but it meant the refactor started without knowing the true cycle count (22 at Wave 1, not 0).

---

## 4. What was deferred (Wave 12 and beyond)

### CSS migration (7 remaining files)
All CSS files except `audio-tab.css` remain global in `styles/`. The blocker is pattern note #8: imperative `classList.add/remove` for 60fps updates (e.g., `.anim-word.active` in AnimationDisplay) requires `:global()` in scoped styles, and many class names are simultaneously used as DOM query selectors in imperative `.ts` files (e.g., `.val-card-wrapper`, `.seg-filter-bar`). Full migration requires first refactoring those imperative modules to use data attributes or `bind:this` refs instead of class-selector queries.

### NB-1: `_applyHistoryData` / `renderEditHistoryPanel` duplication
`segments/data.ts:53-61` contains a private inline duplicate of `renderEditHistoryPanel`. Collapsing requires careful cycle-break structure evaluation. Deferred to Wave 12.

### NB-2: `undo.ts:228` self-round-trip
`setHistoryData(storeGet(historyData))` is a semantically odd self-round-trip. Functional, not blocking. Deferred to Wave 12.

### S2-D28: `_apply_full_replace` return annotation
Missing `-> None | tuple[dict, int]` return annotation on the Wave 2b phase helper. Cosmetic typing nit deferred to Wave 12.

### S2-D29: `get_verse_data._error` discriminant convention
Service-return dict uses `_error` string key to signal HTTP 404 semantics (leaky abstraction). Deferred per both Opus and Sonnet reviewers' concurrence — revisit only if cleaner pattern emerges during further Svelte work.

### Shared `searchable-select.ts` and `dom.ts`
Still consumed by `segments/index.ts` and `segments/state.ts`. Cannot delete until segments tab imperative code is fully Svelte-ified.

---

## 5. Pattern notes that proved most load-bearing

These 8 patterns (authored in Wave 4 handoff) were applied correctly across all subsequent waves:

1. **Plain `writable<T>()` / `derived`** — no factory wrappers. Kept store shapes readable.
2. **Shallow derivation** — `$:` for single-component computed values, derived() for cross-component.
3. **Stores for tab-scoped state; props parent→child; events child→parent** — prevented store proliferation.
4. **No DOM caches in state** — `bind:this` + `querySelectorAll` in imperative update functions prevented stale-ref bugs.
5. **Module-scope `Map` for WebAudio-style caches** — non-reactive Map avoids Svelte re-render overhead on large peak arrays.
6. **CSS vars as `style:` directives on tab root** — not via `:root` JS injection.
7. **Keyboard via `<svelte:window on:keydown>` + `shouldHandleKey(e, tab)`** — centralised guard, no duplication.
8. **Hybrid 60fps**: Svelte for structure + imperative `updateHighlights()` via `bind:this` for per-frame class toggles — the most important pattern; avoids Svelte's 16ms frame budget for animation-critical code.

---

## 6. Pre-flight gate final state

```
[1/7] npm run typecheck (tsc --noEmit)        ok
[2/7] npm run lint (ESLint)                   ok: 0 errors, 0 warnings
[3/7] npm run build (Vite production build)   ok: 144 modules
[4/7] Backend: no 'global' outside cache.py   ok
[5/7] Backend: _URL_AUDIO_META and _phonemizer in cache.py only   ok
[6/7] Frontend: zero '// NOTE: circular dependency' comments      ok
[7/7] Frontend: import/no-cycle count ≤ 0     ok: 0 cycle warnings (ceiling: 0)
svelte-check: 0 errors, 0 warnings
```

Build: 144 modules, 535 kB JS, 31.5 kB CSS.

---

## 7. Decisions that should be revisited before future waves

| Decision | Current state | Suggested revisit |
|----------|---------------|-------------------|
| S2-D10: State-object-pattern deprecated for frontend | Deprecated globally; still active in `segments/` imperative code | When segments imperative code is fully Svelte-ified (Wave 12+), delete `segments/state.ts` state/dom pattern |
| S2-D11: Store granularity provisional | Stores locked per wave, not globally | Wave 12 can collapse any stores that never had multiple consumers |
| S2-D29: `_error` discriminant in services | Keep as-is | Revisit if a REST error-handling refactor lands |
| S2-D34 CSS softening | 7 CSS files still global | Wave 12: start with `timestamps.css` (`:global(.anim-word)` wrappers in AnimationDisplay) and `history.css` (already used inside Svelte history components) |

---

## 8. LOC delta summary

| Category | Before Stage 2 | After Stage 2 | Delta |
|----------|---------------|--------------|-------|
| Frontend TS imperative | ~12,265 LOC | ~3,500 LOC (segments only) | −8,765 |
| Frontend Svelte components | 0 | ~5,800 LOC | +5,800 |
| Frontend stores | 0 | ~600 LOC | +600 |
| Frontend lib/utils | ~800 LOC | ~1,400 LOC | +600 |
| Backend services | ~2,200 LOC | ~2,400 LOC | +200 |
| Build output | 480 kB JS / 31 kB CSS | 535 kB JS / 31.5 kB CSS | ~+11% JS (Svelte runtime) |

Note: LOC figures are approximate (from wave handoffs); no automated counting was performed.

---

**END Stage 2 Retrospective.**
