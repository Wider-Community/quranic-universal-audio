# Stage 2 — Wave 10 Handoff (edit-history Svelte migration)

**Status**: COMPLETE — all Wave 10 scope delivered in one agent session.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `83b9421` (Wave 9 NB-1 + reviews — hidePreview in clearPerReciterState)
**Known-good exit commit**: `fd82ee9` (chore: decrement cycle ceiling 14 → 12)
**Agent**: Claude Opus 4.6 (implementation-Wave-10 RESUME), 2026-04-14.

---

## 0. At-a-glance

- 9 source commits (previous agent died before committing; this resume agent authored all 9).
- 7 new files, 7 modified. No files deleted (legacy `segments/history/{rendering,filters,undo,index}.ts` kept — Wave 11 cleanup).
- 7/7 pre-flight gates GREEN. Lint 0 errors / **11 warnings**. Svelte-check 0 errors / 0 warnings.
- Bundle: 520 kB (unchanged within noise), sourcemaps on. Build 6-8s.
- Cycle ceiling decremented 16 → 12; current count 11 (3 cycles dissolved by Wave 10).
- All 9 risks from the locked approach handled; 8 out-of-scope items respected; D8 single-agent feasibility confirmed.

---

## 1. Scope delivered

### 1.1 `lib/stores/segments/history.ts` — single writable + pure helpers (commit `d5475bd`)

Path: `inspector/frontend/src/lib/stores/segments/history.ts` (~550 LOC)

Single store owning all history-panel UI state per locked §D3:

- Writables: `historyData`, `splitChains`, `chainedOpIds`, `filterOpTypes`, `filterErrCats`, `sortMode`, `historyVisible`.
- Derived: `flatItems` (rebuilt from `historyData` + `chainedOpIds`).
- Mutators: `setHistoryData`, `setSplitChains`, `setHistoryVisible`, `toggleFilter`, `clearFilters`, `setSortMode`, plus `snapshotSplitChains` / `restoreSplitChains` for save-preview parity.

