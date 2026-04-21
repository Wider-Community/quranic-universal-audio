# Wave 10 Locked Approach

> Pre-Wave-10 Opus exploration spec. **Binding** for the Wave 10 impl agent. User directive 2026-04-15: simplest + most reliable wins.

## Component manifest

1. **`lib/stores/segments/history.ts`** (~200 LOC) — single `writable` store + pure helpers absorbed from `history/index.ts`, `filters.ts`, and pure functions from `rendering.ts` (`_flattenBatchesToItems`, `_groupRelatedOps`, `_versesFromRef`, `_countVersesFromBatches`, `_snapToSeg`, `_formatHistDate`, `_computeChainLeafSnaps`, `_histItemChapter`, `_histItemTimeStart`). Shape: `{ data, filterOpTypes, filterErrCats, sortMode, splitChains, chainedOpIds, visible }`.
2. **`lib/utils/svg-arrow-geometry.ts`** (~60 LOC) — pure `computeArrowLayout(input) → { paths, xMark }` per S2-D19. No DOM access.
3. **`tabs/segments/history/HistoryPanel.svelte`** (~120 LOC) — outer panel; subscribes to store; hosts filters + summary + batches list; owns show/hide (absorbs `showHistoryView`/`hideHistoryView` lifecycle behaviors into reactive `visible` store + `{#if}`).
4. **`tabs/segments/history/HistoryFilters.svelte`** (~80 LOC) — filter pills + sort toggles. Pure Svelte rewrite of `renderHistoryFilterBar` + `toggleHistoryFilter` (trivial once counts are derived in-store).
5. **`tabs/segments/history/HistoryBatch.svelte`** (~130 LOC) — the 4-type `{#if}` dispatcher (strip-specials / multi-chapter / revert / op-card) + header (undo/discard/revert badges, issue-delta badges). Absorbs `_renderOpCard`, `_renderSpecialDeleteGroup`, `_appendIssueDeltaBadges`.
6. **`tabs/segments/history/HistoryOp.svelte`** (~100 LOC) — unified single+grouped op rendering per S2-D20. Composes `<SegmentRow mode="history">` for before/after cards + `<HistoryArrows>` in the middle column.
7. **`tabs/segments/history/SplitChainRow.svelte`** (~130 LOC) — the chain variant: root-on-left + N leaves-on-right + waveform range computation via `_computeChainLeafSnaps` helper from store.
8. **`tabs/segments/history/HistoryArrows.svelte`** (~80 LOC) — `bind:this` on container + before/after card refs (passed in as props), measures with `getBoundingClientRect` in `afterUpdate`, pipes numbers into `computeArrowLayout`, renders `<svg>` + inline `<defs>`/`<marker>` + `{#each paths as p}<path />` + optional red-X `<g>`.

**Bonus (not a new file):** `HistorySummaryStats.svelte` (~30 LOC) OR inline inside `HistoryPanel.svelte` — impl's call. Default: inline.

## D1 Arrow technique: **(a) pure helper + reactive binding** [LOCKED]

Wave 0.5 proved: zero resize/scroll listeners exist; 14 lines of quadratic-bezier math; `getBoundingClientRect` is called at exactly 3 sites. `leader-line` is ~35 KB for functionality we don't use (socket-gravity, pathfinding) and inverts Svelte reactivity to imperative teardown/rebuild. Pure helper is strictly simpler and strictly more reliable.

**Impl agent does NOT have to consider**: window `resize` handler, `ResizeObserver`, `IntersectionObserver`, scroll listeners, debouncing, `leader-line`, bundle-size tradeoffs, arrowhead marker uniqueness across instances (inline per-SVG).

## D2 Diff-card layout: **(c) `<SegmentRow mode="history">` composed inside two flex columns** [LOCKED]

Two-column container (`.seg-history-diff` CSS grid `1fr 60px 1fr` preserved verbatim) with `<SegmentRow mode="history" readOnly>` composed for each before/after card. Props `splitHL`, `trimHL`, `mergeHL`, `changedFields` flow reactively — no post-mutation of DOM by `_highlightChanges`. Wave 5 already provisioned these props (verified at `SegmentRow.svelte:44-59`); impl agent must flip the `$: if (splitHL || trimHL || mergeHL || changedFields) void 0;` stub at line 67 into the actual reactive waveform-canvas highlight writes.

