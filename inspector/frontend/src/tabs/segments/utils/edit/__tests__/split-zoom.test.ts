import { describe, expect, it } from 'vitest';

import {
    SPLIT_ZOOM_ANIMATE_MAX_MS,
    SPLIT_ZOOM_ANIMATE_MIN_MS,
} from '../../constants';
import { computeRegionView, computeSweepDurationMs } from '../split-zoom';

// ---- computeRegionView (pure math) ------------------------------------------

describe('computeRegionView', () => {
    it('pads an interior region by 25% of its duration on each side', () => {
        // seg [0, 10000], region [4000, 5000] (dur 1000) → pad 250 → [3750, 5250].
        expect(computeRegionView(4000, 5000, 0, 10000)).toEqual({ viewStart: 3750, viewEnd: 5250 });
    });

    it('clamps the left side to the segment start, keeping full right padding', () => {
        // First region [0, 1000] in seg [0, 10000] → viewStart clamps to 0, right keeps 250.
        expect(computeRegionView(0, 1000, 0, 10000)).toEqual({ viewStart: 0, viewEnd: 1250 });
    });

    it('clamps the right side to the segment end, keeping full left padding', () => {
        // Last region [9000, 10000] in seg [0, 10000] → viewEnd clamps to 10000, left keeps 250.
        expect(computeRegionView(9000, 10000, 0, 10000)).toEqual({ viewStart: 8750, viewEnd: 10000 });
    });

    it('honors a non-zero segment start', () => {
        // seg [2000, 12000], region [6000, 7000] → pad 250 → [5750, 7250].
        expect(computeRegionView(6000, 7000, 2000, 12000)).toEqual({ viewStart: 5750, viewEnd: 7250 });
    });

    it('returns the full segment when the padded window spans (nearly) all of it', () => {
        // Region almost as wide as the segment → padding clamps both sides → full view.
        expect(computeRegionView(100, 9900, 0, 10000)).toEqual({ viewStart: 0, viewEnd: 10000 });
    });

    it('returns the full segment for a degenerate region', () => {
        expect(computeRegionView(5000, 5000, 0, 10000)).toEqual({ viewStart: 0, viewEnd: 10000 });
        expect(computeRegionView(6000, 5000, 0, 10000)).toEqual({ viewStart: 0, viewEnd: 10000 });
    });
});

// ---- computeSweepDurationMs (pure math) -------------------------------------

describe('computeSweepDurationMs', () => {
    it('floors at MIN when the two windows share a center', () => {
        const w = { viewStart: 1000, viewEnd: 3000 }; // center 2000
        expect(computeSweepDurationMs(w, w)).toBe(SPLIT_ZOOM_ANIMATE_MIN_MS);
    });

    it('scales linearly with center distance in the mid range', () => {
        // centers 1000 and 10000 → 9s apart → 180 + 9*35 = 495.
        const from = { viewStart: 0, viewEnd: 2000 };
        const to = { viewStart: 9000, viewEnd: 11000 };
        expect(computeSweepDurationMs(from, to)).toBe(495);
    });

    it('caps at MAX for very long jumps', () => {
        const from = { viewStart: 0, viewEnd: 0 };
        const to = { viewStart: 100000, viewEnd: 100000 }; // 100s away
        expect(computeSweepDurationMs(from, to)).toBe(SPLIT_ZOOM_ANIMATE_MAX_MS);
    });
});
