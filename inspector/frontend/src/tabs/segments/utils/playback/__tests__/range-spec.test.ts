import { describe, expect, it } from 'vitest';

import type { Segment } from '../../../../../lib/types/domain';
import { buildSegmentClipUrl } from '../range-spec';

function makeSegment(overrides: Partial<Segment> = {}): Segment {
    return {
        index: 0,
        entry_idx: 0,
        time_start: 0,
        time_end: 1000,
        matched_ref: '1:1:1-1:1:1',
        matched_text: 'x',
        confidence: 1.0,
        audio_url: 'http://x/seg.mp3',
        ...overrides,
    };
}

describe('buildSegmentClipUrl', () => {
    it('encodes the source url and segment window into the clip endpoint path', () => {
        const seg = makeSegment({
            time_start: 100,
            time_end: 250,
            audio_url: 'https://server.example.com/path with space.mp3',
        });
        const url = buildSegmentClipUrl('reciter_slug', seg);
        expect(url).toBe(
            '/api/seg/segment-clip/reciter_slug?url=https%3A%2F%2Fserver.example.com%2Fpath+with+space.mp3&start_ms=100&end_ms=250',
        );
    });
});
