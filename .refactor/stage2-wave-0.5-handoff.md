# Stage 2 — Wave 0.5 Handoff

**Wave:** 0.5 (focused exploration; pre-Wave-1)
**Date:** 2026-04-13
**Scope:** `inspector/frontend/src/segments/history/rendering.ts` (696 LOC, not 695 — header line included)
**Goal:** De-risk Wave 10 sizing and inform `lib/utils/svg-arrow-geometry.ts` extraction.

## 1. Function-by-function map

| Function | LOC | Category | Role | State reads | State mutates | DOM produced |
|---|---|---|---|---|---|---|
| `renderHistorySummaryStats` (L42–62) | 21 | dom-render | Build three stat cards (operations / chapters / verses). | — (data-arg only) | — | `.seg-history-stat-cards` + 3× `.seg-history-stat-card` |
| `_versesFromRef` (L68–80) | 13 | pure-logic | Parse a `"1:1-1:7"` style ref into `["1:1", ..., "1:7"]`. | — | — | — |
| `_countVersesFromBatches` (L82–93) | 12 | pure-logic | Walk all snaps in a batch list, union their refs into a verse set. | — | — | — |
| `renderHistoryBatches` (L99–106) | 8 | dom-render | Top entry; reads `state._chainedOpIds`, delegates to flatten + renderDisplayItems. | `state._chainedOpIds` | — | Nothing directly |
| `_renderHistoryDisplayItems` (L112–163) | 52 | dom-render | Merge chains + op items, sort by `time` or `quran` mode, append each. | `state._splitChains`, `state._histFilterErrCats`, `state._histFilterOpTypes`, `state._histSortMode` | sets `container.innerHTML=''` | A flat run of `.seg-history-batch` / `.seg-history-split-chain` children |
| `_flattenBatchesToItems` (L169–200) | 32 | pure-logic | Convert `HistoryBatch[]` → `OpFlatItem[]` with per-batch-type branching (strip-specials / multi-chapter / revert / normal). | — (all via args) | — | — |
| `renderSplitChainRow` (L206–296) | 91 | dom-render | The "chain" variant of a batch card — header + before/after diff with waveform highlight ranges. | reads chain props only | writes `_splitHL` on `SegCanvas` | Large `.seg-history-split-chain` subtree including `<svg>` arrow placeholder |
| `renderHistoryGroupedOp` (L304–357) | 54 | dom-render | Near-duplicate of `renderHistoryOp` — handles a group of related ops sharing a diff row. | — | writes `_trimHL` / `_mergeHL` via `_highlightChanges` | `.seg-history-grouped-op` wrap |
| `renderHistoryOp` (L363–408) | 46 | dom-render | Single-op diff row (before col + arrow col + after col). | — | writes `_trimHL`/`_mergeHL` | `.seg-history-op` wrap |
| `_renderOpCard` (L414–462) | 49 | dom-render | The 4-type dispatcher. Picks body based on `item.type` (`strip-specials-card` / `multi-chapter-card` / `revert-card` / `op-card`). | — (takes `OpFlatItem`) | — | `.seg-history-batch` |
| `_renderSpecialDeleteGroup` (L468–478) | 11 | dom-render | Compact "×N deleted" body for strip-specials card. | — | — | `.seg-history-diff` with only before+empty after |
| `_groupRelatedOps` (L484–501) | 18 | pure-logic | Union-find-by-UID grouping of ops within a non-special batch. | — | — | — |
| `_snapToSeg` (L507–519) | 13 | pure-logic | Coerce a `HistorySnapshot` into a `Segment` shape for `renderSegCard`. | — | — | — |
| `_highlightChanges` (L521–531) | 11 | dom-mutate | Compare before/after snaps; add `.seg-history-changed` to text bits and set `_trimHL` on canvases. | — | mutates given cards + their canvas (`_trimHL`) | — (class toggles + canvas prop writes) |
| `_appendIssueDeltaBadges` (L537–541) | 5 | dom-render | Append "-badge" / "+badge" spans from `_deriveOpIssueDelta`. | — | — | spans inside given header |
| `_appendValDeltas` (L543–560) | 18 | dom-render | **Currently unused within this file**; walks validation cats + emits delta badges. | `state._validationCategories` | — | spans |
| `_formatHistDate` (L566–572) | 7 | pure-logic | ISO → `"Apr 13 14:22"`. | — | — | — |
| `_ensureHistArrowDefs` (L578–601) | 24 | dom-mutate (lifecycle) | Idempotently inject a global `<svg id="hist-arrow-defs">` with `<marker>` into `document.body`. | — | `document.body` | One hidden global `<svg>` + `<defs>` + `<marker>` (singleton) |
| `drawHistoryArrows` (L603–646) | 44 | dom-measure + dom-render | The only DOM-measurement function in the file. Queries `.seg-row` inside a diff, measures each with `getBoundingClientRect`, then calls `_drawArrowPath` per mapping. | — | — (mutates passed-in SVG only) | Paths + optional red-X inside the diff's `<svg>` |
| `_drawArrowPath` (L648–661) | 14 | pure-logic + dom-render | Pure coordinate math + 1 appendChild. Quadratic-bezier or straight line depending on \|Δy\|. | — | — | one `<path>` |
| `_histItemChapter` (L667–673) | 7 | pure-logic | Sort-key helper for chapter. | — | — | — |
| `_histItemTimeStart` (L675–680) | 6 | pure-logic | Sort-key helper for time. | — | — | — |
| `_computeChainLeafSnaps` (L686–695) | 10 | pure-logic | Compute leaf (unreplaced) snaps of a chain. | — | — | — |

