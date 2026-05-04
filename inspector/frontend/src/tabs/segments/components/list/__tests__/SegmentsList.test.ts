import { describe, expect, it } from 'vitest';

import {
    bottomSpacerValue,
    findIdxAtOffset,
    heightForPos,
    rebuildCumHeights,
    topOfRow,
    topSpacerValue,
} from '../virtualization';

type FakeSeg = { uid: string; chapter: number; index: number };
const rowKey = (s: FakeSeg): string => s.uid;

/** Build N segments; every 7th row is "tall" (to mimic validation-tagged rows). */
function makeSegs(n: number): FakeSeg[] {
    return Array.from({ length: n }, (_, i) => ({
        uid: `u${i}`,
        chapter: 1,
        index: i,
    }));
}

/** Heights Map where every 7th row is 300px, others 120px. */
function makeHeights(segs: FakeSeg[]): Map<string, number> {
    const m = new Map<string, number>();
    for (const s of segs) m.set(rowKey(s), s.index % 7 === 0 ? 300 : 120);
    return m;
}

describe('SegmentsList virtualization — prefix sums', () => {
    it('rebuildCumHeights produces monotonic sums starting at 0', () => {
        const segs = makeSegs(100);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        expect(cum).toHaveLength(101);
        expect(cum[0]).toBe(0);
        for (let i = 1; i < cum.length; i++) {
            expect(cum[i]).toBeGreaterThan(cum[i - 1]!);
        }
    });

    it('falls back to estimate for unmeasured rows', () => {
        const segs = makeSegs(5);
        const heights = new Map<string, number>();
        heights.set('u2', 200);
        const cum = rebuildCumHeights(segs, rowKey, heights, 100);
        expect(cum).toEqual([0, 100, 200, 400, 500, 600]);
    });

    it('findIdxAtOffset maps a scroll offset to the row whose top is at-or-above', () => {
        const cum = [0, 120, 240, 540, 660, 780];
        expect(findIdxAtOffset(cum, -10)).toBe(0);
        expect(findIdxAtOffset(cum, 0)).toBe(0);
        expect(findIdxAtOffset(cum, 119)).toBe(0);
        expect(findIdxAtOffset(cum, 120)).toBe(1);
        expect(findIdxAtOffset(cum, 239)).toBe(1);
        expect(findIdxAtOffset(cum, 240)).toBe(2);
        expect(findIdxAtOffset(cum, 500)).toBe(2);
        expect(findIdxAtOffset(cum, 10_000)).toBe(5);
    });

    it('topOfRow + heightForPos describe the same row as cumHeights', () => {
        const segs = makeSegs(10);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        for (let i = 0; i < 10; i++) {
            const top = topOfRow(cum, i);
            const h = heightForPos(i, segs, rowKey, heights, 140);
            expect(top + h).toBe(topOfRow(cum, i + 1));
        }
    });
});

describe('SegmentsList virtualization — spacer invariant', () => {
    const INVARIANT = 'topSpacer + sum(window heights) + bottomSpacer === totalHeight';

    it(INVARIANT, () => {
        const segs = makeSegs(200);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        const totalH = cum[cum.length - 1]!;
        const startIdx = 50;
        const endIdx = 80;
        const editingPos = -1; // no pin
        const top = topSpacerValue(cum, startIdx, editingPos, segs, rowKey, heights, 140);
        const bottom = bottomSpacerValue(cum, endIdx, segs.length, editingPos, segs, rowKey, heights, 140);
        let windowSum = 0;
        for (let i = startIdx; i < endIdx; i++) {
            windowSum += heightForPos(i, segs, rowKey, heights, 140);
        }
        expect(top + windowSum + bottom).toBe(totalH);
    });

    it('invariant holds after a height change AFTER the window (no shift above)', () => {
        const segs = makeSegs(200);
        const heights = makeHeights(segs);
        const cum0 = rebuildCumHeights(segs, rowKey, heights, 140);
        const startIdx = 50;
        const endIdx = 80;
        const top0 = topSpacerValue(cum0, startIdx, -1, segs, rowKey, heights, 140);

        // Row 150 grows by 200px (e.g. validation tags arrive).
        heights.set('u150', heights.get('u150')! + 200);
        const cum1 = rebuildCumHeights(segs, rowKey, heights, 140);
        const top1 = topSpacerValue(cum1, startIdx, -1, segs, rowKey, heights, 140);

        // Crucial: the spacer above the current window must NOT change when
        // a row below the window grows. This is the property the rolling-
        // average approach violated and that caused the shake.
        expect(top1).toBe(top0);

        // Invariant still holds.
        const bottom1 = bottomSpacerValue(cum1, endIdx, segs.length, -1, segs, rowKey, heights, 140);
        let windowSum = 0;
        for (let i = startIdx; i < endIdx; i++) {
            windowSum += heightForPos(i, segs, rowKey, heights, 140);
        }
        expect(top1 + windowSum + bottom1).toBe(cum1[cum1.length - 1]!);
    });

    it('pinned editing row above the window is excluded from top spacer', () => {
        const segs = makeSegs(100);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        const startIdx = 40;
        const endIdx = 60;
        const editingPos = 10; // above window, pinned
        const pinnedH = heights.get(rowKey(segs[editingPos]!))!;

        const topNoPin = topSpacerValue(cum, startIdx, -1, segs, rowKey, heights, 140);
        const topWithPin = topSpacerValue(cum, startIdx, editingPos, segs, rowKey, heights, 140);
        expect(topWithPin).toBe(topNoPin - pinnedH);
    });

    it('pinned editing row below the window is excluded from bottom spacer', () => {
        const segs = makeSegs(100);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        const startIdx = 40;
        const endIdx = 60;
        const editingPos = 90; // below window, pinned
        const pinnedH = heights.get(rowKey(segs[editingPos]!))!;

        const botNoPin = bottomSpacerValue(cum, endIdx, segs.length, -1, segs, rowKey, heights, 140);
        const botWithPin = bottomSpacerValue(cum, endIdx, segs.length, editingPos, segs, rowKey, heights, 140);
        expect(botWithPin).toBe(botNoPin - pinnedH);
    });

    it('pinned row inside the window does not affect either spacer', () => {
        const segs = makeSegs(100);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        const startIdx = 40;
        const endIdx = 60;
        const editingPos = 50; // inside window

        const topPlain = topSpacerValue(cum, startIdx, -1, segs, rowKey, heights, 140);
        const topPinned = topSpacerValue(cum, startIdx, editingPos, segs, rowKey, heights, 140);
        expect(topPinned).toBe(topPlain);

        const botPlain = bottomSpacerValue(cum, endIdx, segs.length, -1, segs, rowKey, heights, 140);
        const botPinned = bottomSpacerValue(cum, endIdx, segs.length, editingPos, segs, rowKey, heights, 140);
        expect(botPinned).toBe(botPlain);
    });
});

describe('SegmentsList virtualization — degenerate cases', () => {
    it('empty list produces a length-1 prefix sum with total 0', () => {
        const cum = rebuildCumHeights<FakeSeg>([], rowKey, new Map(), 140);
        expect(cum).toEqual([0]);
        expect(findIdxAtOffset(cum, 0)).toBe(0);
        expect(findIdxAtOffset(cum, 9999)).toBe(0);
    });

    it('single-row list places the only row at offset 0', () => {
        const segs = makeSegs(1);
        const heights = makeHeights(segs);
        const cum = rebuildCumHeights(segs, rowKey, heights, 140);
        expect(cum[0]).toBe(0);
        expect(cum[1]).toBe(300); // index 0 is a "tall" row per makeHeights
    });
});
