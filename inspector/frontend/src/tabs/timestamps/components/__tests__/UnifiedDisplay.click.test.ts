/**
 * UnifiedDisplay click / dblclick tests.
 *
 * Verifies the deferred-click pattern that resolves the known click-vs-
 * dblclick race (see `UnifiedDisplay.svelte`'s onWordClick comment) while
 * still letting a lone single-click swap the loop target — the behavior
 * that fixes the "click on diff word stays on same looped word" bug.
 */
import { cleanup, fireEvent,render } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { makeAudioStub as makePortAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import type { TsVerseData, TsWord } from '../../../../lib/types/domain';
import { loopTarget } from '../../stores/playback';
import type { TsLoadedVerse } from '../../stores/verse';
import { loadedVerse } from '../../stores/verse';
import { TS_CLICK_DELAY_MS } from '../../utils/constants';
import UnifiedDisplay from '../UnifiedDisplay.svelte';

function word(idx: number, start: number, end: number, text = `w${idx}`): TsWord {
    return {
        location: `1:1:${idx + 1}`,
        text,
        display_text: text,
        start,
        end,
        phoneme_indices: [],
        letters: [],
    };
}

function fixture(): TsLoadedVerse {
    const words: TsWord[] = [
        word(0, 1, 2),
        word(1, 3, 4),
        word(2, 5, 6),
    ];
    const data: TsVerseData = {
        reciter: 'r',
        chapter: 1,
        verse_ref: '1:1',
        audio_url: 'http://audio/1.mp3',
        audio_category: 'by_ayah_audio',
        time_start_ms: 0,
        time_end_ms: 10_000,
        intervals: [],
        words,
    };
    return { data, tsSegOffset: 0, tsSegEnd: 10 };
}

/** Minimal stub of HTMLAudioElement that UnifiedDisplay's click path uses.
 *  Reuses the playback-layer test harness so the port's `attachElement`
 *  finds `addEventListener` / `removeEventListener` (it subscribes to
 *  play/pause/timeupdate at attach time). */
function makeAudioStub(): HTMLAudioElement {
    return makePortAudioStub({ src: 'http://audio/1.mp3', readyState: 4 }) as unknown as HTMLAudioElement;
}

/** Bind the SHARED player (`dashPort`) — UnifiedDisplay's click handlers seek
 *  through `dashPort` after the shared-player migration, so the click path
 *  writes `audio.currentTime` via `dashPort.seek`. The port needs a CBR source
 *  so `loadCovering` can resolve and the in-memory window has offsetMs=0. */
function bindAudio(audio: HTMLAudioElement): void {
    dashPort.attachElement(audio);
    dashPort.setSource({ audioUrl: 'http://audio/1.mp3', reciter: null, vbr: false });
    // Synthesize the loaded window so currentTimeMs returns immediately
    // without needing a canplay round-trip in the test fixture.
    const r = dashPort.loadCovering(0, 10_000);
    // The makeAudioStub has _fireEvent for synchronous canplay dispatch.
    (audio as unknown as { _fireEvent: (t: string) => void })._fireEvent('canplay');
    void r.ready;
}

describe('UnifiedDisplay — click / dblclick in loop mode', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        loadedVerse.set(fixture());
        loopTarget.set(null);
        bindAudio(makeAudioStub());
    });

    afterEach(() => {
        cleanup();
        vi.useRealTimers();
        loadedVerse.set(null);
        loopTarget.set(null);
        dashPort.attachElement(null);
    });

    it('single-click on a DIFFERENT word while looped swaps the loop target', () => {
        loopTarget.set({ kind: 'word', wordIndex: 0, startSec: 1, endSec: 2 });
        const { container } = render(UnifiedDisplay);

        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        expect(blocks.length).toBeGreaterThanOrEqual(2);
        // Click word index 1.
        fireEvent.click(blocks[1]!);

        // Single-click is deferred — loop target should NOT have moved yet.
        expect(get(loopTarget)!.wordIndex).toBe(0);

        // After the debounce, loop swaps.
        vi.advanceTimersByTime(TS_CLICK_DELAY_MS + 1);
        const lt = get(loopTarget);
        expect(lt).not.toBeNull();
        expect(lt!.kind).toBe('word');
        expect(lt!.wordIndex).toBe(1);
    });

    it('single-click on the SAME looped word is a no-op', () => {
        loopTarget.set({ kind: 'word', wordIndex: 0, startSec: 1, endSec: 2 });
        const { container } = render(UnifiedDisplay);
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        fireEvent.click(blocks[0]!);
        vi.advanceTimersByTime(TS_CLICK_DELAY_MS + 1);
        expect(get(loopTarget)!.wordIndex).toBe(0);
    });

    it('double-click cancels the pending single-click (race-free dblclick)', () => {
        loopTarget.set({ kind: 'word', wordIndex: 0, startSec: 1, endSec: 2 });
        const { container } = render(UnifiedDisplay);
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');

        // Simulate a real double-click: click fires first, then dblclick.
        fireEvent.click(blocks[1]!);
        fireEvent.dblClick(blocks[1]!);

        // Pending single-click must be dropped — dblclick alone decides the loop.
        vi.advanceTimersByTime(TS_CLICK_DELAY_MS + 1);

        // Dblclick on word 1 while looped on word 0 → toggleLoopOn sees a
        // DIFFERENT target → sets loop to word 1.
        const lt = get(loopTarget);
        expect(lt).not.toBeNull();
        expect(lt!.wordIndex).toBe(1);
    });

    it('double-click on the CURRENTLY looped word clears the loop (toggle off)', () => {
        loopTarget.set({ kind: 'word', wordIndex: 1, startSec: 3, endSec: 4 });
        const { container } = render(UnifiedDisplay);
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');

        fireEvent.click(blocks[1]!);
        fireEvent.dblClick(blocks[1]!);
        vi.advanceTimersByTime(TS_CLICK_DELAY_MS + 1);

        // Pending click is cancelled; dblclick on same target exits loop.
        expect(get(loopTarget)).toBeNull();
    });

    it('single-click with no loop active performs a plain seek (no loop mutation)', () => {
        const audio = makeAudioStub();
        bindAudio(audio);
        loopTarget.set(null);

        const { container } = render(UnifiedDisplay);
        const blocks = container.querySelectorAll<HTMLElement>('.mega-block');
        fireEvent.click(blocks[2]!);
        vi.advanceTimersByTime(TS_CLICK_DELAY_MS + 1);

        expect(get(loopTarget)).toBeNull();
        // Word 2 starts at 5s; seek = word.start + tsSegOffset (0) = 5.
        expect(audio.currentTime).toBeCloseTo(5, 6);
    });
});
