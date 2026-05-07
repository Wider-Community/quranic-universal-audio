import { describe, expect, it } from 'vitest';

import type { Segment } from '../../../../../lib/types/domain';
import { resolveAutoplayGapAdvance } from '../autoplay-gap';

function makeSegment(overrides: Partial<Segment>): Segment {
    return {
        audio_url: '/audio/ch1.mp3',
        chapter: 1,
        confidence: 1,
        display_text: '',
        entry_idx: 0,
        index: 0,
        matched_ref: '',
        matched_text: '',
        silence_after_ms: 0,
        silence_after_raw_ms: 0,
        time_end: 0,
        time_start: 0,
        ...overrides,
    };
}

describe('resolveAutoplayGapAdvance', () => {
    it('schedules a pause even when playback has already crossed into the next segment', () => {
        const displayedSegments = [
            makeSegment({ index: 10, time_start: 0, time_end: 1_000 }),
            makeSegment({ index: 11, time_start: 1_000, time_end: 2_000 }),
        ];

        const advance = resolveAutoplayGapAdvance({
            active: { chapter: 1, index: 10 },
            currentSrc: 'https://example.test/audio/ch1.mp3',
            displayedSegments,
            playEndMs: 1_000,
            timeMs: 1_050,
        });

        expect(advance).not.toBeNull();
        expect(advance?.justEnded.index).toBe(10);
        expect(advance?.next.index).toBe(11);
    });

    it('schedules a pause while playback is inside a real silence gap', () => {
        const displayedSegments = [
            makeSegment({ index: 10, time_start: 0, time_end: 1_000 }),
            makeSegment({ index: 11, time_start: 1_250, time_end: 2_000 }),
        ];

        const advance = resolveAutoplayGapAdvance({
            active: { chapter: 1, index: 10 },
            currentSrc: 'https://example.test/audio/ch1.mp3',
            displayedSegments,
            playEndMs: 1_000,
            timeMs: 1_100,
        });

        expect(advance?.next.index).toBe(11);
    });

    it('does not schedule a pause when the next displayed segment uses a different audio file', () => {
        const displayedSegments = [
            makeSegment({ index: 10, time_start: 0, time_end: 1_000 }),
            makeSegment({ index: 11, audio_url: '/audio/ch2.mp3', time_start: 0, time_end: 2_000 }),
        ];

        const advance = resolveAutoplayGapAdvance({
            active: { chapter: 1, index: 10 },
            currentSrc: 'https://example.test/audio/ch1.mp3',
            displayedSegments,
            playEndMs: 1_000,
            timeMs: 1_050,
        });

        expect(advance).toBeNull();
    });

    it('does not schedule a pause when the next displayed row is not consecutive', () => {
        const displayedSegments = [
            makeSegment({ index: 10, time_start: 0, time_end: 1_000 }),
            makeSegment({ index: 12, time_start: 1_000, time_end: 2_000 }),
        ];

        const advance = resolveAutoplayGapAdvance({
            active: { chapter: 1, index: 10 },
            currentSrc: 'https://example.test/audio/ch1.mp3',
            displayedSegments,
            playEndMs: 1_000,
            timeMs: 1_050,
        });

        expect(advance).toBeNull();
    });
});
