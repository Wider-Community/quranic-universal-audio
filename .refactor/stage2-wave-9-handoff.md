# Stage 2 — Wave 9 Handoff (save preview + undo + S2-B05 + carry-forwards)

**Status**: COMPLETE — Wave 9 scope fully delivered.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `2acf8ac` (Wave 8b review follow-ups)
**Known-good exit commit**: `29a80e6` (drop state.segStatsData + bridge)
**Agent**: Claude Sonnet 4.6 (implementation-Wave-9), 2026-04-14.

---

## 0. At-a-glance

- 6 source commits + this handoff = 7 commits.
- 2 new files (lib/stores/segments/save.ts, tabs/segments/save/SavePreview.svelte), 4 modified (segments/history/undo.ts, segments/data.ts, segments/save.ts, tabs/segments/SegmentsTab.svelte), 1 docstring-only update (lib/stores/segments/stats.ts).
- 7/7 pre-flight gates GREEN. Lint 0 errors / **14 warnings** (cycle count unchanged at 14; ceiling stays 16).
- Bundle: 135 modules (unchanged), ~520 kB.
- All Wave 9 scope delivered: S2-B05 closed, store-desync fixed, save store + SavePreview.svelte created, showPreview/hidePreview wired, state.segStatsData deleted.

---

## 1. Scope delivered

### 1.1 S2-B05 fix — split chain UID lost on undo (commit `02e116f`)

**Root cause**: `state._splitChainUid` / `_splitChainWrapper` / `_splitChainCategory` are set in
`split.ts:369` after a split operation to enable chained ref editing. They were never cleared on
undo or discard, so a pending `_chainSplitRefEdit` 100ms setTimeout could fire on a segment that
no longer exists.

**Fix**: null all three fields in three cleanup paths:

1. `segments/history/undo.ts::_afterUndoSuccess` — top of function, before async history fetch.
2. `segments/history/undo.ts::onPendingBatchDiscard` — before dirty-map deletion.
3. `segments/data.ts::clearSegDisplay` — alongside existing `_splitChains = null` block.

`reference.ts::_chainSplitRefEdit` already nulls all three before using them (line 81-85), so the
read side was safe. The fix closes the window where a delayed timeout could look up a stale UID.

**S2-B05 status**: CLOSED.

---

### 1.2 clearSegDisplay store-desync fix (commit `3d48174`)

**Root cause**: `data.ts::clearSegDisplay` and `data.ts::onSegReciterChange` wrote `state.segAllData`
directly without calling `segAllData.set()`. The SegmentsTab bridge (`$: state.segAllData = $segAllData`)
is store→state (one-way), so direct writes to `state.*` never notified Svelte subscribers.

**Fix**: import `segAllData`, `segData` from `lib/stores/segments/chapter` in `data.ts` and add
`.set()` calls alongside the direct writes at two sites:

- `clearSegDisplay`: `segAllData.set(null)` after `state.segAllData = null`; `segData.set(null)` after `state.segData = null`.
- `onSegReciterChange` (line ~164): `segAllData.set(allResult.value)` after `state.segAllData = allResult.value`.

No bridge change needed in SegmentsTab — the store→state direction already handles store updates.

---

### 1.3 `lib/stores/segments/save.ts` — save preview visibility store (commit `a919fe1`)

Path: `inspector/frontend/src/lib/stores/segments/save.ts`

Thin writable<boolean> store (~31 LOC):

```ts
export const savePreviewVisible = writable<boolean>(false);
export function showPreview(): void { savePreviewVisible.set(true); }
export function hidePreview(): void { savePreviewVisible.set(false); }
```

Follows the same pattern as `validation.ts` and `stats.ts`. Shell-delegation: store owns visibility;
imperative code continues to render content into the divs (Wave 10 territory).

---

### 1.4 `tabs/segments/save/SavePreview.svelte` — shell component (commit `50ff4c2`)