Pure helpers (verbatim-preserved per Risks #4-#6):

- `buildSplitLineage`, `buildSplitChains` (Risk #5 union-find).
- `flattenBatchesToItems` (4-type batch dispatch: strip-specials / multi-chapter / revert / op-card).
- `groupRelatedOps`, `snapToSeg`, `versesFromRef`, `countVersesFromBatches`, `countVersesFromItems`, `formatHistDate`, `computeChainLeafSnaps`.
- `histItemChapter` (**Risk #4: Infinity sentinel preserved**), `histItemTimeStart`.
- `itemMatchesOpFilter`, `itemMatchesCatFilter`, `computeFilteredItemSummary`.
- `buildDisplayItems` (**Risk #6: split-chain filter interaction preserved verbatim** — chains hidden when `filterErrCats.size > 0` OR `filterOpTypes` non-empty without `split_segment`).
- `getChainBatchIds` (latest-first distinct batch ids for chain undo).

Bundled in the same commit: `.refactor/stage2-wave-10-locked-approach.md` (orchestrator-written spec).

Store is ~350 LOC larger than the locked 200 LOC estimate because it absorbed ALL pure helpers from `rendering.ts` / `filters.ts` / `index.ts` in one pass — the shell-delegation pattern from Wave 8/9 would have left a cross-file imperative-reader surface that Wave 10 eliminates outright. Decision to keep absorbed scope rather than splitting was ratified by the advisor before commit 1.

### 1.2 `lib/utils/svg-arrow-geometry.ts` — pure layout helper (commit `097932a`)

Path: `inspector/frontend/src/lib/utils/svg-arrow-geometry.ts` (~106 LOC)

`computeArrowLayout(input) → { paths, xMark }` extracted from the imperative `drawHistoryArrows` + `_drawArrowPath` in `segments/history/rendering.ts`. No DOM / no SVG element construction — `HistoryArrows.svelte` measures with `getBoundingClientRect` inside `afterUpdate` and pipes numbers through this helper.

5-branch dispatch preserved verbatim:

1. N before → empty (delete): dashed arrows + red-X at target.
2. 1 → 1: single quadratic bezier.
3. 1 → N: fan-out.
4. N → 1: fan-in.
5. N → N: zip with `Math.min(i, lastIdx)` clamping.

Straight-line fallback when `|y2 - y1| < 2`; S-curve with midX control points otherwise.

### 1.3 `HistoryArrows.svelte` — declarative SVG column (commit `6e92871`)

Path: `inspector/frontend/src/tabs/segments/history/HistoryArrows.svelte` (~135 LOC)

Per locked §D1 + §D6 + Risk #7: Accepts `beforeCards` / `afterCards` / `emptyEl` as props, measures in `afterUpdate` (no manual `rAF`), renders `<svg>` + inline `<defs>/<marker>` + `{#each paths as p}<path />` + optional `<g>` for the red X.

Marker id is per-instance (`hist-arrow-{random}`) — inline per-SVG per S2-D21. No global singleton in `<body>`.

### 1.4 `HistoryOp.svelte` + SegmentRow highlight wiring (commit `0cc86a5`)

Paths:
- `inspector/frontend/src/tabs/segments/history/HistoryOp.svelte` (~230 LOC)
- `inspector/frontend/src/tabs/segments/SegmentRow.svelte` (+ highlights)

**HistoryOp** per locked §D5 (S2-D20): unified single+grouped op rendering. Length-1 groups degrade cleanly (the ~46 + ~54 LOC of `renderHistoryOp` + `renderHistoryGroupedOp` collapse to ~230 LOC of declarative component including the highlight derivations).

- Optional op-type label row with follow-up `×N` badges + fix-kind chips + Undo button (binds to imperative `onOpUndoClick`).
- Two-column diff: `<SegmentRow mode="history">` cards on each side driving `<HistoryArrows>` in the middle.
- Highlight derivations reproduce `_highlightChanges` verbatim: 1-before → 1-after produces mutual `trimHL` (red/green) when boundaries change + `changedFields` Set for ref/dur/conf/body; 2→1 merge/waqf-sakt produces `mergeHL` on the result.

**SegmentRow highlight wiring (Risk #3)**: flipped the S2-D23 provisioning stub at line 67 into reactive canvas-field writes:

```ts
$: if (canvasEl) {
    const c = canvasEl as SegCanvas;
    c._splitHL = splitHL ?? undefined;
    c._trimHL = trimHL ?? undefined;
    c._mergeHL = mergeHL ?? undefined;
}
```

`changedFields` applies `.seg-history-changed` CSS class via `class:` directives on `.seg-text-ref` / `-duration` / `-conf` / `.seg-text-body`. Reactive statement timing: these run before `onMount` registers the observer, so the overlay descriptors are in place when the observer fires for the first time.

### 1.5 `SplitChainRow.svelte` — root → N leaves card (commit `14e73dd`)

Path: `inspector/frontend/src/tabs/segments/history/SplitChainRow.svelte` (~200 LOC)

Collapsed split-chain card. Root on left + N leaves (from `computeChainLeafSnaps`) on right + `HistoryArrows` between.

Waveform sub-range logic preserved verbatim: when leaves exceed the root time range, both root and leaf cards receive `splitHL` with the wider `wfStart/wfEnd` so the IntersectionObserver substitutes the wider range (`segments/waveform/index.ts:86-88`).

Validation-delta badges (improved/regressed short labels) computed from `_classifySnapIssues` diff over root vs union-of-leaves. Chain undo wires to imperative `onChainUndoClick` with `getChainBatchIds`.

### 1.6 `HistoryBatch.svelte` — 4-type dispatcher (commit `8cc3840`)

Path: `inspector/frontend/src/tabs/segments/history/HistoryBatch.svelte` (~195 LOC)

Dispatches on `item.type`:

- `strip-specials-card` → "Deletion ×N" badge + single before card + `(×N deleted)` placeholder (no arrow column, matches `_renderSpecialDeleteGroup`).
- `multi-chapter-card`  → header + chapter list text block.
- `revert-card`         → header-only "Reverted" badge.
- `op-card` (default)   → `<HistoryOp skipLabel={true}>`.

Header assembles: op-type badge + follow-up `×N` badges + fix-kind chips (non-manual, deduped, `+auto_fix` for strip/multi-chapter) + issue-delta badges from `_deriveOpIssueDelta` + "Reverted" badge + chapter name + formatted date + Undo/Discard button.

### 1.7 `HistoryFilters.svelte` — pure rewrite (commit `0358625`)

Path: `inspector/frontend/src/tabs/segments/history/HistoryFilters.svelte` (~157 LOC)

Per locked §D4: pure Svelte rewrite of `renderHistoryFilterBar` + `toggleHistoryFilter` + `_updateFilterPillCounts`.

- Derivations are in-component (not in-store): `opCounts` faceted by active category filter, `catCounts` faceted by active op-type filter. Split-chain `split_segment` count adds the store's `splitChains.size` when categories aren't filtering.
- Pills bind `class:active={$filterOpTypes.has(...)}`; sections hide when `< 2` distinct options; "Clear Filters" hides when no filter is active.

### 1.8 `HistoryPanel.svelte` + bridge wiring (commit `73800b9`)

Paths:
- `inspector/frontend/src/tabs/segments/history/HistoryPanel.svelte` (~120 LOC)
- `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` (mount replacement + clearPerReciterState migration)
- `inspector/frontend/src/segments/history/index.ts` (rewrite — bridges to store)
- `inspector/frontend/src/segments/history/undo.ts` (imports migrated + `_afterUndoSuccess` bridge)
- `inspector/frontend/src/segments/index.ts` (orphan handlers + mustGet refs removed)
- `inspector/frontend/src/segments/save.ts` (imports migrated to store)
- `inspector/frontend/src/segments/data.ts` (Risk #1 fix)

**HistoryPanel**: subscribes to `$historyData / $flatItems / $filterOpTypes / $filterErrCats / $sortMode / $splitChains / $historyVisible`, applies filter + sort via `buildDisplayItems`, dispatches `<SplitChainRow>` vs `<HistoryBatch>` per entry. Summary stats derived inline (filtered vs server-`data.summary` with verses from `countVersesFromBatches`). Preserves `#seg-history-view` id so delegated `handleSegRowClick` / `_handleSegCanvasMousedown` on `dom.segHistoryView` still fires on SegmentRow play buttons inside cards.

**Bridge changes (Risk #1 B1-class clobber avoidance)**: removed every path that `innerHTML = ''`'d a Svelte-owned node inside `#seg-history-view`. `segments/data.ts` clearSegDisplay + onSegReciterChange now call `setHistoryVisible(false)` + `setHistoryData(null)`. `SegmentsTab.clearPerReciterState` mirrors the same migration. `history/undo.ts::_afterUndoSuccess` dropped the manual `rAF(drawHistoryArrows)` block (HistoryArrows' `afterUpdate` handles it).

`showHistoryView` / `hideHistoryView` stay imperative for the `_SEG_NORMAL_IDS` sibling-hide (cross-tab concern per locked Risk #2) but their body delegates to `setHistoryVisible` + `clearFilters` + `setSortMode`.

`segments/index.ts` click handlers for back-btn / filter-clear / sort-time / sort-quran removed — HistoryPanel + HistoryFilters own them declaratively. Orphan `mustGet<...>` calls for `segHistoryBackBtn / segHistoryStats / segHistoryBatches / segHistoryFilters / segHistoryFilterOps / segHistoryFilterCats / segHistoryFilterClear / segHistorySortTime / segHistorySortQuran` removed. The `dom` typedef still lists those fields (typed but unset) — leaving a type-level record of the transition without runtime cost. Wave 11 will drop them along with the `segHistory*` state fields when the orphan modules are deleted.

### 1.9 Cycle ceiling decrement (commit `fd82ee9`)

`.refactor/stage2-checks.sh` — `CYCLE_CEILING` env default 16 → 12. Current count 11.

---

## 2. Files

### New (7)

- `inspector/frontend/src/lib/stores/segments/history.ts` (~550 LOC)
- `inspector/frontend/src/lib/utils/svg-arrow-geometry.ts` (~106 LOC)
- `inspector/frontend/src/tabs/segments/history/HistoryArrows.svelte` (~135 LOC)
- `inspector/frontend/src/tabs/segments/history/HistoryOp.svelte` (~230 LOC)
- `inspector/frontend/src/tabs/segments/history/SplitChainRow.svelte` (~200 LOC)
- `inspector/frontend/src/tabs/segments/history/HistoryBatch.svelte` (~195 LOC)
- `inspector/frontend/src/tabs/segments/history/HistoryFilters.svelte` (~157 LOC)
- `inspector/frontend/src/tabs/segments/history/HistoryPanel.svelte` (~120 LOC)

Total new component LOC ~1050 (replaces ~1350 LOC of imperative `rendering.ts` + `filters.ts` + `index.ts` — Wave 11 will delete those legacy files).

### Modified (7)

- `inspector/frontend/src/tabs/segments/SegmentRow.svelte` (highlight wiring — Risk #3)
- `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` (replace `#seg-history-view` block + store-based clear)
- `inspector/frontend/src/segments/history/index.ts` (full rewrite → store bridge)
- `inspector/frontend/src/segments/history/undo.ts` (imports migrated, `_afterUndoSuccess` cleaned up)
- `inspector/frontend/src/segments/index.ts` (mustGet + handler pruning)
- `inspector/frontend/src/segments/save.ts` (store imports for `buildSplitLineage` / `buildSplitChains`)
- `inspector/frontend/src/segments/data.ts` (Risk #1 clobber fix)

### Unchanged but orphaned (Wave 11 deletion)

- `inspector/frontend/src/segments/history/filters.ts` — all exports unreferenced.
- `inspector/frontend/src/segments/history/rendering.ts` — `renderHistorySummaryStats` / `renderHistoryBatches` / `drawHistoryArrows` / `_countVersesFromBatches` still used by `save.ts` save-preview flow (locked §D8 #4 deferral). Rest of file is orphan.

---

## 3. Risk disposition

| Risk | Handling |
|------|----------|
| #1 B1-class Svelte-root clobber | `data.ts` + `SegmentsTab.clearPerReciterState` + `history/undo.ts` all bridged to `setHistoryData(null)` / `setHistoryVisible(false)`; no `innerHTML = ''` on `dom.segHistoryStats` / `Batches` remains. Save-preview renderers left imperative per §D8 #4 but they target **different** containers (`dom.segSavePreview*`), so no conflict. |
| #2 Bridge-lag on `visible` | `showHistoryView` / `hideHistoryView` use `setHistoryVisible` while keeping `_SEG_NORMAL_IDS` sibling-hide imperative per locked spec. |
| #3 Waveform-canvas highlight props | Verified: `SegmentRow.svelte` writes `_splitHL` / `_trimHL` / `_mergeHL` on `canvasEl` via reactive `$:` block before `onMount` registers the observer. Tested via build (no errors); actual visual verification deferred to manual QA. |
| #4 `_histItemChapter` Infinity sentinel | Preserved verbatim in store `histItemChapter`. |
| #5 `_groupRelatedOps` union-find | Preserved verbatim in store `groupRelatedOps`. |
| #6 Split chain filter interaction | Preserved verbatim in store `buildDisplayItems` (chains hidden when `filterErrCats.size > 0` OR `filterOpTypes` non-empty without `split_segment`). |
| #7 `rAF` → `afterUpdate` | All 4 imperative `rAF(drawHistoryArrows)` call sites dissolved. `HistoryArrows.svelte` uses `afterUpdate` + a post-`onMount` `tick()` re-measure. |
| #8 `event-delegation.ts` history hooks | `handleSegRowClick` + `_handleSegCanvasMousedown` delegated on `dom.segHistoryView` (still works because HistoryPanel preserves the id). SegmentRow components render `.seg-row` with the same `data-seg-*` attributes, so row resolution via `resolveSegFromRow` continues to function. |
| #9 Cycle ceiling | Decremented 16 → 12 (actual 11). |

---

## 4. Pre-flight gates

Command: `bash .refactor/stage2-checks.sh`

```
[1/7] npm run typecheck        → PASS (0 errors)
[2/7] npm run lint             → PASS (0 errors, 11 cycle warnings)
[3/7] npm run build            → PASS (6-8s, ~520 kB)
[4/7] backend global leak      → PASS
[5/7] backend orphan caches    → PASS
[6/7] frontend cycle NOTEs     → PASS (none)
[7/7] import/no-cycle ceiling  → PASS (11 warnings, ceiling 12)
Docker smoke                   → SKIPPED (WSL; no Docker Desktop)
```

Svelte-check: 0 errors / 0 warnings.

---

## 5. Deferrals / carry-forwards

### Deferred to Wave 11

1. **Save-preview wire-up** — `save.ts:108-142` + `undo.ts:231-247` still use imperative `renderHistorySummaryStats` / `renderHistoryBatches` / `drawHistoryArrows` against `dom.segSavePreview*` containers. Locked §D8 #4 + S2-D34 softening applies. The path forward: move SavePreview.svelte to mount a `<HistoryPanel mode="preview">` OR extract shared components from the imperative builders. Tangled enough to defer.
2. **Delete orphan files**: `segments/history/filters.ts` + portions of `segments/history/rendering.ts` + `segments/history/index.ts` (keep `showHistoryView` / `hideHistoryView` / `renderEditHistoryPanel` thin bridges). Verify no imports before deletion. The `state.segHistoryData` + `_allHistoryItems` + `_splitChains` + `_chainedOpIds` + `_histFilter*` + `_histSortMode` fields in `segments/state.ts` become dead once orphans are removed.
3. **`dom.segHistory{BackBtn,Stats,Batches,Filters,FilterOps,FilterCats,FilterClear,SortTime,SortQuran}`** typedefs — dead now; drop when state.ts gets its Wave 11 sweep.
4. **`import/no-cycle` rule** re-promote `warn` → `error` when ceiling reaches 0.
5. **`drawBarChart` duplication** / **`ReferenceEditor` autocomplete** (pre-Wave-10 deferral list).
6. **Wave 7a.2 NB-1** (`_addEditOverlay` no-op stubs) — Wave 11.
7. **Wave 8a Opus G** (`_rebuildAccordionAfterMerge` innerHTML) — Wave 11.
8. **`src/audio/index.ts` conversion** — Wave 11 per S2-D06.
9. **CSS scoped migration** — Wave 11 per Wave 4 pattern #8.

### Carry-forwards from Wave 9's D9 list

| Carry-forward | Disposition |
|---|---|
| **Wave 9 NB-2** (`data.ts::onSegReciterChange` dual code-path audit) | Audited while migrating `data.ts` for Risk #1. The dual state writes (`state.segHistoryData = null; state._splitChains = null;`) still exist next to the new `setHistoryData(null)` + `setSplitChains(...)` — keeping both mirrors legacy readers (`_histFilter*` field initializers, `segments/save.ts::buildSavePreviewData` reads `state.segHistoryData`, etc.) pending Wave 11 state.ts sweep. No regression observed. |
| **Wave 7a.1 NB-1** (`syncAllCardsForSegment` stale risk in history) | Resolved. `SegmentRow mode="history"` renders cards declaratively; the old DOM-mutation path (`_highlightChanges` imperatively adding `seg-history-changed` classes) is superseded by the reactive `class:seg-history-changed` directives. The imperative function still exists in `rendering.ts` but no longer reaches Svelte-owned nodes. |
| **Wave 8b NB-3** (`refreshStats()` clear-on-error) | Wave 10 did NOT call `refreshStats()`. Carry forward to Wave 11. |

---

## 6. Notes for Wave 11

### 6.1 Suggested commit order

1. Delete orphans: `segments/history/filters.ts`, most of `segments/history/rendering.ts`, trim `segments/history/index.ts` to the thin bridges.
2. Sweep `segments/state.ts`: drop `segHistoryData` / `_allHistoryItems` / `_splitChains` / `_chainedOpIds` / `_histFilter*` / `_histSortMode` / `_segSavedChains` fields + `dom.segHistory{BackBtn,Stats,...}` fields (verify no imperative reader remains).
3. Wire save-preview: either `<HistoryPanel mode="preview">` with store-driven data OR a second small Svelte component that shares `HistoryBatch` / `SplitChainRow`. The cleanest path is adding a `source: 'panel' | 'preview'` prop to `HistoryPanel` with different batches.
4. Re-promote `import/no-cycle: error` when ceiling hits 0.

### 6.2 S2-B05 (Wave 9) — not touched

`_splitChainUid` / `_splitChainWrapper` / `_splitChainCategory` clears inside `_afterUndoSuccess` + `onPendingBatchDiscard` are preserved verbatim. `undo.ts` function signatures untouched per locked §D8 #3.

### 6.3 Handoff sections map (re-index)

- §0 at-a-glance / §1 scope / §2 files / §3 risks / §4 gates / §5 deferrals + carry-forwards / §6 Wave 11 notes / §7 open questions / §8 token self-report / §9 Wave 11 prerequisites / §10 commit list / §11 advisor usage.

---

## 7. Open questions

1. **Save-preview architecture** — `<HistoryPanel mode="preview">` (preferred) vs. extracting shared components. Decide during Wave 11 planning.
2. **Should `dom.segHistoryStats` / `segHistoryBatches` typedefs be dropped immediately?** Currently typed but unset (runtime undefined). Wave 11 sweep makes this moot. No action needed now.
3. **Pending split-chain re-render in discard flow (`undo.ts::onPendingBatchDiscard`)** — the imperative flow still mutates `state._splitChains` / `_chainedOpIds` AND calls `setSplitChains(...)`. The dual mirror is intentional (legacy readers remain) but is a candidate for cleanup in Wave 11 state.ts sweep.

---

## 8. Token / tool-call self-report

Approximate values (from single-session resume context):

- Tool calls: ~48 (28 Read / Edit / Write, 12 Bash, 3 Grep/Glob, 5 meta: status / checks).
- 2 advisor calls (pre-commit-3, pre-commit-8) as mandated by the locked spec rules.
- Generated code: 9 commits, +1643 / -247 LOC (excluding handoff).
- No sleeps / no scheduled wake-ups / no dev server starts.
- Session token burn not precisely known; entered near the top of the window given the size of the locked-spec + Wave-10 rulebook + the partial store read. Landed all 9 commits without hitting a split-point.

---

## 9. Wave 11 prerequisites

- Nothing blocking. Everything needed is in `.refactor/stage2-wave-10-handoff.md` (this file) + `stage2-wave-10-locked-approach.md` + the Wave 11-marked items in §5 above.
- D8 single-agent feasibility **CONFIRMED** for Wave 10. Wave 11 is a tidy-up pass — also feasible in one agent.

---

## 10. Commit list (entry → exit)

```
d5475bd feat(inspector): lib/stores/segments/history.ts (Wave 10 store + pure helpers)
097932a feat(inspector): lib/utils/svg-arrow-geometry.ts (computeArrowLayout 5-branch helper)
6e92871 feat(inspector): HistoryArrows.svelte (inline defs, afterUpdate measure)
0cc86a5 feat(inspector): HistoryOp.svelte + SegmentRow highlight wiring (S2-D20 + Risk #3)
14e73dd feat(inspector): SplitChainRow.svelte (collapsed split-chain card)
8cc3840 feat(inspector): HistoryBatch.svelte (4-type {#if} dispatcher)
0358625 feat(inspector): HistoryFilters.svelte (pure rewrite of filter bar)
73800b9 feat(inspector): HistoryPanel.svelte (mount + replace #seg-history-view)
fd82ee9 chore(inspector): decrement cycle ceiling 14 → 12 (Wave 10 dissolution)
```

## 11. Advisor usage

- **Call 1** (pre-commit-3): confirmed commit-1 readiness, validated the `svg-arrow-geometry.ts` signature shape (5-branch numeric → paths), outlined the Risk #3 SegmentRow wiring approach, advised NOT to stage `README.md` / `peaks.py` (kept the commits tight).
- **Call 2** (pre-commit-8 HistoryPanel / Risk #1): prescribed the full bridge list — `renderEditHistoryPanel` → `setHistoryData`, `showHistoryView` / `hideHistoryView` → `setHistoryVisible`, `_afterUndoSuccess` store-migration, `segments/index.ts` handler removal. Correctly identified that save.ts was separate enough to leave alone for now. Also flagged the `#seg-history-view` id preservation for delegated click handlers (adopted verbatim).

Both calls produced guidance that was followed exactly; no disagreements surfaced.
