/**
 * Pure geometry helper for edit-history diff arrows.
 *
 * Wave 10: extracted from segments/history/rendering.ts
 * (`drawHistoryArrows` + `_drawArrowPath`). Takes numeric inputs only —
 * no DOM or SVG element construction — so `HistoryArrows.svelte` can
 * `bind:` card refs, measure them via `getBoundingClientRect` in
 * `afterUpdate`, pipe the Y positions through this helper, and render
 * the result as declarative `{#each paths as p}<path />`.
 *
 * Five-branch dispatch (preserved verbatim from the imperative impl):
 *   1. N before → empty    : dashed arrows + red-X at target.
 *   2. 1 before → 1 after  : single quadratic bezier.
 *   3. 1 before → N after  : fan-out (one source → each target).
 *   4. N before → 1 after  : fan-in (each source → one target).
 *   5. N before → N after  : zip (min(i, lastIdx) pairing).
 */

export interface ArrowInput {
    /** Y coordinates (canvas-local px) of "before" cards. */
    beforeYs: number[];
    /** Y coordinates (canvas-local px) of "after" cards. Empty = delete. */
    afterYs: number[];
    /** If `afterYs` is empty, the Y of the empty/delete placeholder. */
    emptyY: number | null;
}

export interface ArrowPath {
    /** SVG path "d" attribute. */
    d: string;
    /** Dashed stroke (used for delete arrows). */
    dashed: boolean;
}

export interface XMark {
    /** Center X of the red X glyph. */
    cx: number;
    /** Center Y of the red X glyph. */
    cy: number;
    /** Half-width of each diagonal stroke. */
    size: number;
}

export interface ArrowLayout {
    paths: ArrowPath[];
    xMark: XMark | null;
}

/** Fixed column geometry — matches `.seg-history-arrows` CSS width. */
const X_LEFT = 4;
const X_RIGHT = 56;
const X_X_MARK = 52;
const X_SIZE = 5;

/** Build a single arrow path. Straight line if y1 ≈ y2, else S-curve. */
function buildPath(x1: number, y1: number, x2: number, y2: number, dashed: boolean): ArrowPath {
    const midX = (x1 + x2) / 2;
    const d = Math.abs(y2 - y1) < 2
        ? `M ${x1} ${y1} L ${x2} ${y2}`
        : `M ${x1} ${y1} Q ${midX} ${y1}, ${midX} ${(y1 + y2) / 2} Q ${midX} ${y2}, ${x2} ${y2}`;
    return { d, dashed };
}

/**
 * Compute the final arrow layout for one diff card.
 * Returns `{ paths: [], xMark: null }` when input is degenerate.
 */
export function computeArrowLayout(input: ArrowInput): ArrowLayout {
    const { beforeYs: bY, afterYs: aY, emptyY } = input;
    const paths: ArrowPath[] = [];

    // Branch 1: delete (no "after" cards, empty placeholder Y available).
    if (aY.length === 0 && emptyY != null) {
        for (const sy of bY) paths.push(buildPath(X_LEFT, sy, X_RIGHT, emptyY, true));
        return { paths, xMark: { cx: X_X_MARK, cy: emptyY, size: X_SIZE } };
    }

    if (bY.length === 0 || aY.length === 0) return { paths, xMark: null };

    // Branch 2: 1→1 single curve.
    if (bY.length === 1 && aY.length === 1) {
        paths.push(buildPath(X_LEFT, bY[0]!, X_RIGHT, aY[0]!, false));
        return { paths, xMark: null };
    }

    // Branch 3: 1→N fan-out.
    if (bY.length === 1 && aY.length > 1) {
        for (const ty of aY) paths.push(buildPath(X_LEFT, bY[0]!, X_RIGHT, ty, false));
        return { paths, xMark: null };
    }

    // Branch 4: N→1 fan-in.
    if (bY.length > 1 && aY.length === 1) {
        for (const sy of bY) paths.push(buildPath(X_LEFT, sy, X_RIGHT, aY[0]!, false));
        return { paths, xMark: null };
    }

    // Branch 5: N→N zip with clamping to last index.
    const maxLen = Math.max(bY.length, aY.length);
    for (let i = 0; i < maxLen; i++) {
        const sy = bY[Math.min(i, bY.length - 1)]!;
        const ty = aY[Math.min(i, aY.length - 1)]!;
        paths.push(buildPath(X_LEFT, sy, X_RIGHT, ty, false));
    }
    return { paths, xMark: null };
}