Path: `inspector/frontend/src/tabs/segments/save/SavePreview.svelte`

Extracts `<div id="seg-save-preview">` from SegmentsTab.svelte's inline HTML. All IDs preserved so
`mustGet()` in `segments/state.ts` continues to resolve `DomRefs.segSavePreview`,
`segSavePreviewCancel`, `segSavePreviewConfirm`, `segSavePreviewStats`, `segSavePreviewBatches`.

Visibility binding: `hidden={!$savePreviewVisible}` — store-driven. Inner content is still rendered
imperatively by `segments/history/rendering.ts` into `#seg-save-preview-stats` and
`#seg-save-preview-batches`.

SegmentsTab.svelte: `<div id="seg-save-preview">` block replaced with `<SavePreview />` (+ import).

---

### 1.5 Wire showPreview/hidePreview into save + data (commit `2505321`)

- `segments/save.ts`: import `showPreview`, `hidePreview` from `lib/stores/segments/save`.
  - `showSavePreview`: `showPreview()` called after `dom.segSavePreview.hidden = false`.
  - `hideSavePreview`: `hidePreview()` called after `dom.segSavePreview.hidden = true`.
- `segments/data.ts`: import `hidePreview`; call `hidePreview()` alongside
  `dom.segSavePreview.hidden = true` in `clearSegDisplay`.

The `dom.segSavePreview.hidden` direct writes are retained so imperative guard checks
(`if (!dom.segSavePreview.hidden) return;`) continue to work. Both are set consistently —
no race condition.

**SaveConfirm.svelte**: NOT created. Confirm/cancel buttons are 3 lines inline in SavePreview.svelte;
extraction not worth the indirection (advisor recommendation).

---

### 1.6 Drop state.segStatsData field + bridge — Wave 8b CF (commit `29a80e6`)

**Confirmed zero imperative reads** of `state.segStatsData` outside the bridge and SegmentsTab
(grep: 2 hits — interface definition and initializer only; no call sites).

Changes:
- `segments/state.ts`: removed `segStatsData: SegStatsResponse | null` from `SegmentsState` interface; removed `segStatsData: null` from initializer; removed unused `SegStatsResponse` import.
- `tabs/segments/SegmentsTab.svelte`: replaced `$: state.segStatsData = $segStats;` with comment.
- `lib/stores/segments/stats.ts`: updated docstring to note bridge removed.

---

## 2. Scope deferred

### 2.1 History view panels (Wave 10)

`renderHistoryBatches`, `renderHistorySummaryStats`, `drawHistoryArrows`, `renderEditHistoryPanel`
are all imperative — untouched. Wave 10 owns the full history panel migration to Svelte.

### 2.2 Save preview content rendering (Wave 10)

`dom.segSavePreviewStats` and `dom.segSavePreviewBatches` are still rendered imperatively.
The store owns visibility only (shell-delegation); Wave 10 will promote content.

### 2.3 Undo flow (Wave 10)

`onBatchUndoClick`, `onOpUndoClick`, `onChainUndoClick`, `onPendingBatchDiscard` remain imperative.
Wave 9 adds S2-B05 fix; no store migration of undo panels.

### 2.4 NB-3 carry-forward (stats error-clear on refresh)

Wave 8b NB-3: "Wave 9 refreshStats() should explicitly clear on error or set sentinel." The
current save flow (`executeSave`) calls `refreshValidation()` but does NOT call `refreshStats()`.
Stage-1 also didn't refresh stats on save. If `refreshStats()` is added in Wave 10/11, it
should call `clearStats()` on error response before `setStats()` on success.

### 2.5 `drawBarChart` duplication — Wave 11

StatsChart + ChartFullscreen still have ~120 LOC duplicated. Wave 11 extraction.

### 2.6 ReferenceEditor autocomplete — Wave 11

### 2.7 All Wave 7b / 8a.2 / 8b deferred items — unchanged

---

## 3. Key decisions / lessons