## D3 Store granularity: **(a) single `history.ts` writable** [LOCKED]

All history UI state (batches, summary, filters, sort, splitChains, chainedOpIds, visible) lives in ONE store. Per-batch "expanded" UI state stays as local component `let` inside `HistoryBatch.svelte` (no store needed — collapsible state is ephemeral). Avoids coordination overhead of multiple sub-stores and matches Wave 8a/8b/9 precedent.

## D4 Filter UI: **(b) full Svelte rewrite** [LOCKED]

`filters.ts` (252 LOC) is mostly DOM-builder code for pills + a small `applyHistoryFilters` derivation. The derivation is pure (reads items + filter sets → writes items back). Moving count-derivation into the store and pills into `HistoryFilters.svelte` is SIMPLER than keeping imperative helpers and writing a shell wrapper — the shell pattern wins when imperative code is complex (save flow, waveform canvas); here it's all loops and `addEventListener`, trivially Svelte-native.

## D5 HistoryOp consolidation: **confirm S2-D20 (collapse to 1 component with `group: EditOp[]`)** [LOCKED]

Length-1 groups degrade cleanly. 46+54 LOC → ~100 LOC single component. No override.

## D6 `<defs>` placement: **confirm S2-D21 (inline per `HistoryArrows.svelte` instance)** [LOCKED]

~5 diffs on-screen × 4 lines of `<marker>` markup = negligible. Removes global-singleton lifecycle concern. No override.

## D7 `_appendValDeltas` drop: **confirm S2-D22 (drop)** [LOCKED]

Grep confirmed zero call sites. Delete when migrating the rest of `rendering.ts`. No override.

## D8 Single-agent feasibility: **DOABLE in one agent** [LOCKED]

Wave 0.5 removes ~80% of the discovery burden. Comparable in scope to Wave 8a+8b or Wave 7a.1+7a.2.

**Scope-tightening guidance:**
1. **Commit cadence**: one commit per file — store, util, then components in dependency order (`HistoryArrows` → `HistoryOp` → `SplitChainRow` → `HistoryBatch` → `HistoryFilters` → `HistoryPanel`). Target 7–9 commits.
2. **Start with the store + util** (no UI impact) so pre-flight stays green while DOM-builder code still runs. Then land components in dependency order, stubbing the arrow column as an empty `<div>` until `HistoryArrows.svelte` is ready.
3. **Do NOT restructure** `undo.ts` — keep `onBatchUndoClick`/`onOpUndoClick`/`onChainUndoClick`/`onPendingBatchDiscard` imperative and bind to them from Svelte via explicit `on:click={() => onBatchUndoClick(batchId)}`. The S2-B05 fix from Wave 9 must not be disturbed.
4. **Do NOT touch** `save.ts:140`'s call to `drawHistoryArrows` inside save preview until `HistoryArrows.svelte` can mount inside `SavePreview.svelte` too — if tangled, leave imperative for Wave 11 (per S2-D34 softening precedent).
5. **Preserve CSS class names** (`.seg-history-batch`, `.seg-history-diff`, `.seg-history-before`, `.seg-history-after`, `.seg-history-arrows`, `.seg-row`, `.seg-history-changed`, `.seg-history-split-chain`, etc.) — global `styles/history.css` stays in force per Wave 4 pattern note #8.
6. **Mount point**: `HistoryPanel.svelte` replaces the `#seg-history-view` div inside `SegmentsTab.svelte`. Guard: verify `dom.segHistoryView` mustGet still resolves (or migrate that lookup in-wave — small enough).

If the impl agent's token budget approaches ~250k mid-wave, the natural split point is **after arrows lands**: commit arrows + panel wiring, declare a "Wave 10.x continuation" and hand off the remaining cleanup (undo migration, save-preview wire-up) to Wave 11 — but plan for landing everything in one pass.

## D9 Carry-forwards [LOCKED LIST]

