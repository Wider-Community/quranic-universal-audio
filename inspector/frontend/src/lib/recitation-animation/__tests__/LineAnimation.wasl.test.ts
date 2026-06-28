import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_RECITATION_CONFIG } from '../config';
import LineAnimation from '../LineAnimation.svelte';
import type { AnimUnit } from '../types';

const cfg = {
    ...DEFAULT_RECITATION_CONFIG,
    granularity: 'word' as const,
    clearOnAyahEnd: true,
    clearOnOverflow: false,
    showAyahMarker: true,
    leadMs: 0,
};

/** A one-word-per-unit verse; the unit's interval carries `waslTo` when the
 *  verse bridges into the next. happy-dom's zero-size rects make every word
 *  "fit" one page, so the rendered `.ra-word` count == the paged unit count. */
function unit(location: string, start: number, end: number, waslTo?: string): AnimUnit {
    const [s, a, w] = location.split(':');
    const span = waslTo ? { start, end, waslTo } : { start, end };
    return {
        location, ayahKey: `${s}:${a}`, surah: Number(s), ayah: Number(a), word: Number(w),
        text: location, start, end, intervals: [span], letters: [{ char: 'x', start, end }],
    };
}

describe('LineAnimation — waṣl chaining', () => {
    it('chains the line across a waṣl boundary (both verses on one page)', async () => {
        const units = [
            unit('1:1:1', 0, 1),
            unit('1:1:2', 1, 2, '1:2'), // verse 1 bridges into verse 2
            unit('1:2:1', 2, 3),
            unit('1:2:2', 3, 4),
        ];
        const { container } = render(LineAnimation, {
            units, config: cfg, getTimeMs: () => 0, playing: false,
        });
        await tick();
        expect(container.querySelectorAll('.ra-word').length).toBe(4);
        // The verse-1 ۝ marker renders inline mid-chain.
        expect(container.querySelector('.ra-ayah-marker[data-after-word="1"]')).not.toBeNull();
    });

    it('clears at a non-bridging verse end (only the first verse on the page)', async () => {
        const units = [
            unit('1:1:1', 0, 1),
            unit('1:1:2', 1, 2), // no waslTo → stop
            unit('1:2:1', 2, 3),
            unit('1:2:2', 3, 4),
        ];
        const { container } = render(LineAnimation, {
            units, config: cfg, getTimeMs: () => 0, playing: false,
        });
        await tick();
        expect(container.querySelectorAll('.ra-word').length).toBe(2);
    });

    it('extends across a 3-verse chain', async () => {
        const units = [
            unit('1:1:1', 0, 1, '1:2'),
            unit('1:2:1', 1, 2, '1:3'),
            unit('1:3:1', 2, 3),
        ];
        const { container } = render(LineAnimation, {
            units, config: cfg, getTimeMs: () => 0, playing: false,
        });
        await tick();
        expect(container.querySelectorAll('.ra-word').length).toBe(3);
    });
});

describe('LineAnimation — waqf marker color', () => {
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
    });
    afterEach(() => vi.unstubAllGlobals());

    async function step(toMs: number): Promise<void> {
        nowMs = toMs;
        for (let i = 0; i < 2 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    it('lights the ۝ marker on a waqf stop at a non-bridging verse end', async () => {
        const units = [
            unit('1:1:1', 0, 1),
            unit('1:1:2', 1, 2), // verse 1 ends at t=2, no bridge
            unit('1:2:1', 3, 4), // verse 2 starts at t=3 → silence 2..3
            unit('1:2:2', 4, 5),
        ];
        const { container } = render(LineAnimation, {
            units, config: cfg, getTimeMs, playing: true,
        });
        await tick();
        await step(1500); // word 1:1:2 active → lastActive set
        await step(2500); // pause holds at verse 1's end
        const marker = container.querySelector('.ra-ayah-marker[data-after-word="1"]');
        expect(marker?.classList.contains('marker-pause')).toBe(true);
    });

    it('never lights the marker at a bridged boundary', async () => {
        const units = [
            unit('1:1:1', 0, 1),
            unit('1:1:2', 1, 2, '1:2'), // bridges into verse 2
            unit('1:2:1', 3, 4), // forced gap to isolate the bridgesNext guard
            unit('1:2:2', 4, 5),
        ];
        const { container } = render(LineAnimation, {
            units, config: cfg, getTimeMs, playing: true,
        });
        await tick();
        await step(1500); // word 1:1:2 active
        await step(2500); // a gap after verse 1 — but it bridges, so no stop
        const marker = container.querySelector('.ra-ayah-marker[data-after-word="1"]');
        expect(marker?.classList.contains('marker-pause')).toBe(false);
    });
});