### 3.1 Shell-delegation for save preview

The save flow is complex (preview state, scroll restoration, stale-data flag, reciter reload path).
Wave 9 uses shell-delegation: the store owns only `savePreviewVisible: boolean`; imperative code
keeps rendering content. This avoids a large, risky rewrite of the save orchestration while still
giving Svelte the visibility signal it needs to drive `SavePreview.svelte`.

### 3.2 Direct DOM writes retained alongside store calls

`dom.segSavePreview.hidden = false/true` direct writes are kept alongside `showPreview()`/`hidePreview()`
calls. The imperative guard `if (!dom.segSavePreview.hidden) return;` in `showSavePreview()` still
works. Svelte's `hidden={!$savePreviewVisible}` binding will agree on the next tick. No B1-class risk
since the initial HTML attribute matches the store initial value (`false` → `hidden` present in
initial HTML rendered by Svelte).

### 3.3 S2-B05: null-out on cleanup, not restore from snapshot

The split chain fields (`_splitChainUid`, `_splitChainWrapper`, `_splitChainCategory`) are a
"fire-once" intent signal to `_chainSplitRefEdit`. They are not part of the undo snapshot.
The fix is to clear them in all cleanup paths (undo, discard, reciter-clear), not to include them
in the undo snapshot restore.

### 3.4 store-desync: direct state writes bypass bridges

The bridge in SegmentsTab (`$: state.segAllData = $segAllData`) is store→state, so writing
`state.segAllData = X` directly never notifies Svelte. Any direct `state.*` write must be paired
with a `store.set(X)` call in the same code path. This is a recurring pattern to watch for in
Wave 10-11 migrations.

### 3.5 segStatsData deletion timing

Wave 8b NB said "safe in Wave 9". Confirmed by grep: zero imperative reads outside the bridge.
The deletion is clean and the typecheck passes, closing the open question from §8 of the
Wave 8b handoff.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `29a80e6`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, **14 warnings** (cycle count unchanged) |
| [3/7] vite build | PASS | 135 modules, ~520 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 14/16 |

Pre-flight run 3 times across the 6 commits — all GREEN each time.

---

## 5. Manual QA smoke items

The following items should be tested manually after next deploy:

1. **Save preview shows**: Make dirty edits → click Save → Review Changes panel appears.
   Verify panel content (batches, stats summary) renders correctly.
2. **Save preview hides on Cancel**: Click ← Cancel → panel hides, segment list restores.
   Verify scroll position is restored.
3. **Save preview hides on Confirm Save**: Confirm → panel hides, save executes, reciter reloads.
4. **Reciter change mid-preview**: Trigger a reciter change while preview is open (via `_segDataStale`
   path in `hideSavePreview`) → verify panel hides cleanly and new reciter loads.
5. **S2-B05 regression**: Split a segment → immediately undo the split → verify no JS console
   error about "Cannot find segment with UID" or similar stale-ref error from `_chainSplitRefEdit`.
6. **Discard pending edits**: Open preview → discard pending chapter → verify preview updates or
   hides correctly; split chain fields are null.
7. **clearSegDisplay store sync**: Switch reciter → verify `$segAllData` becomes null in Svelte
   (segment list empties, filter bar hides). Then select a new reciter → verify `$segAllData`
   populates and segment list renders.
8. **StatsPanel after Wave 8b CF**: Verify StatsPanel still renders after reciter load (segStatsData
   deletion did not break the store flow).
9. **ValidationPanel after undo**: Make edit → save → undo → verify ValidationPanel re-populates
   correctly (B1 regression test from Wave 8a).

---

## 6. Commits (exit-point detail)

