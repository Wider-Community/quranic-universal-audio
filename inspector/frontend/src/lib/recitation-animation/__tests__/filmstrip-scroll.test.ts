import { describe, expect, it } from 'vitest';

import { createStripScroller, GLIDE_MIN_MS, type StripScroller } from '../filmstrip-scroll.svelte';

/**
 * Unit tests for the unified strip-scroll controller. A manual clock + single-
 * slot rAF lets each eased frame be stepped deterministically: `advance(ms)`
 * moves the clock, `drain()` runs the controller's one pending rAF (one `tick`).
 * Continuous-mode catch-up is driven the way the component drives it — `follow`
 * is called each frame (the "component loop") and then the controller's rAF is
 * drained (the per-frame advance).
 */
interface Harness {
    scroller: StripScroller;
    advance(_ms: number): void;
    drain(): void;
    setReduced(_v: boolean): void;
}

function makeHarness(lastRight = 1000): Harness {
    let clock = 0;
    let reduced = false;
    let pending: ((_t: number) => void) | null = null;
    const scroller = createStripScroller({
        get lastRight() { return lastRight; },
        get reducedMotion() { return reduced; },
        now: () => clock,
        raf: (cb) => { pending = cb; return 1; },
        caf: () => { pending = null; },
    });
    return {
        scroller,
        advance: (ms) => { clock += ms; },
        drain: () => { const cb = pending; pending = null; if (cb) cb(clock); },
        setReduced: (v) => { reduced = v; },
    };
}

const FRAME = 16; // ms per simulated frame

describe('StripScroller forward tracking (continuous follow)', () => {
    it('locks the offset exactly on the live target during forward play', () => {
        const h = makeHarness();
        h.scroller.follow(137, false);
        expect(h.scroller.offset).toBe(137);
        expect(h.scroller.animating).toBe(false);
    });

    it('stays frame-locked across consecutive forward frames (never lags)', () => {
        const h = makeHarness();
        for (const target of [10, 22, 35, 49]) {
            h.advance(FRAME);
            h.scroller.follow(target, false);
            expect(h.scroller.offset).toBe(target);
        }
    });
});

describe('StripScroller eased glide (fixed target)', () => {
    it('eases IN — a big jump barely moves on the first frame (no lurch)', () => {
        // The old exponential catch-up leapt ~28% of the gap on frame 1
        // (0.28·400 ≈ 112px). A Hermite glide from rest starts near-zero.
        const h = makeHarness();
        h.scroller.snap(500);
        h.scroller.glide(100); // 400px jump back
        h.advance(FRAME);
        h.drain();
        const movedFrame1 = Math.abs(500 - h.scroller.offset);
        expect(movedFrame1).toBeGreaterThan(0); // not frozen
        expect(movedFrame1).toBeLessThan(20); // soft start, not a lurch
    });

    it('advances monotonically and lands exactly on the target', () => {
        const h = makeHarness();
        h.scroller.snap(0);
        h.scroller.glide(300);
        let prev = h.scroller.offset;
        let frames = 0;
        while (h.scroller.animating && frames < 200) {
            h.advance(FRAME);
            h.drain();
            expect(h.scroller.offset).toBeGreaterThanOrEqual(prev - 1e-6); // never reverses
            prev = h.scroller.offset;
            frames++;
        }
        expect(h.scroller.offset).toBe(300);
        expect(h.scroller.animating).toBe(false);
    });
});

