import { describe, expect, it } from 'vitest';

import { GLIDE_FOLLOW, type ScrollState, stepScroll } from '../filmstrip-scroll';

/** Seed for the arm frame (no prior catch-up target). */
const armed = (offset: number): ScrollState => ({ offset, following: false, prevTarget: 0 });

describe('stepScroll forward tracking', () => {
    it('tracks the live target instantly when not in a catch-up', () => {
        // No discontinuity, not following → the needle sits exactly on the target
        // (scroll, fill and audio stay locked). This is the per-frame forward case.
        const s = stepScroll(100, 137, false, false, 0, 1000, false);
        expect(s.offset).toBe(137);
        expect(s.following).toBe(false);
    });

    it('keeps tracking instantly across consecutive forward frames', () => {
        let st = armed(0);
        for (const target of [10, 22, 35, 49]) {
            st = stepScroll(st.offset, target, false, false, st.prevTarget, 1000, false);
            expect(st.offset).toBe(target); // never lags the live position
        }
    });
});

describe('stepScroll loopback catch-up', () => {
    it('eases toward the target on a discontinuity instead of jumping', () => {
        // Loopback: target is BEHIND the current offset (an earlier verse). One
        // frame closes GLIDE_FOLLOW of the gap — a smooth rewind, not a teleport.
        const s = stepScroll(500, 100, true, false, 0, 1000, false);
        expect(s.following).toBe(true);
        expect(s.offset).toBeCloseTo(500 + (100 - 500) * GLIDE_FOLLOW, 6);
        expect(s.offset).toBeLessThan(500); // moved toward the looped verse
        expect(s.offset).toBeGreaterThan(100); // but eased, not snapped
    });

    it('lands ON a MOVING target during replay — converges to zero lag', () => {
        // After the loopback the recited word keeps advancing. A fixed-fraction
        // smoothing toward a moving target would settle at a CONSTANT lag and never
        // land; the velocity-aware landing must close that lag to zero and hand
        // back to instant tracking so the strip sits exactly on the replayed word.
        let st = stepScroll(500, 100, true, false, 0, 1000, false); // arm at snapshot 100
        let liveTarget = 100;
        for (let i = 0; i < 30; i++) {
            liveTarget += 4; // verse replays forward, ~4px/frame
            st = stepScroll(st.offset, liveTarget, false, st.following, st.prevTarget, 1000, false);
        }
        // Converged exactly onto the live position, NOT trailing by a fixed lag.
        expect(st.following).toBe(false);
        expect(st.offset).toBe(liveTarget);
    });

    it('moves every frame during the catch-up (never frozen)', () => {
        let st = stepScroll(500, 100, true, false, 0, 1000, false);
        let liveTarget = 100;
        let prev = st.offset;
        // Sample the catch-up transient (before it lands): each frame must move.
        for (let i = 0; i < 4; i++) {
            liveTarget += 4;
            st = stepScroll(st.offset, liveTarget, false, st.following, st.prevTarget, 1000, false);
            expect(st.offset).not.toBe(prev);
            prev = st.offset;
        }
    });

    it('lands and resumes instant tracking once within snap distance', () => {
        // Static target (velocity 0): land at the base SNAP_EPS_PX.
        const s = stepScroll(100.4, 100, false, true, 100, 1000, false);
        expect(s.offset).toBe(100);
        expect(s.following).toBe(false);
    });

    it('jumps straight to the target under reduced motion', () => {
        const s = stepScroll(500, 100, true, false, 0, 1000, true);
        expect(s.offset).toBe(100);
        expect(s.following).toBe(false);
    });

    it('clamps the target into [0, lastRight]', () => {
        expect(stepScroll(0, 1e6, false, false, 0, 250, false).offset).toBe(250);
        expect(stepScroll(0, -50, false, false, 0, 250, false).offset).toBe(0);
    });
});
