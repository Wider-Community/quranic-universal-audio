# Wave 11a — Implementation Handoff

**Date**: 2026-04-15
**Branch**: `worktree-refactor+inspector-modularize` (WSL worktree)
**Working directory**: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/`
**Wave HEAD**: `49c49b6` (docs: record S2-B06 fix SHA)
**Agent model**: claude-sonnet-4-6

---

## 1. Wave scope and completion status

Wave 11a covered 4 priorities. All 4 are COMPLETE.

| Priority | Scope | Status | Key commits |
|----------|-------|--------|-------------|
| P1 | Save-preview HistoryPanel reuse — resolve Opus F bifurcation | COMPLETE | (from previous session) |
| P2 | State.ts sweep — delete fields with zero live readers | COMPLETE | `d46cf1a` |
| P3 | Orphan file deletion + cleanup | COMPLETE | (from previous session) |
| P4 | Cycle ceiling 12 → 0 + re-promote `import/no-cycle` to `error` | COMPLETE | `71a1dc7` |

---

## 2. P2 — State.ts sweep

### Fields removed from `SegmentsState` interface + initializer

| Field | Was | Absorbed by |
|-------|-----|-------------|
| `segHistoryData` | `SegEditHistoryResponse \| null` | `historyData` writable in `lib/stores/segments/history.ts` |
| `_histFilterOpTypes` | `Set<string>` | `filterOpTypes` writable in history store |
| `_histFilterErrCats` | `Set<string>` | `filterErrCats` writable in history store |
| `_histSortMode` | `'time' \| 'quran'` | `sortMode` writable in history store |
| `_allHistoryItems` | `OpFlatItem[] \| null` | `flatItems` derived in history store |
| `_splitChains` | `Map<string, SplitChain> \| null` | `splitChains` writable in history store |
| `_chainedOpIds` | `Set<string> \| null` | `chainedOpIds` writable in history store |

### Fields removed from `DomRefs` interface + `dom` initializer

All of these were Svelte-owned node references — never legitimately writeable by imperative code:
- `segHistoryBackBtn`, `segHistoryStats`, `segHistoryBatches` (HistoryPanel.svelte owns)
- `segHistoryFilters`, `segHistoryFilterOps`, `segHistoryFilterCats`, `segHistoryFilterClear` (HistoryFilters.svelte owns)
- `segHistorySortTime`, `segHistorySortQuran` (HistoryFilters.svelte owns)
- `segSavePreviewStats`, `segSavePreviewBatches` (SavePreview.svelte owns)

### Dead write sites removed

Across `save.ts`, `history/undo.ts`, `data.ts`, `SegmentsTab.svelte`:
- `state.segHistoryData = hist` → now call `renderEditHistoryPanel(hist)` directly (bridge → store)
- `state._splitChains = ...` / `state._chainedOpIds = ...` → removed (store-only writes via `setSplitChains`)
- `state._allHistoryItems = null` → removed
- `savePrevStats.innerHTML = ''` / `savePrevBatches.innerHTML = ''` in SegmentsTab.svelte → replaced with `clearSavePreviewData()` store call (B1-class clobber fix)

### `segHistoryData` reader migration

`undo.ts:220` was the last reader of `state.segHistoryData?.batches`. Replaced with `storeGet(historyData)?.batches`. Added `get as storeGet` and `historyData` imports from the history store.

---

## 3. P4 — Cycle dissolution

### Approach

All 4 underlying cycles went through `data.ts` as a hub. The pattern used throughout:
- In the "callee" module: add `let _fn = null; export function registerX(fn) { _fn = fn; }; function _x() { _fn?.() }`
- In `segments/index.ts` (the wiring hub): import both sides and call `registerX(realFn)`

### Cycles dissolved

**Cycle A: `data.ts` ↔ `history/index.ts`**
- `data.ts` used to import `renderEditHistoryPanel` from `history/index.ts`
- `history/index.ts` imports `onSegReciterChange` from `data.ts` (used in `hideHistoryView`)
- Fix: Inline `renderEditHistoryPanel` logic as private `_applyHistoryData()` in `data.ts`. Register `onSegReciterChange` via `registerOnSegReciterChange` in `history/index.ts`.

**Cycle B: `data.ts` ↔ `playback/index.ts`**
- `data.ts` imported `stopSegAnimation` from `playback/index.ts`
- `playback/index.ts` imports `getSegByChapterIndex` from `data.ts`
- Fix: Register `stopSegAnimation` in `data.ts` via `registerStopSegAnimation`.

**Cycle C: `data.ts` ↔ `waveform/index.ts`**
- `data.ts` imported `_fetchChapterPeaksIfNeeded` from `waveform/index.ts`
- `waveform/index.ts` imported `getAdjacentSegments, getSegByChapterIndex` from `data.ts`
- Fix: Register `_fetchChapterPeaksIfNeeded` in `data.ts` via `registerFetchChapterPeaks`. Register data lookups in `waveform/index.ts` via `registerDataLookups(getAdjFn, getSegFn)`.

**Cycle D: `waveform/index.ts` ↔ `rendering.ts`** (via data.ts)
- `waveform/index.ts` imported `_getEditCanvas` from `rendering.ts`
- `rendering.ts` imports from `data.ts`, which imported from `waveform/index.ts`
- Fix: Register `_getEditCanvas` in `waveform/index.ts` via `registerGetEditCanvas`.

### New exports from `segments/index.ts` wiring

```ts
// data.ts
import { onSegReciterChange, getAdjacentSegments, getSegByChapterIndex,
         registerFetchChapterPeaks, registerStopSegAnimation } from './data';
