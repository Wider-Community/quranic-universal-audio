/**
 * prefetch.ts — VBR clip URL prefetch + accordion sibling resolver.
 *
 * Verifies the two-resolver routing in `prefetchNextSegAudio`:
 *   - Chapter mode (no `currentChapter` arg) → `nextDisplayedSeg` by index+1.
 *   - Accordion mode (with `currentChapter`) → `nextSiblingSeg` by list pos.
 * And the per-sibling VBR/CBR transport branch driven by the per-reciter
 * `reciterVbrChapters` store.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Segment } from '../../../../../lib/types/domain';
import {
    reciterVbrChapters,
    selectedReciter,
} from '../../../stores/chapter';
import { nextDisplayedSeg, nextSiblingSeg, prefetchNextSegAudio } from '../prefetch';

function makeSegment(overrides: Partial<Segment> = {}): Segment {
    return {
        index: 0,
        entry_idx: 0,
        time_start: 0,
        time_end: 1000,
        matched_ref: '1:1:1-1:1:1',
        matched_text: 'x',
        display_text: 'x',
        confidence: 1.0,
        audio_url: 'http://x/audio.mp3',
        chapter: 1,
        ...overrides,
    };
}

let fetchSpy: ReturnType<typeof vi.fn>;
const _origFetch = globalThis.fetch;

beforeEach(() => {
    fetchSpy = vi.fn(() => Promise.resolve(new Response(new Blob())));
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    selectedReciter.set('test_reciter');
    reciterVbrChapters.set(new Set());
});

afterEach(() => {
    globalThis.fetch = _origFetch;
    selectedReciter.set('');
    reciterVbrChapters.set(new Set());
});

describe('nextDisplayedSeg', () => {
    it('returns the segment at pos+1 for the matched index', () => {
        const segs = [
            makeSegment({ index: 0 }), makeSegment({ index: 1 }), makeSegment({ index: 2 }),
        ];
        expect(nextDisplayedSeg(segs, 0)?.index).toBe(1);
        expect(nextDisplayedSeg(segs, 1)?.index).toBe(2);
    });

    it('returns null at the end of the slice or when index is missing', () => {
        const segs = [makeSegment({ index: 0 })];
        expect(nextDisplayedSeg(segs, 0)).toBeNull();
        expect(nextDisplayedSeg(segs, 99)).toBeNull();
        expect(nextDisplayedSeg(null, 0)).toBeNull();
    });
});

describe('nextSiblingSeg — list-position resolver', () => {
    it('matches by (chapter, index) and returns the next list element', () => {
        const siblings = [
            makeSegment({ chapter: 4, index: 10 }),
            makeSegment({ chapter: 5, index: 0 }),    // cross-chapter sibling
            makeSegment({ chapter: 5, index: 1 }),
        ];
        expect(nextSiblingSeg(siblings, 4, 10)?.chapter).toBe(5);
        expect(nextSiblingSeg(siblings, 4, 10)?.index).toBe(0);
        expect(nextSiblingSeg(siblings, 5, 0)?.index).toBe(1);
    });

    it('does not pick the second occurrence of a same-index seg in another chapter', () => {
        // A validation panel with chapter=null may render the same seg.index
        // from two chapters. Match must be (chapter, index)-tuple, not just index.
        const siblings = [
            makeSegment({ chapter: 4, index: 5 }),
            makeSegment({ chapter: 7, index: 5 }),    // shares seg.index, different chapter
            makeSegment({ chapter: 7, index: 6 }),
        ];
        expect(nextSiblingSeg(siblings, 7, 5)?.index).toBe(6);
        expect(nextSiblingSeg(siblings, 7, 5)?.chapter).toBe(7);
    });

    it('returns null at the end of the list', () => {
        const siblings = [makeSegment({ chapter: 1, index: 0 })];
        expect(nextSiblingSeg(siblings, 1, 0)).toBeNull();
    });

    it('returns null when no row matches', () => {
        const siblings = [makeSegment({ chapter: 1, index: 0 })];
        expect(nextSiblingSeg(siblings, 99, 0)).toBeNull();
        expect(nextSiblingSeg(null, 1, 0)).toBeNull();
    });
});

describe('prefetchNextSegAudio — chapter mode (no currentChapter)', () => {
    it('fires the clip URL when the next sibling lives in a VBR chapter', () => {
        reciterVbrChapters.set(new Set([1]));
        const segs = [
            makeSegment({ chapter: 1, index: 0, audio_url: 'http://x/c1.mp3' }),
            makeSegment({ chapter: 1, index: 1, audio_url: 'http://x/c1.mp3', time_start: 1000, time_end: 2000 }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(segs, 0, 'http://x/c1.mp3', cache);

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        const url = fetchSpy.mock.calls[0]?.[0] as string;
        expect(url).toContain('/api/seg/segment-clip/test_reciter');
        expect(url).toContain('start_ms=1000');
        expect(url).toContain('end_ms=2000');
        expect(cache[url]).toBeDefined();
    });

    it('falls through to the chapter URL when next sibling is in a non-VBR chapter', () => {
        reciterVbrChapters.set(new Set([2]));    // chapter 1 NOT in VBR set
        const segs = [
            makeSegment({ chapter: 1, index: 0, audio_url: 'http://x/c1.mp3' }),
            makeSegment({ chapter: 1, index: 1, audio_url: 'http://x/c2.mp3' }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(segs, 0, 'http://x/c1.mp3', cache);

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        expect(fetchSpy).toHaveBeenCalledWith('http://x/c2.mp3');
    });

    it('skips when next sibling shares the current src and is CBR', () => {
        reciterVbrChapters.set(new Set());
        const segs = [
            makeSegment({ chapter: 1, index: 0, audio_url: 'http://x/c1.mp3' }),
            makeSegment({ chapter: 1, index: 1, audio_url: 'http://x/c1.mp3' }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(segs, 0, 'http://x/c1.mp3', cache);
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('does not refetch a URL already in the cache', () => {
        reciterVbrChapters.set(new Set([1]));
        const segs = [
            makeSegment({ chapter: 1, index: 0, time_start: 0, time_end: 1000 }),
            makeSegment({ chapter: 1, index: 1, time_start: 1000, time_end: 2000 }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(segs, 0, 'http://x/audio.mp3', cache);
        expect(fetchSpy).toHaveBeenCalledTimes(1);

        prefetchNextSegAudio(segs, 0, 'http://x/audio.mp3', cache);
        expect(fetchSpy).toHaveBeenCalledTimes(1);
    });
});

describe('prefetchNextSegAudio — accordion mode (with currentChapter)', () => {
    it('uses list-position resolver and fires the clip URL for a cross-chapter VBR sibling', () => {
        // Active chapter is 4 (VBR). The accordion's sibling list crosses
        // into chapter 5 (also VBR per reciter map). Prefetch should target
        // chapter-5's clip URL using its own audio_url + window.
        reciterVbrChapters.set(new Set([4, 5]));
        const siblings = [
            makeSegment({ chapter: 4, index: 100, audio_url: 'http://x/c4.mp3', time_start: 0, time_end: 1000 }),
            makeSegment({ chapter: 5, index: 0, audio_url: 'http://x/c5.mp3', time_start: 500, time_end: 1500 }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(siblings, 100, 'http://x/c4.mp3', cache, 4);

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        const url = fetchSpy.mock.calls[0]?.[0] as string;
        expect(url).toContain('/api/seg/segment-clip/test_reciter');
        expect(url).toContain('http%3A%2F%2Fx%2Fc5.mp3');
        expect(url).toContain('start_ms=500');
        expect(url).toContain('end_ms=1500');
    });

    it('falls back to chapter URL when the next cross-chapter sibling is CBR', () => {
        reciterVbrChapters.set(new Set([4]));    // chapter 5 is CBR
        const siblings = [
            makeSegment({ chapter: 4, index: 100, audio_url: 'http://x/c4.mp3' }),
            makeSegment({ chapter: 5, index: 0, audio_url: 'http://x/c5.mp3' }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(siblings, 100, 'http://x/c4.mp3', cache, 4);

        expect(fetchSpy).toHaveBeenCalledTimes(1);
        expect(fetchSpy).toHaveBeenCalledWith('http://x/c5.mp3');
    });

    it('does not skip CBR fallback when src differs across siblings', () => {
        // Accordion sibling lists may include the same audio_url repeated;
        // the URL-equality short-circuit only matters when the sibling shares
        // the *current* row's audio. Different file → fire.
        reciterVbrChapters.set(new Set());
        const siblings = [
            makeSegment({ chapter: 4, index: 0, audio_url: 'http://x/a.mp3' }),
            makeSegment({ chapter: 4, index: 1, audio_url: 'http://x/b.mp3' }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(siblings, 0, 'http://x/a.mp3', cache, 4);
        expect(fetchSpy).toHaveBeenCalledTimes(1);
        expect(fetchSpy).toHaveBeenCalledWith('http://x/b.mp3');
    });

    it('returns silently when there is no next sibling', () => {
        reciterVbrChapters.set(new Set([1]));
        const siblings = [makeSegment({ chapter: 1, index: 0 })];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(siblings, 0, 'http://x/audio.mp3', cache, 1);
        expect(fetchSpy).not.toHaveBeenCalled();
    });

    it('returns silently when reciter is unset (clip URL would be unconstructable)', () => {
        selectedReciter.set('');
        reciterVbrChapters.set(new Set([1]));
        const siblings = [
            makeSegment({ chapter: 1, index: 0, audio_url: 'http://x/c1.mp3' }),
            makeSegment({ chapter: 1, index: 1, audio_url: 'http://x/c1.mp3', time_start: 1000, time_end: 2000 }),
        ];
        const cache: Record<string, Promise<unknown>> = {};
        prefetchNextSegAudio(siblings, 0, 'http://x/c1.mp3', cache, 1);
        // VBR fast path falls through (reciter empty), CBR path skips because
        // sibling shares the current src — net: no fetch.
        expect(fetchSpy).not.toHaveBeenCalled();
    });
});
