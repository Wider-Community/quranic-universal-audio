import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { describe, expect, it } from 'vitest';

import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/** Synthetic unit; the last interval optionally carries the waṣl flag. */
function unitW(
    location: string,
    intervals: Array<[number, number]>,
    wasl?: { to: string },
): AnimUnit {
    const [s, a, w] = location.split(':');
    const spans: TimeSpan[] = intervals.map(([start, end]) => ({ start, end }));
    if (wasl && spans.length) {
        spans[spans.length - 1]!.waslTo = wasl.to;
    }
    return {
        location, ayahKey: `${s}:${a}`, surah: Number(s), ayah: Number(a), word: Number(w),
        text: location, start: spans[0]!.start, end: spans[spans.length - 1]!.end,
        intervals: spans, letters: [],
    };
}

const marginRight = (el: Element): number => parseFloat((el as HTMLElement).style.marginRight) || 0;
const getTimeMs = (): number => 0;

describe('AyahFilmstrip — waṣl merge', () => {
    it('renders a bridge gapless with full-bordered sub-cells + an accent rail', async () => {
        // 1:1 (waṣl»1:2), then 1:2 — any-take-bridges → permanently merged.
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
        // The left member of a bridge is gapless (margin collapsed to 0).
        expect(marginRight(cells[0]!)).toBe(0);
        // Sub-cells keep their own full borders + verse numbers — the rail carries
        // the "merged" read, not a corner-squaring weld or a range label.
        const nums = [...container.querySelectorAll('.cell .cell-num')].map((e) => e.textContent);
        expect(nums).toContain('1');
        expect(nums).toContain('2');
        // One accent rail spans the gapless group; no connector/range label.
        expect(container.querySelector('.wasl-link')).toBeNull();
        expect(container.querySelector('.wasl-range')).toBeNull();
        expect(container.querySelectorAll('.wasl-rail').length).toBe(1);
    });

    it('lays a merged short verse time-true (no min-width floor) so the group keeps constant velocity', async () => {
        const px = DEFAULT_RECITATION_CONFIG.filmstripPxPerSec;
        const minPx = DEFAULT_RECITATION_CONFIG.filmstripMinCellPx;
        // 1:1 (0.5s) waṣl»1:2 (0.5s) contiguous → merged group; 1:3 (0.5s) is a
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
});
