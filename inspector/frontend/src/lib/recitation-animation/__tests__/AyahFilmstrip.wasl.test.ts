import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/** Synthetic unit; the last interval optionally carries the waṣl flag. */
function unitW(
    location: string,
    intervals: Array<[number, number]>,
    wasl?: { to: string; dynamic?: boolean },
): AnimUnit {
    const [s, a, w] = location.split(':');
    const spans: TimeSpan[] = intervals.map(([start, end]) => ({ start, end }));
    if (wasl && spans.length) {
        spans[spans.length - 1]!.waslTo = wasl.to;
        spans[spans.length - 1]!.waslDynamic = wasl.dynamic ?? false;
    }
    return {
        location, ayahKey: `${s}:${a}`, surah: Number(s), ayah: Number(a), word: Number(w),
        text: location, start: spans[0]!.start, end: spans[spans.length - 1]!.end,
        intervals: spans, letters: [],
    };
}

const marginRight = (el: Element): number => parseFloat((el as HTMLElement).style.marginRight) || 0;

describe('AyahFilmstrip — waṣl merge', () => {
    let rafCbs: FrameRequestCallback[] = [];
    let nowMs = 0;
    const getTimeMs = (): number => nowMs;

    beforeEach(() => {
        rafCbs = [];
        nowMs = 0;
        vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback): number => {
            rafCbs.push(cb);
            return rafCbs.length;
        });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        vi.spyOn(performance, 'now').mockImplementation(() => nowMs);
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    async function step(toMs: number): Promise<void> {
        nowMs = toMs;
        for (let i = 0; i < 2 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    it('renders a STATIC bridge gapless with a link connector + capsule corners', async () => {
        // 1:1 (waṣl»1:2), then 1:2. Contiguous, never stops → static merge.
        const units = [
            unitW('1:1:1', [[0, 1]]),
            unitW('1:1:2', [[1, 2]], { to: '1:2' }),
            unitW('1:2:1', [[2, 3]]),
            unitW('1:2:2', [[3, 4]]),
        ];
        const model = buildFilmstripModel(units, 'duration');
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 4000, getTimeMs, playing: false,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        const cells = container.querySelectorAll('.cell');
        // The left member of a static bridge is gapless (margin collapsed to 0).
        expect(marginRight(cells[0]!)).toBe(0);
        // Capsule: left member squares its right corners, right member its left.
        expect(cells[0]!.classList.contains('merge-r')).toBe(true);
        expect(cells[1]!.classList.contains('merge-l')).toBe(true);
        // The link connector is rendered (full opacity for a static pair).
        const link = container.querySelector<HTMLElement>('.wasl-link');
        expect(link).not.toBeNull();
        expect(parseFloat(link!.style.opacity || '1')).toBeCloseTo(1, 2);
    });

    it('animates a DYNAMIC bridge closed as the bridging take plays + lights the connector', async () => {
        // 1:1 (waṣl»1:2, DYNAMIC), gap of 2s to 1:2 so the closing gap is visible.
        const units = [
            unitW('1:1:1', [[0, 1]]),
            unitW('1:1:2', [[1, 2]], { to: '1:2', dynamic: true }),
            unitW('1:2:1', [[4, 5]]),
        ];
        const model = buildFilmstripModel(units, 'duration');
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 5000, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        const leftCell = (): Element => container.querySelectorAll('.cell')[0]!;
        // Before the bridging take plays, the dynamic pair sits separated (gap > 0).
        await step(100); // inside 1:1:1, not yet the bridging word
        const gapSeparated = marginRight(leftCell());
        expect(gapSeparated).toBeGreaterThan(8);

        // Play the bridging last word (1:1:2 spans 1–2s) over several frames; the
        // merge eases closed and the connector goes live.
        for (const ms of [1200, 1400, 1600, 1800]) await step(ms);
        expect(marginRight(leftCell())).toBeLessThan(gapSeparated * 0.6);
        expect(container.querySelector('.wasl-link.wasl-live')).not.toBeNull();
    });
});