// history/index.ts
import { registerOnSegReciterChange } from './history/index';
// playback/index.ts
import { stopSegAnimation } from './playback/index';
// rendering.ts
import { _getEditCanvas } from './rendering';
// waveform/index.ts
import { _fetchChapterPeaksIfNeeded, registerDataLookups,
         registerGetEditCanvas } from './waveform/index';

// Registrations
registerStopSegAnimation(stopSegAnimation);
registerOnSegReciterChange(onSegReciterChange);
registerGetEditCanvas(_getEditCanvas);
registerFetchChapterPeaks(_fetchChapterPeaksIfNeeded);
registerDataLookups(getAdjacentSegments, getSegByChapterIndex);
```

### Gate update

- `eslint.config.js`: `'import/no-cycle': 'warn'` → `'import/no-cycle': 'error'`
- `.refactor/stage2-checks.sh`: `CYCLE_CEILING=12` → `CYCLE_CEILING=0`
- `stage2-bugs.md`: S2-B06 moved to Section 5 with SHA `71a1dc7`

---

## 4. Known issue — undo.ts `setHistoryData(storeGet(historyData))`

`onPendingBatchDiscard` (undo.ts:228) calls `setHistoryData(storeGet(historyData))` — reading the store and writing it back to itself. This is functional (setHistoryData rebuilds split chains in-store from the raw batches), but it's an odd no-op if no batch was added externally. The original code was `setHistoryData(state.segHistoryData)` when those were in sync. The intent is to force HistoryPanel to re-derive its display list after `setSplitChains` augments chains. Tracked as a known concern for Wave 12+ cleanup.

---

## 5. Files changed in this wave (P2 + P4)

### P2 commit (`d46cf1a`)
- `inspector/frontend/src/segments/state.ts` — removed 7 interface fields, 7 initializer entries, 11 DomRefs fields + dom entries; removed `SegEditHistoryResponse` import
- `inspector/frontend/src/segments/save.ts` — removed dual `state._splitChains/_chainedOpIds` writes; simplified `state.segHistoryData = hist; render(state.segHistoryData)` → `render(hist)`
- `inspector/frontend/src/segments/history/undo.ts` — same pattern; added `storeGet(historyData)` for the one remaining read; removed `state.segHistoryData = hist`
- `inspector/frontend/src/segments/data.ts` — removed dead null-writes; removed B1-clobber via `clearSavePreviewData()`
- `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` — removed dead writes; fixed B1-class innerHTML clobbers → `clearSavePreviewData()`

### P4 commit (`71a1dc7`)
- `inspector/frontend/src/segments/data.ts` — removed waveform+history+playback imports; added 3 registrations + `_applyHistoryData` inline
- `inspector/frontend/src/segments/history/index.ts` — removed `data.ts` import; added `registerOnSegReciterChange`
- `inspector/frontend/src/segments/waveform/index.ts` — removed `data.ts` + `rendering.ts` imports; added `registerDataLookups` + `registerGetEditCanvas`
- `inspector/frontend/src/segments/index.ts` — added 5 registration calls + 7 new imports
- `inspector/frontend/eslint.config.js` — `'import/no-cycle': 'error'`
- `.refactor/stage2-checks.sh` — `CYCLE_CEILING=0`
- `.refactor/stage2-bugs.md` — S2-B06 closed

---

## 6. Pre-flight gate status at wave exit

```
[1/7] Backend: config.py magic-number check   ok
[2/7] Backend: no Flask imports in services/  ok
[3/7] Frontend: tsc --noEmit                  ok
[4/7] Backend: no 'global' outside cache.py   ok
[5/7] Backend: orphan global cache vars       ok
[6/7] Frontend: zero cycle NOTE comments      ok
[7/7] Frontend: import/no-cycle count ≤ 0     ok: 0 cycle warnings (ceiling: 0)
svelte-check: 0 errors, 0 warnings
```

---

## 7. What comes next (Wave 12+)

Wave 11a was the final planned wave for this stage. The orchestrator should:

1. **Smoke test** — load the app in the browser, switch reciters, open history view, trigger save-preview (with split chain history), undo a batch, verify history panel updates correctly.

2. **Consider**: `segments/data.ts` and `segments/rendering.ts` are the largest remaining non-Svelte files in the segments tab. They're not orphans (live importers exist in Svelte components), but they could be the next migration target if a Wave 12 is chartered.

3. **Known concern**: `setHistoryData(storeGet(historyData))` in `undo.ts:228` — see Section 4 above.

4. **S2-D34 softening**: `segments/{data,filters,navigation,rendering}.ts` were candidates for P3 orphan deletion but all had live Svelte-component importers. These are kept and documented.

5. **Stage 2 overall**: All waves 0.5–11a are complete. Backend (Waves 2a–2b), Svelte foundation (Wave 3), Timestamps tab (Wave 4), Segments tab migrations (Waves 5–11a) are done. Wave 11b (audio tab + CSS port) and 11c (retro + CLAUDE.md + docs) remain.

---

## 8. Review findings + disposition

### Sonnet (pattern review) — **APPROVE**

No blockers. 3 minor non-blockers (all Wave 11b/11c/12):

| ID | Item | Disposition |
|---|---|---|
| NB-1 | `_applyHistoryData` in `data.ts:53-61` is a private inline of `history/index.ts:79-87::renderEditHistoryPanel`. The private copy exists to break the cycle (correct), but creates a subtle divergence risk if the canonical version evolves. | Wave 12 cleanup |
| NB-2 | `undo.ts:227` self-round-trip `setHistoryData(storeGet(historyData))` — functional but semantically odd. Tracked in handoff §4. | Wave 11b/c awareness |
| NB-3 | `waveform/index.ts:17` dead `void _findCoveringPeaks` line (pre-existing marker, not Wave 11a). | Wave 11b/c absorption |

**Validated:** §6.3 conformity, P1 Opus F bifurcation resolution (zero raw `state._splitChains` reads in `save.ts`; `SavePreview` subscribes via `$savePreviewData` + `$splitChains`; `rAF(drawHistoryArrows)` gone), P2 sweep completeness (7 fields + 11 DomRefs removed; zero live grep hits; 2 B1-class clobbers fixed), P3 orphan deletion (history/{filters,rendering}.ts deleted; `_addEditOverlay`/`_removeEditOverlay` stubs gone; `drawBarChart`/`findBinIndex` extracted to `lib/utils/stats-chart-draw.ts`; `_rebuildAccordionAfterMerge` correctly preserved — has live caller in `edit/merge.ts:142`), P4 cycle dissolution (4 cycle types via 5 register* wirings at `segments/index.ts:63-70`; eslint.config.js promoted to `error`; CYCLE_CEILING=0; S2-B06 in Section 5 with SHA `71a1dc7`), no regressions to S2-B01/B02/B04/B05/B07, pattern notes #1-#8 upheld, runtime flow trace clean.

### Haiku (mechanical review) — **VERIFIED with one structural discrepancy**

All counts confirmed: 7 SegmentsState fields removed; 11 DomRefs removed; 4 cycle types via 5 register* wirings; ceiling 12 → 0; eslint promoted; npm run lint 0/0; vite build 145 modules; 0 tsc errors; net LOC -772.

**STRUCTURAL DISCREPANCY (fixed by orchestrator)**: S2-B06 was added to Section 5 (Closed) but the original Section 2 row was left at `DEFERRED` status with empty Fix-SHA. Orchestrator updated Section 2 row: status `DEFERRED → CLOSED`, populated Fix-SHA `71a1dc7`, added "see Section 5" pointer + cycle-count progression history (23 → 19 → 16 → 14 → 12 → 0).

### Orchestrator disposition

- Both reviewers APPROVE. No blockers.
- Haiku discrepancy fixed inline (1 edit to `bugs.md` Section 2 row).
- 3 Sonnet NBs deferred to Wave 11b/c or Wave 12.
- **Wave 11a CLOSED.** Proceed to Wave 11b (audio tab + CSS port).