```
02e116f fix(inspector): S2-B05 — null splitChainUid/Wrapper/Category on undo and discard
3d48174 fix(inspector): clearSegDisplay store-desync — mirror segAllData/segData to stores
a919fe1 feat(inspector): lib/stores/segments/save.ts — save preview visibility store
50ff4c2 feat(inspector): SavePreview.svelte — extract save-preview panel from SegmentsTab
2505321 refactor(inspector): wire showPreview/hidePreview store calls into save + data
29a80e6 refactor(inspector): drop state.segStatsData field + bridge (Wave 8b CF)
```

6 source commits + this handoff = 7 commits.

---

## 7. Wave 10 prerequisites

Wave 10 owns: edit history view + full undo panel migration.

Prerequisites Wave 10 must respect:

1. **All prior prerequisites still apply** (store patterns, bridge-lag, {#each} keys, S2-B07 DOM-deferral).
2. **Cycle ceiling at 16** (14 actual). Wave 10 should target reduction as more Svelte migration dissolves cycles.
3. **S2-B05 CLOSED** — split chain UID triple is now properly nulled on all cleanup paths.
4. **Shell-delegation pattern for save preview** — Wave 10 should extend this: migrate content
   rendering (batches, stats) into the SavePreview component, using `$segHistoryData` or a derived store.
5. **direct state.* writes must pair with store.set()** — the store-desync pattern (§3.4) applies
   to all Wave 10 data writes. Check `onSegReciterChange` and other data-loading paths.
6. **NB-3 carry-forward** (§2.4): if Wave 10 adds `refreshStats()`, it should call `clearStats()`
   on error path.
7. **History panel imperative DOM**: `renderHistoryBatches`, `renderHistorySummaryStats`,
   `drawHistoryArrows`, `renderEditHistoryPanel` are all B1-risk if Svelte wraps the containers.
   Wave 10 must audit before mounting Svelte components over history divs.

---

## 8. Open questions for Wave 10

- [ ] Should `renderHistoryBatches` / `renderHistorySummaryStats` be replaced by Svelte components,
      or retained as imperative renderers called from within a Svelte component? The save preview
      approach (shell-delegation) suggests the latter is lower-risk.
- [ ] The undo panel `onBatchUndoClick` / `onOpUndoClick` / `onChainUndoClick` live in
      `segments/history/undo.ts` and are wired via `event-delegation.ts`. Wave 10 should decide
      whether to keep them imperative (event delegation) or migrate click handlers to Svelte.
- [ ] Should `savePreviewVisible` be expanded to include preview data (`batches`, `summary`) to
      allow fully declarative rendering in SavePreview? That would make SavePreview fully reactive
      and eliminate the `dom.segSavePreviewStats / Batches` mustGet refs.

---

## 9. Store inventory (post-Wave-9)

| Store | Path | Shape | Wave introduced |
|-------|------|-------|----------------|
| `segAllReciters` | lib/stores/segments/chapter.ts | `SegReciter[]` | Wave 5 |
| `selectedReciter` | lib/stores/segments/chapter.ts | `string` | Wave 5 |
| `selectedChapter` | lib/stores/segments/chapter.ts | `string` | Wave 5 |
| `selectedVerse` | lib/stores/segments/chapter.ts | `string` | Wave 5 |
| `segAllData` | lib/stores/segments/chapter.ts | `SegAllDataState \| null` | Wave 6a |
| `segData` | lib/stores/segments/chapter.ts | `SegDataState \| null` | Wave 6a |
| `activeFilters` | lib/stores/segments/filters.ts | `SegFilter[]` | Wave 6b |
| `displayedSegments` | lib/stores/segments/filters.ts | `Segment[]` (derived) | Wave 6b |
| `segIndexMap` | lib/stores/segments/filters.ts | `Map<string, Segment>` (derived) | Wave 6b |
| `savedFilterView` | lib/stores/segments/navigation.ts | `{...} \| null` | Wave 6b |
| `editMode` | lib/stores/segments/edit.ts | `SegEditMode` | Wave 7a |
| `segValidation` | lib/stores/segments/validation.ts | `SegValidateResponse \| null` | Wave 8a |
| `segStats` | lib/stores/segments/stats.ts | `SegStatsResponse \| null` | Wave 8b |
| `savePreviewVisible` | lib/stores/segments/save.ts | `boolean` | **Wave 9** |

---

## 10. File delta

New files:
- `inspector/frontend/src/lib/stores/segments/save.ts` (31 LOC)
- `inspector/frontend/src/tabs/segments/save/SavePreview.svelte` (28 LOC)

Modified:
- `inspector/frontend/src/segments/history/undo.ts` (S2-B05 null-outs in 2 functions)
- `inspector/frontend/src/segments/data.ts` (store import + set() calls + hidePreview)
- `inspector/frontend/src/segments/save.ts` (showPreview/hidePreview wiring)
- `inspector/frontend/src/segments/state.ts` (removed segStatsData field + SegStatsResponse import)
- `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` (SavePreview import + mount; bridge comment)
- `inspector/frontend/src/lib/stores/segments/stats.ts` (docstring update only)

---

## 11. Token / tool-call self-report

- Orientation reads: 8 files (Wave 8b handoff, undo.ts, data.ts, save.ts, state.ts, SegmentsTab.svelte, chapter.ts, stats.ts store).
- 1 advisor call (before Wave 9 start — approach confirmation, S2-B05 analysis, store shape).
- ~30 tool calls total (reads + edits + bash pre-flight runs).
- No dev server started. No new circular dependencies introduced.
- All 6 commits are atomic (one logical change each); pre-flight GREEN at every commit point.

---

## 12. Review findings + disposition

### Sonnet (pattern review) — **APPROVE-WITH-CHANGES**

**Non-blockers (NB-1 fixed inline; NB-2 carry-forward):**

| ID | Item | Disposition |
|---|---|---|
| NB-1 | `SegmentsTab.svelte::clearPerReciterState` (line 319) sets `(savePrev as HTMLElement).hidden = true` but does NOT call `hidePreview()`. Store stays at `true` while DOM hidden. If anything re-renders SavePreview.svelte (reactive update or hot-reload), Svelte restores `hidden={!$savePreviewVisible}` from stale `true` → panel re-appears. **Reviewer escalated to "required before Wave 10 start"**. | **Fixed** by orchestrator: imported `hidePreview` + called inside `clearPerReciterState`. Pattern matches Wave 9's `data.ts::clearSegDisplay` fix (commit `3d48174`). |
| NB-2 | `data.ts::onSegReciterChange` (line 165-166) mirrors `segAllData` but doesn't `segData.set(null)` at top — already handled by `clearSegDisplay` call at line 108. Not a bug; flag for Wave 10 audit of dual code-paths. | Carry-forward to Wave 10. |

**Validated:** §6.3 conformity (all 11 sections), S2-B05 fix correctness (3 sites; fire-once-signal reasoning sound; bugs.md row in Section 5 with literal SHA), clearSegDisplay store-desync (segAllData.set(null) + segData.set(null) + post-success notify), B1-class audit (no Svelte-root clobbers), save store shape (minimal `writable<boolean>` per S2-D11), state.segStatsData drop (zero live refs), Wave 8b NB-3 carry, segValidation auto-fix asymmetry N/A (save calls refreshValidation post-server), patterns #1-#8, D2 + S2-B07 greps clean, runtime flow trace clean post-NB-1-fix.

### Orchestrator disposition

- NB-1 fixed inline (2 source edits to SegmentsTab.svelte: `hidePreview` import + call). Within trip-wire budget.
- NB-2 + Wave 8b NB-3 (`refreshStats()` error-clear) carry-forward to Wave 10.
- **STOP-POINT 2 reached** per plan §9. Wave 9 CLOSED. User approval requested before Wave 10 (history view); plan §9 also requires "Pre-Wave-10 revisits the Wave 0.5 exploration findings to confirm Wave 10 sub-wave sizing."

---

**END WAVE 9 HANDOFF.**
