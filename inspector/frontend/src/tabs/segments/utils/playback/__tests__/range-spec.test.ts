import { describe, expect,it } from 'vitest';

import type { SegDataResponse } from '../../../../../lib/types/api';
import type { Segment } from '../../../../../lib/types/domain';
import { segData, selectedReciter } from '../../../stores/chapter';
import { AUTOPLAY_GAP_PAUSE_MS } from '../../constants';
import { buildSegmentClipUrl, buildSegPolicy, buildSegRangeSpec, resolveSegNextRange } from '../range-spec';

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

describe('buildSegRangeSpec — VBR routing', () => {
    function withVbrSegData<T>(reciter: string, fn: () => T): T {
        const prev = { reciter: '', data: null as SegDataResponse | null };
        selectedReciter.subscribe((v) => { prev.reciter = v; })();
        segData.subscribe((v) => { prev.data = v; })();
        selectedReciter.set(reciter);
        segData.set({
            audio_url: 'http://x/seg.mp3',
            vbr: true,
            segments: [],
            summary: {} as never,
            verse_word_counts: {},
        });
        try {
            return fn();
        } finally {
            selectedReciter.set(prev.reciter);
            segData.set(prev.data);
        }
    }

    it('emits clip-relative spec with clipFileOffsetMs when chapter is VBR', () => {
        const seg = makeSegment({ time_start: 4411667, time_end: 4419395, audio_url: 'http://x/004.mp3' });
        withVbrSegData('yasser_al_dosari', () => {
            const spec = buildSegRangeSpec(seg);
            expect(spec.startMs).toBe(0);
            expect(spec.endMs).toBe(7728);
            expect(spec.clipFileOffsetMs).toBe(4411667);
            expect(spec.src).toBe('/api/seg/segment-clip/yasser_al_dosari?url=http%3A%2F%2Fx%2F004.mp3&start_ms=4411667&end_ms=4419395');
        });
    });

    it('maps file-absolute seekToMs into clip-relative space', () => {
        const seg = makeSegment({ time_start: 1000, time_end: 5000, audio_url: 'http://x/seg.mp3' });
        withVbrSegData('r', () => {
            const spec = buildSegRangeSpec(seg, 3500);
            expect(spec.startMs).toBe(2500);
            expect(spec.endMs).toBe(4000);
            expect(spec.clipFileOffsetMs).toBe(1000);
        });
    });

    it('clamps seekToMs into the clip window so out-of-range values do not seek negative', () => {
        const seg = makeSegment({ time_start: 1000, time_end: 5000, audio_url: 'http://x/seg.mp3' });
        withVbrSegData('r', () => {
            const before = buildSegRangeSpec(seg, 500);
            expect(before.startMs).toBe(0);
            const after = buildSegRangeSpec(seg, 9000);
            expect(after.startMs).toBe(4000);
        });
    });

    it('falls back to file-absolute spec when reciter slug is missing', () => {
        const seg = makeSegment({ time_start: 1000, time_end: 2000, audio_url: 'http://x/seg.mp3' });
        // VBR but no reciter → no clip URL we can build → CBR fallback
        const prev = { data: null as SegDataResponse | null };
        segData.subscribe((v) => { prev.data = v; })();
        segData.set({
            audio_url: 'http://x/seg.mp3', vbr: true, segments: [],
            summary: {} as never, verse_word_counts: {},
        });
        try {
            const spec = buildSegRangeSpec(seg);
            expect(spec.startMs).toBe(1000);
            expect(spec.clipFileOffsetMs).toBeUndefined();
        } finally {
            segData.set(prev.data);
        }
    });
});

describe('buildSegmentClipUrl', () => {
    it('encodes the source url and segment window into the clip endpoint path', () => {
        const seg = makeSegment({ time_start: 100, time_end: 250, audio_url: 'https://server.example.com/path with space.mp3' });
        const url = buildSegmentClipUrl('reciter_slug', seg);
        expect(url).toBe('/api/seg/segment-clip/reciter_slug?url=https%3A%2F%2Fserver.example.com%2Fpath+with+space.mp3&start_ms=100&end_ms=250');
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

    it('advance kind always for main-list play; nextRange returns null when autoplay off', () => {
        // autoplay-off no longer produces {kind:'stop'} — it produces advance
        // with nextRange gated on the live getter so toggling mid-play works.
        const policy = buildSegPolicy({ ...baseOpts, getAutoPlayEnabled: () => false, isAccordionPlay: false });
        expect(policy.kind).toBe('advance');
        if (policy.kind === 'advance') {
            expect(policy.nextRange()).toBeNull();
        }
    });

    it('stop policy in accordion play even when autoplay is enabled', () => {
        const policy = buildSegPolicy({ ...baseOpts, getAutoPlayEnabled: () => true, isAccordionPlay: true });
        expect(policy.kind).toBe('stop');
    });

    it('advance policy with AUTOPLAY_GAP_PAUSE_MS when autoplay enabled in main list', () => {
        const policy = buildSegPolicy({ ...baseOpts, getAutoPlayEnabled: () => true, isAccordionPlay: false });
        expect(policy.kind).toBe('advance');
        if (policy.kind === 'advance') {
            expect(policy.gapMs).toBe(AUTOPLAY_GAP_PAUSE_MS);
        }
    });

    it('nextRange responds to live autoplay toggle — off mid-play stops at next boundary', () => {
        const segs = [
            makeSegment({ index: 0, time_start: 0, time_end: 1000, audio_url: 'a' }),
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
        ];
        let autoPlay = true;
        const policy = buildSegPolicy({
            getAutoPlayEnabled: () => autoPlay,
            isAccordionPlay: false,
            getCurrentIndex: () => 0,
            getDisplayed: () => segs,
        });
        if (policy.kind !== 'advance') throw new Error('expected advance');
        expect(policy.nextRange()?.startMs).toBe(1000);

        // User toggles autoplay OFF mid-segment — next boundary stops.
        autoPlay = false;
        expect(policy.nextRange()).toBeNull();

        // Toggle back ON — resumes advancing.
        autoPlay = true;
        expect(policy.nextRange()?.startMs).toBe(1000);
    });

    it('advance policy nextRange resolves dynamically — filter change between gaps takes effect', () => {
        const segs = [
            makeSegment({ index: 0, time_start: 0, time_end: 1000, audio_url: 'a' }),
            makeSegment({ index: 1, time_start: 1000, time_end: 2000, audio_url: 'a' }),
        ];
        let displayed: typeof segs | null = segs;
        const policy = buildSegPolicy({
            getAutoPlayEnabled: () => true,
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
            getAutoPlayEnabled: () => true,
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
