import { describe, it, expect } from 'vitest';

import type { Segment } from '../../../../../lib/types/domain';
import { buildSegRangeSpec, buildSegPolicy, resolveSegNextRange } from '../range-spec';
import { AUTOPLAY_GAP_PAUSE_MS } from '../../constants';

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
        audio_url: 'http://x/seg.mp3',
        ...overrides,
    };
}

describe('buildSegRangeSpec', () => {
    it('emits {startMs, endMs, src} from segment fields', () => {
        const seg = makeSegment({
            index: 5,
            time_start: 1500,
            time_end: 2500,
            audio_url: 'http://x/abc.mp3',
        });
        const spec = buildSegRangeSpec(seg);
        expect(spec.startMs).toBe(1500);
        expect(spec.endMs).toBe(2500);
        expect(spec.src).toBe('http://x/abc.mp3');
    });

    it('honors seekToMs override', () => {
        const seg = makeSegment({ time_start: 1000, time_end: 2000 });
        const spec = buildSegRangeSpec(seg, 1234);
        expect(spec.startMs).toBe(1234);
        expect(spec.endMs).toBe(2000);
    });

    it('falls back src to null when audio_url is empty', () => {
        const seg = makeSegment({ audio_url: '' });
        expect(buildSegRangeSpec(seg).src).toBeNull();
    });
});

describe('resolveSegNextRange', () => {
    it('returns the next consecutive seg in the displayed slice', () => {
        const segs = [
            makeSegment({ index: 0, time_start: 0, time_end: 1000, audio_url: 'a' }),
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
            makeSegment({ index: 2, time_start: 2000, time_end: 3000, audio_url: 'a' }),
        ];
        const spec = resolveSegNextRange({ getDisplayed: () => segs, currentIndex: 1 });
        expect(spec).not.toBeNull();
        expect(spec!.startMs).toBe(2000);
        expect(spec!.endMs).toBe(3000);
    });

    it('returns null when the next index is not currentIndex + 1', () => {
        // Filter has hidden a row between idx 1 and idx 3 — refuse to skip.
        const segs = [
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
            makeSegment({ index: 3, time_start: 3000, time_end: 4000, audio_url: 'a' }),
        ];
        expect(resolveSegNextRange({ getDisplayed: () => segs, currentIndex: 1 })).toBeNull();
    });

    it('returns null at the end of the slice', () => {
        const segs = [makeSegment({ index: 0, time_start: 0, time_end: 1000 })];
        expect(resolveSegNextRange({ getDisplayed: () => segs, currentIndex: 0 })).toBeNull();
    });

    it('returns null when displayed is null', () => {
        expect(resolveSegNextRange({ getDisplayed: () => null, currentIndex: 0 })).toBeNull();
    });
});

describe('buildSegPolicy', () => {
    const baseOpts = {
        getCurrentIndex: () => 0,
        getDisplayed: () => null,
    };

    it('stop policy when autoplay is disabled', () => {
        const policy = buildSegPolicy({ ...baseOpts, autoPlayEnabled: false, isAccordionPlay: false });
        expect(policy.kind).toBe('stop');
    });

    it('stop policy in accordion play even when autoplay is enabled', () => {
        const policy = buildSegPolicy({ ...baseOpts, autoPlayEnabled: true, isAccordionPlay: true });
        expect(policy.kind).toBe('stop');
    });

    it('advance policy with AUTOPLAY_GAP_PAUSE_MS when autoplay enabled in main list', () => {
        const policy = buildSegPolicy({ ...baseOpts, autoPlayEnabled: true, isAccordionPlay: false });
        expect(policy.kind).toBe('advance');
        if (policy.kind === 'advance') {
            expect(policy.gapMs).toBe(AUTOPLAY_GAP_PAUSE_MS);
        }
    });

    it('advance policy nextRange resolves dynamically — filter change between gaps takes effect', () => {
        const segs = [
            makeSegment({ index: 0, time_start: 0, time_end: 1000, audio_url: 'a' }),
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
        ];
        let displayed: typeof segs | null = segs;
        const policy = buildSegPolicy({
            autoPlayEnabled: true,
            isAccordionPlay: false,
            getCurrentIndex: () => 0,
            getDisplayed: () => displayed,
        });
        if (policy.kind !== 'advance') throw new Error('expected advance');
        expect(policy.nextRange()?.startMs).toBe(1000);

        // Simulate filter change between boundary fires.
        displayed = [makeSegment({ index: 0, time_start: 0, time_end: 1000 })];
        expect(policy.nextRange()).toBeNull();
    });

    it('advance policy uses the live current index — no infinite loop on consecutive boundaries', () => {
        // Regression: a stale captured currentIndex made the resolver return
        // the same "next" seg on every boundary, looping seg N+1 forever.
        const segs = [
            makeSegment({ index: 0, time_start: 0, time_end: 1000, audio_url: 'a' }),
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
            makeSegment({ index: 2, time_start: 2000, time_end: 3000, audio_url: 'a' }),
        ];
        let activeIdx = 0;
        const policy = buildSegPolicy({
            autoPlayEnabled: true,
            isAccordionPlay: false,
            getCurrentIndex: () => activeIdx,
            getDisplayed: () => segs,
        });
        if (policy.kind !== 'advance') throw new Error('expected advance');

        // First boundary: playing seg 0, advance returns seg 1.
        expect(policy.nextRange()?.startMs).toBe(1000);

        // Caller advances to seg 1; second boundary should now return seg 2.
        activeIdx = 1;
        expect(policy.nextRange()?.startMs).toBe(2000);

        // Caller advances to seg 2 (last); third boundary returns null.
        activeIdx = 2;
        expect(policy.nextRange()).toBeNull();
    });
});