- **Wave 9 NB-2** (`data.ts::onSegReciterChange` dual code-path audit) — audit as Wave 10 touches `clearSegDisplay` adjacencies via history store.
- **Wave 7a.1 NB-1** (`syncAllCardsForSegment` stale risk in history) — resolved by `<SegmentRow mode="history">` adoption; verify the old DOM-mutation code path is fully replaced before declaring done.
- **Wave 8b NB-3** (`refreshStats()` clear-on-error) — Wave 10 likely does NOT call `refreshStats()`; if it does as part of undo/revert flow, pair with `clearStats()` on error. Otherwise carry forward to Wave 11.

Wave 7a.2 NB-1 (`_addEditOverlay` no-op stubs) and Wave 8a Opus G (`_rebuildAccordionAfterMerge` innerHTML) are **Wave 11, NOT Wave 10**.

## Risks the impl agent must handle

1. **B1-class Svelte-root clobber**: `HistoryPanel.svelte` owns `#seg-history-view` — do NOT mount it over a DOM node that imperative code (`save.ts:140`) still appendChilds into. Coordinate save-preview arrow wiring explicitly.
2. **Bridge-lag on `visible`**: `showHistoryView`/`hideHistoryView` currently flip `dom.segHistoryView.hidden` imperatively AND mutate `state._histFilter*` / `state._allHistoryItems` / `state._histSortMode`. Use Wave 9's shell-delegation pattern: store → UI binding; keep the `_SEG_NORMAL_IDS` sibling-hide logic imperative for now (cross-tab concern, not Wave 10 scope).
3. **Waveform-canvas highlight props**: `splitHL`/`trimHL`/`mergeHL` currently written as custom HTMLElement properties in `_highlightChanges` + `renderSplitChainRow` + `renderHistoryOp` + `renderHistoryGroupedOp`. In Svelte they MUST flow as reactive props to `<SegmentWaveformCanvas>` via `<SegmentRow>`. Verify the prop chain reaches the canvas and the canvas reacts (Wave 6b owns `SegmentWaveformCanvas`; read that file before wiring).
4. **`_histItemChapter` sentinel**: returns `Infinity` — preserve verbatim; do not "clean up" to `null`.
5. **`_groupRelatedOps` union-find**: preserve verbatim in store module; subtle code.
6. **Split chain filter interaction**: chains hidden when `_histFilterErrCats.size > 0` OR (`_histFilterOpTypes` non-empty AND not containing `split_segment`). Preserve exactly.
7. **`requestAnimationFrame` → `afterUpdate`**: the 4 existing `rAF(drawHistoryArrows)` call sites all dissolve into one `afterUpdate` inside `HistoryArrows.svelte`. Do NOT manually schedule `rAF` — Svelte's `afterUpdate` runs after DOM commit.
8. **`event-delegation.ts` wires to history**: check for history-targeted click handlers before replacing with Svelte `on:click`; those handlers must be either re-pointed or the old DOM left in place until migration is complete.
9. **Cycle ceiling**: currently 14/16. Wave 10 likely dissolves cycles when `history/` directory shrinks; expected count reduction 2–4. Ceiling can be decremented at wave end.

## What's explicitly out of impl agent's scope

- **Wave 11 cleanup items**: `drawBarChart` duplication, `ReferenceEditor` autocomplete, re-promoting `import/no-cycle` to `error`, deleting now-orphan `rendering.ts`/`filters.ts`/`index.ts`/`undo.ts` files (delete only after verification that nothing imports them — safest in Wave 11).
- **Wave 7a.2 NB-1** (`_addEditOverlay` no-op stubs) — Wave 11.
- **Wave 8a Opus G** (`_rebuildAccordionAfterMerge` innerHTML) — Wave 11.
- **`src/audio/index.ts` (audio tab) conversion** — Wave 11 per S2-D06.
- **CSS migration from global to scoped** — Wave 11 per Wave 4 pattern note #8.
- **Automated testing** — out of Stage 2 scope per S2-D07.
- **`undo.ts` function signatures** — keep imperative, call from Svelte templates.
- **`save.ts:140` migration** — attempt at end; if tangled, defer to Wave 11 with documented rationale (S2-D34 softening applies).

LOCKED — ready for impl agent.
