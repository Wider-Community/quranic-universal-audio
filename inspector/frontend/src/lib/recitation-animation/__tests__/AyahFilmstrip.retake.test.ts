import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    assembleVerseFromShard,
    chapterOccasionIntervals,
    chapterVerseRefs,
    type TsReciterAudio,
} from '../../recitation-data/ts-source';
import shard102 from '../../recitation-data/__tests__/fixtures/nasser_al_qatami_mp3quran_102.shard.json';
import type { TsShardResponse } from '../../types/ts-client';
import AyahFilmstrip from '../AyahFilmstrip.svelte';
import {
    buildChapterRecitation,
    type AssembledVerse,
} from '../chapter-words';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';

/**
 * Component-level #143 regression with REAL data: the dashboard / Timestamps
 * recited filmstrip must NOT freeze (latch `silent`) while the chapter audio
 * plays a DISCARDED re-take. The active cell must travel to the re-recited
 * verse's cell and re-light it.
 *
 * Built through the real assembly pipeline against the published nasser_al_qatami
 * chapter-102 shard (every verse re-recited 2-3×). The discarded take of 102:7
 * spans audio ~[86.2, 93.0]s with NO canonical data — the frozen window.
 */

const RECITER = 'nasser_al_qatami_mp3quran';
const RECITER_AUDIO: TsReciterAudio = { audio_category: 'by_surah' };
const EMPTY: Record<string, { text?: string }> = {};

function buildUnits(): ReturnType<typeof buildChapterRecitation>['units'] {
    const shard = shard102 as unknown as TsShardResponse;
    const verses: AssembledVerse[] = [];
    for (const ref of chapterVerseRefs(shard)) {
        const data = assembleVerseFromShard(RECITER, shard, ref, EMPTY, EMPTY, RECITER_AUDIO, '');
        if (data) verses.push({ verseRef: ref, data });
    }
    return buildChapterRecitation(RECITER, 102, verses, chapterOccasionIntervals(shard)).units;
}

function activeCellAyah(container: HTMLElement): number | null {
    const el = container.querySelector<HTMLElement>('.cell.active .cell-num');
    return el ? Number(el.textContent) : null;
}
function frozenCellAyah(container: HTMLElement): number | null {
    const el = container.querySelector<HTMLElement>('.cell.frozen .cell-num');
    return el ? Number(el.textContent) : null;
}

describe('AyahFilmstrip re-take coverage (real nasser_al_qatami 102)', () => {
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

    it('travels the active cell into verse 7 during its discarded re-take, never frozen', async () => {
        const units = buildUnits();
        const model = buildFilmstripModel(units, 'duration');
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 104_000, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        // Play through to verse 8's canonical take (75.86-85.86s), so the active
        // cell is on verse 8 — past verse 7's canonical start.
        for (const ms of [52_000, 60_000, 70_000, 78_000, 84_000]) await step(ms);
        expect(activeCellAyah(container)).toBe(8);

        // Audio re-enters verse 7's THIRD occasion (the discarded re-take at
        // ~86.2-93.0s). Pre-fix this window had no canonical data → silent freeze.
        // Now the active cell must travel BACK to verse 7 and stay lit.
        for (const ms of [87_000, 89_000, 91_000]) await step(ms);
        expect(frozenCellAyah(container)).toBeNull(); // not latched silent
        expect(activeCellAyah(container)).toBe(7);
    });

    it('freezes (goes silent) only in a genuine inter-take silence, not a re-take', async () => {
        const units = buildUnits();
        const model = buildFilmstripModel(units, 'duration');
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: 104_000, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: 'hybrid' },
            onSeek: () => {},
        });
        await tick();

        // Get the strip active first.
        for (const ms of [52_000, 60_000]) await step(ms);
        // 59.05-59.875s is a real inter-segment silence (verse 7 canonical end →
        // verse 6 re-take start). Land squarely in it.
        await step(59_400);
        expect(activeCellAyah(container)).toBeNull(); // silence freeze is preserved
        expect(frozenCellAyah(container)).not.toBeNull();
    });
});
