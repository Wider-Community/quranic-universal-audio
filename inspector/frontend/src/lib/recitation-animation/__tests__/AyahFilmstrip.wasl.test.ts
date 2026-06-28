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

    it('renders a STATIC bridge gapless with full-bordered sub-cells + an accent rail', async () => {
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
        // Sub-cells keep their own full borders + verse numbers — the rail carries
        // the "merged" read, not a corner-squaring weld or a range label.
        expect(cells[0]!.classList.contains('merge-r')).toBe(false);
        expect(cells[1]!.classList.contains('merge-l')).toBe(false);
        const nums = [...container.querySelectorAll('.cell .cell-num')].map((e) => e.textContent);
        expect(nums).toContain('1');
        expect(nums).toContain('2');
        // One accent rail spans the gapless group; the old connector/range are gone.
        expect(container.querySelector('.wasl-link')).toBeNull();
        expect(container.querySelector('.wasl-range')).toBeNull();
        const rails = container.querySelectorAll<HTMLElement>('.wasl-rail');
        expect(rails.length).toBe(1);
        // Static merge → rail fully opaque.
        expect(parseFloat(rails[0]!.style.opacity || '1')).toBeCloseTo(1);
    });

    it('lays a merged short verse time-true (no min-width floor) so the capsule keeps constant velocity', async () => {
        const px = DEFAULT_RECITATION_CONFIG.filmstripPxPerSec;
        const minPx = DEFAULT_RECITATION_CONFIG.filmstripMinCellPx;
        // 1:1 (0.5s) waṣl»1:2 (0.5s) contiguous → static capsule; 1:3 (0.5s) is a
        // solo short verse after a gap. 0.5s × pxPerSec is below minCellPx, so a
        // SOLO short cell floors for legibility but a MERGED member stays time-true
        // (w === aw) — no floor surplus to jerk the cursor at the gapless seam.
        const units = [
            unitW('1:1:1', [[0, 0.5]], { to: '1:2' }),
            unitW('1:2:1', [[0.5, 1.0]]),
            unitW('1:3:1', [[6, 6.5]]),
        ];
        const model = buildFilmstripModel(units, 'duration');
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 7000, getTimeMs, playing: false,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        const cells = container.querySelectorAll<HTMLElement>('.cell');
        const width = (el: HTMLElement): number => parseFloat(el.style.width) || 0;
        const aw = Math.round(0.5 * px);
        expect(aw).toBeLessThan(minPx); // precondition: short enough to floor when solo
        expect(width(cells[0]!)).toBe(aw); // merged left member — time-true
        expect(width(cells[1]!)).toBe(aw); // merged right member — time-true
        expect(width(cells[2]!)).toBe(minPx); // solo short verse — still floored
    });

    it('animates a DYNAMIC bridge closed as the bridging take plays + ramps the rail in', async () => {
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
        // Before the bridging take plays, the dynamic pair sits separated (gap > 0)
        // and is not yet a group → no rail.
        await step(100); // inside 1:1:1, not yet the bridging word
        const gapSeparated = marginRight(leftCell());
        expect(gapSeparated).toBeGreaterThan(8);
        expect(container.querySelector('.wasl-rail')).toBeNull();

        // Play the bridging last word (1:1:2 spans 1–2s) over several frames; the
        // gap eases closed and the rail appears + strengthens (opacity ramps up).
        for (const ms of [1200, 1400, 1600, 1800]) await step(ms);
        expect(marginRight(leftCell())).toBeLessThan(gapSeparated * 0.6);
        const rail = container.querySelector<HTMLElement>('.wasl-rail');
        expect(rail).not.toBeNull();
        expect(parseFloat(rail!.style.opacity || '0')).toBeGreaterThan(0);
        expect(container.querySelector('.wasl-range')).toBeNull();
    });
});