describe('StripScroller loopback catch-up (continuous follow)', () => {
    it('eases toward the looped verse instead of teleporting', () => {
        const h = makeHarness();
        h.scroller.snap(500);
        h.scroller.follow(100, true); // discontinuity: target is an earlier verse
        expect(h.scroller.animating).toBe(true);
        h.advance(FRAME);
        h.drain();
        expect(h.scroller.offset).toBeLessThan(500); // moved toward the loop
        expect(h.scroller.offset).toBeGreaterThan(100); // but eased, not snapped
    });

    it('lands ON a moving target during replay — zero residual lag', () => {
        const h = makeHarness();
        h.scroller.snap(500);
        let live = 100;
        h.scroller.follow(live, true); // arm at snapshot 100
        for (let i = 0; i < 60 && h.scroller.animating; i++) {
            h.advance(FRAME);
            live += 4; // the replayed verse keeps advancing ~4px/frame
            h.scroller.follow(live, false); // component loop re-targets live
            h.drain(); // controller advances + maybe lands
        }
        expect(h.scroller.animating).toBe(false);
        expect(h.scroller.offset).toBe(live); // sitting exactly on the live word
    });

    it('moves every frame during the catch-up (never frozen)', () => {
        const h = makeHarness();
        h.scroller.snap(500);
        let live = 100;
        h.scroller.follow(live, true);
        let prev = h.scroller.offset;
        for (let i = 0; i < 4; i++) {
            h.advance(FRAME);
            live += 4;
            h.scroller.follow(live, false);
            h.drain();
            expect(h.scroller.offset).not.toBe(prev);
            prev = h.scroller.offset;
        }
    });

    it('re-plans without a velocity spike — consecutive frame deltas stay smooth', () => {
        // A re-plan toward a moving target carries the current velocity (C1), so
        // per-frame movement changes gradually — no single frame jumps far more
        // than its neighbours (the old "matches the previous cutoff" artefact).
        const h = makeHarness();
        h.scroller.snap(600);
        let live = 100;
        h.scroller.follow(live, true);
        const deltas: number[] = [];
        let prev = h.scroller.offset;
        for (let i = 0; i < 20 && h.scroller.animating; i++) {
            h.advance(FRAME);
            live += 6;
            h.scroller.follow(live, false);
            h.drain();
            deltas.push(Math.abs(h.scroller.offset - prev));
            prev = h.scroller.offset;
        }
        // No frame moves more than ~3× the previous frame's distance: smooth,
        // not a lurch-then-crawl.
        for (let i = 1; i < deltas.length; i++) {
            if (deltas[i - 1]! > 0.5) {
                expect(deltas[i]!).toBeLessThan(deltas[i - 1]! * 3 + 1);
            }
        }
    });
});

describe('StripScroller in-flight glide vs forward follow', () => {
    it('does not hard-snap over an in-flight glide when a forward follow targets it', () => {
        // The paused → verse-click → resume case: a fixed glide is mid-flight to
        // the clicked cell, then a forward (non-discont) follow frame arrives whose
        // live target IS that cell. The instant path must NOT slam offset onto the
        // target (a teleport that also frame-fights the still-ticking plan) — the
        // glide must keep easing.
        const h = makeHarness();
        h.scroller.snap(0);
        h.scroller.glide(300); // fixed glide to the clicked cell
        h.advance(FRAME);
        h.drain();
        const mid = h.scroller.offset;
        expect(mid).toBeLessThan(60); // barely started
        h.scroller.follow(300, false); // resume frame: live target == glide dest
        expect(h.scroller.offset).toBeLessThan(300 - 5); // did NOT teleport to 300
        expect(h.scroller.animating).toBe(true); // glide still in flight
        // …and it still lands smoothly.
        for (let i = 0; i < 200 && h.scroller.animating; i++) { h.advance(FRAME); h.drain(); }
        expect(h.scroller.offset).toBe(300);
    });
});

describe('StripScroller reduced motion + clamping', () => {
    it('applies targets instantly under reduced motion (no glide)', () => {
        const h = makeHarness();
        h.setReduced(true);
        h.scroller.snap(500);
        h.scroller.glide(100);
        expect(h.scroller.offset).toBe(100);
        expect(h.scroller.animating).toBe(false);
        h.scroller.follow(300, true);
        expect(h.scroller.offset).toBe(300);
        expect(h.scroller.animating).toBe(false);
    });

    it('clamps every target into [0, lastRight]', () => {
        const h = makeHarness(250);
        h.scroller.snap(1e6);
        expect(h.scroller.offset).toBe(250);
        h.scroller.snap(-50);
        expect(h.scroller.offset).toBe(0);
    });

    it('stops animating after cancel', () => {
        const h = makeHarness();
        h.scroller.snap(500);
        h.scroller.glide(100);
        expect(h.scroller.animating).toBe(true);
        h.scroller.cancel();
        expect(h.scroller.animating).toBe(false);
    });
});

// GLIDE_MIN_MS is re-exported for the component's fill-glide; keep it referenced
// so a removal surfaces here too.
describe('shared glide constants', () => {
    it('exposes a positive minimum glide duration', () => {
        expect(GLIDE_MIN_MS).toBeGreaterThan(0);
    });
});