Summary:
- **dom-render**: 11 functions (~372 LOC, ~53%)
- **pure-logic**: 9 functions (~106 LOC, ~15%)
- **dom-measure+render (arrows)**: `drawHistoryArrows` only, 44 LOC
- **dom-mutate (global lifecycle)**: `_ensureHistArrowDefs`, 24 LOC; `_highlightChanges`, 11 LOC
- **event-wire**: inline — only in `renderSplitChainRow` (undo button), `renderHistoryGroupedOp`/`renderHistoryOp` (undo), `_renderOpCard` (undo/discard). No standalone event-wire function.

## 2. SVG-arrow geometry deep dive

**Where:** `drawHistoryArrows` L603–646 + `_drawArrowPath` L648–661. `_ensureHistArrowDefs` L578–601 is a one-time global setup (arrowhead marker in `<body>`).

**Re-layout triggers — important finding:** there is NO `resize` listener, NO `scroll` listener, NO `ResizeObserver`, NO `IntersectionObserver` for arrows. `grep` confirms the ONLY callers of `drawHistoryArrows` schedule it via `requestAnimationFrame` once per render pass:

- `history/index.ts:56` — on `showHistoryView`
- `history/filters.ts:126` — on filter change
- `history/undo.ts:35, 227` — post-undo
- `save.ts:140` — in save preview

This is significant: arrows are draw-once-per-render. They do NOT dynamically reposition on window resize or on user-initiated accordion expand. (The cards inside are static-height once rendered; only waveform canvas lazily paints later, but its DOM height is already 40px from CSS.) **This collapses Wave 10b dramatically** — Svelte's `$: drawArrowsInEffect(containerRef, diffItems)` with an `afterUpdate` trigger is sufficient.

**Inputs (DOM measurement):** exactly 3 `getBoundingClientRect` call sites (L613, L618, L623):

```ts
const colRect = arrowCol.getBoundingClientRect();                       // L613
const midYs = (cards) => Array.from(cards).map(c => {
    const r = c.getBoundingClientRect();
    return r.top + r.height / 2 - colRect.top;                          // L617-618
});
// ...and (only when empty):
const eRect = afterEmpty.getBoundingClientRect();                        // L623
```

All measurements are relative to the arrow column's top (`colRect.top`), so they're viewport-independent — ideal for a pure helper.

**Path computation:** `_drawArrowPath` is a beautiful 14-liner:

