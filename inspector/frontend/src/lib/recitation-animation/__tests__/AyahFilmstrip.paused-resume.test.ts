import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';
import Harness from './_PausedResumeHarness.svelte';

/**
 * Integration guard for the paused → verse-click → resume teleport.
 *
 * Clicking a verse (or teleprompter line) while paused makes the parent call
 * `dashPort.play()` AND `filmstrip.refresh()`. `refresh()` starts a fixed glide
 * to the clicked cell and PRE-SETS `activeIdx`/`cellFrac` to that cell. When
 * playback then resumes, the driver resets `lastTimeMs` (so `seeked = false`)
 * and `isJump` sees `prevIdx === r.idx` (so no loopback) — net `discont = false`.
 * The continuous (hybrid/tuner) branch then calls `scroll.follow(target, false)`,
 * whose instant path must NOT hard-snap over the in-flight glide — otherwise the
 * strip teleports/jitters instead of easing into place.
 *
 * This exercises the `drivePlayback → follow` resume interaction that the
 * controller's isolated unit tests can't reach.
 */

function unit(loc: string, ivs: Array<[number, number]>): AnimUnit {
    const [s, a, w] = loc.split(':').map(Number);
    const spans: TimeSpan[] = ivs.map(([st, en]) => ({ start: st, end: en }));
    return {
        location: loc, ayahKey: `${s}:${a}`, surah: s!, ayah: a!, word: w!, text: loc,
        start: spans[0]!.start, end: spans[spans.length - 1]!.end, intervals: spans, letters: [],
    };
}

// 6 verses, 2 words each, 1s/word, played straight through — so verse 6 is a
// long scroll from the strip's start position.
const units: AnimUnit[] = [];
for (let v = 1; v <= 6; v++) {
    for (let w = 1; w <= 2; w++) {
        const start = (v - 1) * 2 + (w - 1);
        units.push(unit(`1:${v}:${w}`, [[start, start + 1]]));
    }
}
const model = buildFilmstripModel(units, 'duration');

/** Current strip scroll offset (px) — the negated track translateX. */
function scrollOffset(container: HTMLElement): number {
    const el = container.querySelector<HTMLElement>('.track');
    const m = el ? /translateX\((-?[\d.]+)px\)/.exec(el.style.transform) : null;
    return m ? -parseFloat(m[1]!) : 0;
}

describe('AyahFilmstrip paused → resume (continuous modes)', () => {
    let rafCbs: FrameRequestCallback[] = [];
    let nowMs = 0;
    const getTimeMs = (): number => nowMs;

    beforeEach(() => {
        rafCbs = [];
        vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback): number => {
            rafCbs.push(cb);
            return rafCbs.length;
        });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        vi.spyOn(performance, 'now').mockImplementation(() => nowMs);
        // jsdom reports clientWidth 0, which makes the filmstrip's `refresh()`
        // early-return (`if (cw === 0)`) — give it a real width so the paused
        // refresh→glide path under test actually runs.
        Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 800 });
        vi.stubGlobal('ResizeObserver', class {
            #cb: ResizeObserverCallback;
            constructor(cb: ResizeObserverCallback) { this.#cb = cb; }
            observe(el: Element): void { this.#cb([{ target: el } as ResizeObserverEntry], this); }
            unobserve(): void {}
            disconnect(): void {}
        });
    });
    afterEach(() => {
        delete (HTMLElement.prototype as unknown as { clientWidth?: number }).clientWidth;
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    async function pump(toMs: number): Promise<void> {
        nowMs = toMs;
        for (let i = 0; i < 2 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    for (const motion of ['hybrid', 'tuner'] as const) {
        it(`eases (never teleports) when a paused verse-click resumes — ${motion}`, async () => {
            const { container, component } = render(Harness, {
                inner: {
                    units, model, durationMs: 12_000, getTimeMs,
                    config: { ...DEFAULT_RECITATION_CONFIG, filmstripMotion: motion },
                    onSeek: () => {},
                },
            });
            const harness = component as unknown as {
                refresh: () => void;
                setPlaying: (_v: boolean) => void;
            };
            await tick();

            // Paused at the strip start. "Click verse 6": the parent seeks the
            // audio to verse 6 and (because paused) calls refresh() — which starts
            // a glide to that cell and pre-sets the active cell.
            nowMs = 10_500; // verse 6, word 1 (interval [10, 11]s)
            harness.refresh();
            await tick();

            // Sample every frame; resume playback a few frames in (the parent's
            // dashPort.play() flips `playing` on the SAME instance). Advancing time
            // stays inside verse 6, so the resume frame has no real discontinuity —
            // the exact teleport case.
            const deltas: number[] = [];
            let prev = scrollOffset(container);
            for (let f = 0; f < 40; f++) {
                if (f === 3) { harness.setPlaying(true); await tick(); }
                await pump(10_500 + f * 16);
                const o = scrollOffset(container);
                deltas.push(Math.abs(o - prev));
                prev = o;
            }

            const total = Math.abs(scrollOffset(container)); // landed at verse 6
            const maxDelta = Math.max(...deltas);
            expect(total).toBeGreaterThan(20); // it really did travel to verse 6
            // No single frame jumps more than half the whole glide — i.e. it eased
            // the whole way instead of teleporting on the resume frame.
            expect(maxDelta).toBeLessThan(total * 0.5);
        });
    }
});
