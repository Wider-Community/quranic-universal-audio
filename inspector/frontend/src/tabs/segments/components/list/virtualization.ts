/**
 * Pure helpers for SegmentsList virtualization.
 *
 * `SegmentsList.svelte` owns the `heights: Map<rowKey, px>` cache (populated
 * by a ResizeObserver on row-group wrappers). These helpers turn that cache
 * plus `$displayedSegments` into prefix sums, window math, and spacer sizes —
 * without touching the DOM or Svelte. Tested directly in
 * `__tests__/SegmentsList.test.ts`.
 *
 * Why prefix sums instead of a rolling-average row height: any row's height
 * change only moves rows *after* it in the prefix sum, so a single card
 * changing size never translates rows above it. The rolling-average approach
 * did — that was the "segment card shakes vertically" bug.
 */

/** Build prefix sums: cum[i] = total px height of rows 0..i-1. Length = n+1. */
export function rebuildCumHeights<T>(
    segs: readonly T[],
    rowKey: (s: T) => string,
    heights: Map<string, number>,
    estimate: number,
): number[] {
    const n = segs.length;
    const out = new Array<number>(n + 1);
    out[0] = 0;
    for (let i = 0; i < n; i++) {
        const key = rowKey(segs[i]!);
        out[i + 1] = out[i]! + (heights.get(key) ?? estimate);
    }
    return out;
}

/**
 * Largest i in [0, cum.length-1] with cum[i] <= y. Used to map a pixel
 * scroll offset to a row index. Binary search; O(log n).
 */
export function findIdxAtOffset(cum: readonly number[], y: number): number {
    if (y <= 0 || cum.length <= 1) return 0;
    let lo = 0;
    let hi = cum.length - 1;
    while (lo < hi) {
        const mid = (lo + hi + 1) >>> 1;
        if ((cum[mid] ?? 0) <= y) lo = mid;
        else hi = mid - 1;
    }
    return lo;
}

/**
 * Height of the spacer above the rendered window.
 *
 * The pinned editing row (when it exists outside the window) is physically
 * rendered at the END of the DOM, not at its logical position. So if it
 * lives at `editingPos < startIdx` we must subtract its height from the top
 * spacer — otherwise its height would be double-counted (once in the spacer,
 * once in the pinned DOM box).
 */
export function topSpacerValue<T>(
    cum: readonly number[],
    startIdx: number,
    editingPos: number,
    segs: readonly T[],
    rowKey: (s: T) => string,
    heights: Map<string, number>,
    estimate: number,
): number {
    let px = cum[startIdx] ?? 0;
    if (editingPos >= 0 && editingPos < startIdx) {
        const seg = segs[editingPos];
        if (seg !== undefined) {
            px -= heights.get(rowKey(seg)) ?? estimate;
        }
    }
    return Math.max(0, px);
}

/** Symmetric subtraction when the pinned row is at or below the window. */
export function bottomSpacerValue<T>(
    cum: readonly number[],
    endIdx: number,
    total: number,
    editingPos: number,
    segs: readonly T[],
    rowKey: (s: T) => string,
    heights: Map<string, number>,
    estimate: number,
): number {
    const totalH = cum[cum.length - 1] ?? 0;
    let px = totalH - (cum[endIdx] ?? totalH);
    if (editingPos >= endIdx && editingPos < total) {
        const seg = segs[editingPos];
        if (seg !== undefined) {
            px -= heights.get(rowKey(seg)) ?? estimate;
        }
    }
    return Math.max(0, px);
}

/** Height for row at `pos`, or `estimate` if unmeasured. */
export function heightForPos<T>(
    pos: number,
    segs: readonly T[],
    rowKey: (s: T) => string,
    heights: Map<string, number>,
    estimate: number,
): number {
    const seg = segs[pos];
    if (seg === undefined) return estimate;
    return heights.get(rowKey(seg)) ?? estimate;
}

/** Pixel offset of the top edge of row `pos` in the scroll container. */
export function topOfRow(cum: readonly number[], pos: number): number {
    return cum[pos] ?? 0;
}