```ts
const midX = (x1 + x2) / 2;
const d = Math.abs(y2 - y1) < 2
    ? `M ${x1} ${y1} L ${x2} ${y2}`
    : `M ${x1} ${y1} Q ${midX} ${y1}, ${midX} ${(y1 + y2) / 2} Q ${midX} ${y2}, ${x2} ${y2}`;
```

Straight line when horizontal (\|Δy\|<2); otherwise two quadratic beziers mirrored across the column midline (a smooth S-curve). `x1=4`, `x2=56` hard-coded; column is 60px wide per CSS.

**Branching logic in `drawHistoryArrows`:**
1. `afterEmpty` path (deletion): dashed arrows from each before to the empty placeholder + a red X at (52, targetY).
2. `1:1` (trim / edit): one arrow.
3. `1:N` (split): one source to N targets.
4. `N:1` (merge): N sources to one target.
5. `N:N`: pair by index, clamping with `Math.min(i, len-1)`.

**Cleanup lifecycle:** on redraw the function does `svg.innerHTML = ''` (L610) and rebuilds. The global `#hist-arrow-defs` is append-once and never torn down (fine — it's one hidden SVG). `svg.setAttribute('height', String(colRect.height))` uses the measured height so the SVG matches the diff's row height.

## 3. Split-chain layout algorithm

**Visual shape**: a split chain is rendered as ONE wide diff row (class `.seg-history-split-chain` + `.seg-history-batch`) — NOT nested or threaded. Header shows `"Split → N"` badge + chain-wide validation deltas. Body is the usual 3-column grid: root snapshot on the left, arrow column in the middle, every leaf snap stacked on the right.

**Data input**: a `SplitChain` (from `state.ts`):
- `rootSnap`: the pre-split parent snapshot (first `targets_before` of the root `split_segment` op).
- `rootBatch`: the batch containing the root split.
- `ops`: every `split_segment` / `trim_segment` / `edit_reference` / `confirm_reference` absorbed into this chain (sequential, insertion order).
- `latestDate`: ISO stamp for sort.

`_buildSplitChains` (in `history/index.ts` L146–191, not this file) builds these. This file only **consumes** them and computes leaves via `_computeChainLeafSnaps`.

**Layout steps** in `renderSplitChainRow`:
1. Compute leaf snaps with `_computeChainLeafSnaps` — walk all ops, track `finalSnaps` (last seen after-snap per UID) minus `beforeUids` (UIDs that appear as a `before` in a later op and were replaced). Sort leaves by `time_start`.
2. Compute waveform viewport: `wfStart = min(rootSnap.time_start, all leafSnap.time_start)`, `wfEnd` analogous. If leaves exceed the root range (`wfExpanded`), stamp `_splitHL` on each card's canvas so the waveform renders the union range with the individual leaf highlighted.
3. Render root before-card on left, each leaf after-card on right. Put a single `<svg>` placeholder in the middle arrow column.
4. Header badges derive "improved" / "regression" classification by comparing issue sets of root vs union of leaves (`_classifySnapIssues`).
5. Undo button uses `_getChainBatchIds(chain)` to collect all batch IDs participating in the chain.

**Edge cases handled**:
- **Mixed chains + standalone ops**: `_renderHistoryDisplayItems` merges both into a single sorted list. Chains are kept only when they intersect with currently visible (post-filter) batches (L122–127).
- **All leaves deleted**: shows `"(all segments deleted)"` empty placeholder in the after column (L280–284).
- **Cross-batch chains**: supported by design — `chain.ops` spans batches, `_getChainBatchIds` aggregates the set.
- **Filter interaction**: chains are hidden if `_histFilterErrCats.size > 0` (category filter active) OR if `_histFilterOpTypes` is non-empty but doesn't include `split_segment` (L119–121).

## 4. Diff-card before/after layout

**HTML structure** (common to `renderSplitChainRow`, `renderHistoryGroupedOp`, `renderHistoryOp`, `_renderSpecialDeleteGroup`):

```
.seg-history-batch[.is-revert?][.seg-history-split-chain?]
  > .seg-history-batch-header           (time, chapter, badges, undo/discard btn)
  > .seg-history-batch-body
      > [maybe .seg-history-op-label / .seg-history-chapter-list for multi-chapter]
      > .seg-history-diff                (CSS grid: 1fr 60px 1fr)
          > .seg-history-before          (flex col of .seg-row cards)
          > .seg-history-arrows           (contains <svg>)
          > .seg-history-after            (flex col of .seg-row cards or .seg-history-empty)
```

**CSS selector dependencies** (in `styles/history.css`, lines verified L273–340):
- `.seg-history-diff` grid layout with `grid-template-columns: 1fr 60px 1fr` — load-bearing constant; the `60px` middle col matches `x1=4, x2=56` in `_drawArrowPath`. If the Svelte component changes column width, the helper must accept it as a parameter.
- `.seg-history-arrows` + `.seg-history-arrows svg { width: 60px; overflow: visible; }` — arrow SVG sizing is CSS-driven, height set imperatively per diff.
- `.seg-history-diff .seg-row { flex-direction: column; gap: 4px; }` — overrides the default horizontal `.seg-row` layout; this is the reason history cards stack waveform-above-text.
- `.seg-history-diff .seg-text.conf-high/mid/low/fail` — override confidence-color border to `border-top` instead of `border-left`.
- `.seg-history-changed` — orange text color applied in `_highlightChanges`.
- `.seg-history-val-delta.improved` (green), `.regression` (red) — badge colors.

**Text-level diff highlighting** is in `_highlightChanges` (L521–531). It compares 4 fields:
- `matched_ref` → toggles `.seg-history-changed` on `.seg-text-ref` (after card).
- `time_start`/`time_end` → toggles on `.seg-text-duration`, AND writes `_trimHL` onto both canvases so each waveform renders the other's range dimly (red/green).
- `confidence` → toggles on `.seg-text-conf`.
- `matched_text` → toggles on `.seg-text-body`.

**Cross-component coupling to flag**: `_highlightChanges` plus the trim/merge/split highlight logic in `renderSplitChainRow` / `renderHistoryOp` / `renderHistoryGroupedOp` write custom properties `_splitHL`, `_trimHL`, `_mergeHL` onto `SegCanvas` HTMLElements. `SegCanvas` is defined in `segments/waveform/types`. In Svelte these cannot be imperative side effects on child DOM — they must flow as props to a `SegmentRow.svelte` in `readOnly`/history mode (or to a dedicated `HistorySegmentRow.svelte`). **Wave 5's `SegmentRow.svelte` must accept `splitHL?`, `trimHL?`, `mergeHL?` props for Wave 10 to work.**

## 5. DOM-measurement vs pure-computation separation

**DOM-measurement functions** (the minimum set):
- `drawHistoryArrows` (L603–646) — contains the ONLY 3 `getBoundingClientRect` call sites in the file.
- `_ensureHistArrowDefs` — global marker-defs lifecycle; not really a "measurement".

**Pure data→string/array functions** (safely portable to `lib/utils/svg-arrow-geometry.ts`):
- `_drawArrowPath`'s path-string math (currently bundled with `document.createElementNS` + `appendChild` — needs extraction).
- The branching logic in `drawHistoryArrows` (deletion / 1:1 / 1:N / N:1 / N:N pairing).

**Verdict — cleanly separable.** The separation is almost surgical. The component does 3 `getBoundingClientRect`s, derives `colHeight + beforeMidYs + afterMidYs + (optional) emptyMidY`, and passes those into a pure helper. Helper returns path descriptors. Svelte template renders them.

**Recommended helper signature** (the plan's `computeArrowPath(fromRect, toRect) → string` is too simple — it treats arrows as 1:1; the real mapping logic is branching):

```ts
export interface ArrowSpec {
    d: string;                // SVG path `d` attribute
    dashed: boolean;
}
export interface ArrowLayoutInput {
    colHeight: number;
    colWidth: number;         // 60 by default; parameterize for future
    beforeMidYs: number[];
    afterMidYs: number[];     // empty if after-col is empty
    emptyMidY: number | null; // when afterMidYs is empty
}
export interface ArrowLayoutResult {
    paths: ArrowSpec[];
    xMark: { cx: number; cy: number; size: number } | null;
}
export function computeArrowLayout(input: ArrowLayoutInput): ArrowLayoutResult;
```

~60 LOC including the path-string helper and branching. **No `getBoundingClientRect` callback needed** — the Svelte component does the measurement (`bind:this` on the column + `[bind:this]` on each `.seg-row` + `clientHeight` or inline `getBoundingClientRect`) and passes pre-measured numbers into the pure helper. This is cleaner than a callback-injection pattern.

## 6. Estimated LOC after Svelte conversion

| File | Est. LOC | Basis |
|---|---|---|
| `lib/utils/svg-arrow-geometry.ts` (pure helper) | ~60 | Path math + 5-branch layout + types. Slightly over the plan's 50. |
| `HistoryArrows.svelte` (template + measurement) | ~80 | `<svg>` + `{#each paths}` + `afterUpdate`/`$:` measurement + `bind:this` on container + optional red-X. Includes `<svelte:head>` for the global marker `<defs>`. |
| `HistoryBatch.svelte` (absorbs `_renderOpCard` + `renderHistorySummaryStats`'s card pattern at the item level) | ~130 | 4-type `{#if}` dispatcher + header (undo/discard/revert/pending badges + issue-delta badges) + body slot. |
| `HistoryOp.svelte` (unified `renderHistoryOp` + `renderHistoryGroupedOp`) | ~100 | These two are near-duplicates and collapse. The `skipLabel` prop + grouped-badge secondary spans cleanly template-ify. Handles `_highlightChanges` logic (probably through `<SegmentRow readOnly splitHL={…}>`). |
| `SplitChainRow.svelte` | ~130 | `renderSplitChainRow` body. Most verbose component because of header badge derivation + leaf-snap waveform-range computation (the `_computeChainLeafSnaps` call + min/max over leaves). |
| `HistoryPanel.svelte` (hosts filters, summary, batches list, handles `_renderHistoryDisplayItems` sort + filter flow) | ~120 | `{#each displayItems}` + sort in `$:` derivation + `<HistoryFilters>` slot. |
| `HistoryFilters.svelte` (already in plan, ~absorbs `filters.ts` pill rendering) | — | Not counted here (not in rendering.ts scope). |
| `lib/stores/segments/history.ts` (the data + flatten + chain logic) | ~200 | Absorbs `_flattenBatchesToItems`, `_groupRelatedOps`, `_versesFromRef`, `_countVersesFromBatches`, `_snapToSeg`, `_formatHistDate`, `_computeChainLeafSnaps`, `_histItemChapter`, `_histItemTimeStart` as pure functions exported from the store module. |

**Total Svelte estimate**: ~700 LOC split across 5 `.svelte` components + 1 pure helper + 1 store module. **Roughly same total as today (696)**, but distributed such that no single file exceeds ~130 LOC.

This matches the plan's §5 component inventory exactly (HistoryPanel, HistoryFilters, HistoryBatch, HistoryOp, SplitChainRow, HistoryArrows).

## 7. Wave 10 sub-wave sizing recommendation

**Recommendation: keep the 2-sub-wave split. Do NOT escalate to 3.**

**Sub-wave 10a** (~450 LOC net; store + components except arrows):
- `lib/stores/segments/history.ts` (~200 LOC). Pure functions + `writable` store for `batches`, `filters`, `sortMode`, `splitChains`, `chainedOpIds`.
- `HistoryPanel.svelte` (~120).
- `HistoryBatch.svelte` (~130).
- `HistoryOp.svelte` (~100, unified from both `renderHistoryOp` + `renderHistoryGroupedOp`).
- `SplitChainRow.svelte` (~130).
- `HistoryFilters.svelte` + `clearHistoryFilters`/`setHistorySort`/`applyHistoryFilters` (covered here since they share the store).
- Arrow slot: render empty `<div class="seg-history-arrows">` placeholders; no SVG yet.
- **Smoke**: batches render, diffs show, filters work, undo/discard buttons work. Arrow column is blank.

**Sub-wave 10b** (~140 LOC):
- `lib/utils/svg-arrow-geometry.ts` (~60).
- `HistoryArrows.svelte` (~80) with `afterUpdate`-driven measurement and pure-helper call.
- Global `<defs>` in `App.svelte`'s `<svelte:head>` or in `HistoryArrows.svelte` itself.
- **Smoke**: arrows render correctly for every case (1:1 / 1:N / N:1 / N:N / deletion with X).

**Why not 3 sub-waves**:
- Total net LOC is comparable to today's single file.
- The store+components slice (10a) is well-bounded; none of the components exceed ~130 LOC.
- Arrow slice (10b) is ~140 LOC with one new pure module — trivially a single agent run.
- Splitting 10a further (e.g., SplitChainRow alone) creates coordination overhead without a risk reduction benefit. The 4 components share the history store and can be implemented in one pass.

## 8. `leader-line` library viability

**Verdict: NOT recommended. Pure helper is clearly the right call.**

**API shape**: imperative, JS-only. Constructor `new LeaderLine(startElement, endElement, options)`. You call `.position()` after layout changes and `.remove()` on destroy. Integration with Svelte means `onMount` to construct + `afterUpdate` to `position()` + `onDestroy` to `remove()`, plus keeping references in an array per diff-block.

**Bundle cost**: leader-line is ~35 KB min+gzipped, includes its own SVG-marker management and socket-gravity calculations that this use case doesn't need.

**Edge case coverage concerns**:
- The red-X deletion marker isn't a leader-line concept; still requires custom SVG overlay.
- The dashed-line (deletion) vs solid-line (normal) distinction is a config flag — fine.
- The 1:N, N:1, N:N pairing would need one leader-line instance per pair — more objects to manage than current 4–8 paths per diff.
- No reactive data binding; every update is imperative teardown + rebuild, which loses Svelte's diff advantage.

**Why pure helper wins decisively here**:
- Arrow math is 14 lines of quadratic-bezier. No arc, no socket-gravity, no pathfinding.
- No resize / scroll / dynamic reposition requirement (confirmed §2) — eliminates the main reason to use leader-line.
- `<svelte:head>` for the marker `<defs>` + `{#each paths as p}<path d={p.d} />{/each}` in the component gives Svelte reactivity for free.
- Keeps the SVG declarative and diffable; leader-line would invert this to imperative.

**Fallback plan**: the plan already lists leader-line as a fallback for 10b. Keep that contingency in the decisions log but budget zero work for it — pure helper is confirmed viable.

## 9. Risks / surprises for Wave 10 implementation agent

**Surprises beyond the plan**:

1. **Global SVG marker singleton (`_ensureHistArrowDefs`) is appended to `document.body`, not to the component's tree.** In Svelte, this belongs in a top-level `<svelte:head>` (inside `App.svelte` or `HistoryArrows.svelte`), OR inline in every arrow SVG (~4 lines of markup, acceptable duplication for ~5 diffs on screen). **Recommendation**: inline the `<marker>` directly in each `HistoryArrows.svelte` instance — simpler, no cross-component coupling, negligible DOM overhead.

2. **Hard dependency on `SegmentRow.svelte` accepting history-mode props.** `rendering.ts` imports `renderSegCard` from `../rendering` — the general segment-card renderer. It passes `{ readOnly: true, showChapter: true, showPlayBtn: true }`. Then it post-mutates the returned card by setting `_splitHL`, `_trimHL`, `_mergeHL` on its canvas and adding `.seg-history-changed` to inner text elements. Wave 5's `SegmentRow.svelte` must support props: `readOnly`, `showChapter`, `showPlayBtn`, `splitHL?`, `trimHL?`, `mergeHL?`, `changedFields?: Set<'ref'|'duration'|'conf'|'body'>`. Wave 10 agent should verify these props exist before starting 10a; if missing, add them in a Wave 10 prep commit.

3. **Near-duplicate functions collapse in Svelte.** `renderHistoryOp` (46 LOC) and `renderHistoryGroupedOp` (54 LOC) are ~90% the same code. In Svelte they become one `HistoryOp.svelte` that takes `group: EditOp[]` (length-1 degrades to single-op rendering). This cuts ~50 LOC from the estimate and reduces risk of drift.

4. **`_appendValDeltas` is dead code.** Grep confirms it is exported but has zero call sites in the repo. Wave 10 agent can safely drop it. Flag this in the handoff diff.

5. **No resize/scroll re-layout.** The plan speculated on resize triggers. The actual code has none. Wave 10b does NOT need `ResizeObserver`, `window.addEventListener('resize')`, or scroll tracking. A single `afterUpdate` hook after data changes is sufficient.

6. **`drawHistoryArrows` is called from 4 sites.** In Svelte, the equivalent is one `afterUpdate` in `HistoryArrows.svelte` — all 4 trigger-sites dissolve into natural reactivity. The save-preview call site (`save.ts:140`) means `HistoryArrows.svelte` must be reusable inside both `HistoryPanel.svelte` and `SavePreview.svelte` — which it is by design.

7. **`_histItemChapter` returns `Infinity` as a sentinel.** Sort stability relies on `Infinity` comparing correctly. In Svelte, keep the sentinel semantics intact; don't "clean up" to `null` + conditional — that'd change sort order for pending / multi-chapter items.

8. **`_groupRelatedOps` is a small union-find.** Preserve it verbatim in the store module — it's subtle and already tested by existing usage. Do not rewrite.

9. **CSS selector `.seg-history-diff .seg-row { flex-direction: column }` overrides the default horizontal segment-card layout.** When `SegmentRow.svelte` is scoped-styled in Svelte, this global override needs either (a) a `mode="history"` prop on `SegmentRow.svelte` that changes its own scoped layout, or (b) a global style fragment. Option (a) is cleaner.

**Do any findings suggest the plan needs revision? Short answer: minor clarifications only, no structural revision.**

- LOC estimate for `svg-arrow-geometry.ts` bumps from 50 to ~60. Non-material.
- Helper signature in the plan (`computeArrowPath(fromRect, toRect) → string`) should be replaced with `computeArrowLayout(input) → { paths, xMark }`. Update S2-D16 decision wording to reflect this.
- 2 sub-waves is correct; no 3rd needed.
- `leader-line` fallback should be deprioritized (keep in decisions log for documentation but treat as near-zero probability).

## 10. Confidence summary

- **LOC estimate confidence**: **High.** The file is fully read, functions counted, Svelte component boundaries match natural semantic cleavages, no hidden complexity.
- **Sub-wave sizing confidence**: **High.** 10a is ~450 net LOC / 4 components + store. 10b is ~140 LOC / 1 component + pure helper. Both fit single-agent budgets comfortably.
- **Separation (helper vs component) confidence**: **High.** Exactly 3 `getBoundingClientRect` calls in one function. Pure math is already cleanly isolated in `_drawArrowPath`. Zero callback threading needed.

**One-sentence summary for the Wave 10 agent**: `history/rendering.ts` decomposes cleanly into 5 Svelte components + 1 pure `svg-arrow-geometry.ts` + 1 store module; the SVG arrows are drawn once per render (no resize/scroll listeners), the geometry is a 14-line quadratic-bezier helper with five mapping-cardinality branches, and the main risk is cross-component coupling on `SegmentRow.svelte` accepting history-mode props (`splitHL`, `trimHL`, `mergeHL`, `changedFields`) — which Wave 5 must provision.

---

**File paths referenced (absolute)**:
- Target: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/inspector/frontend/src/segments/history/rendering.ts`
- Siblings: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/inspector/frontend/src/segments/history/{index,filters,undo}.ts`
- CSS: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/inspector/frontend/src/styles/history.css`
- State types: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/inspector/frontend/src/segments/state.ts` (lines 58–109 for `SplitChain`, `HistorySnapshot`, `OpFlatItem`)
- Parent card renderer (dependency): `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/inspector/frontend/src/segments/rendering.ts` (`renderSegCard`)
