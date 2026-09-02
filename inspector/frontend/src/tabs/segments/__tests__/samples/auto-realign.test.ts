import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Segment } from '../../../../lib/types/view-models';

const { realign, commit, segs, sample } = vi.hoisted(() => ({
    realign: vi.fn(),
    commit: vi.fn(),
    segs: [] as Segment[],
    sample: { id: 'sid' },
}));

vi.mock('../../../../lib/api/samples', () => ({
    realignSampleSegment: (...a: unknown[]) => realign(...a),
    SampleApiError: class extends Error {},
}));
vi.mock('../../utils/edit/setWordTimings', () => ({ setWordTimingsOnSegment: (...a: unknown[]) => commit(...a) }));
vi.mock('../../stores/chapter', () => ({ getChapterSegments: () => segs }));
vi.mock('../../stores/samples', async () => {
    const { readable } = await import('svelte/store');
    return { activeSample: readable(sample), sampleHasWordTimings: readable(true) };
});
vi.mock('../../../../lib/refs/quran-refs', async () => {
    const { readable } = await import('svelte/store');
    return { quranRefs: readable({ verse_word_counts: { '2:1': 2 } }) };
});
vi.mock('../../../../lib/stores/toast', () => ({ pushToast: vi.fn() }));

import { finalizeOp } from '../../stores/dirty';
import { REALIGN_DELAY_MS, realignStatus, startAutoRealign } from '../../utils/samples/auto-realign';

const op = (uid: string, op_type = 'trim_segment') =>
    ({ op_type, targets_after: [{ segment_uid: uid }], targets_before: [], snapshots: { before: [], after: [] } }) as never;

describe('auto realign scheduler', () => {
    let stop: () => void;
    beforeEach(() => {
        vi.useFakeTimers();
        segs.length = 0;
        segs.push({
            index: 0, entry_idx: 0, chapter: 2, segment_uid: 'u1', time_start: 100, time_end: 900,
            matched_ref: '2:1:1-2:1:2', confidence: 1,
            word_timings: [{ word: 'a', location: '2:1:1', start_ms: 100, end_ms: 400 }],
        });
        realign.mockReset().mockResolvedValue([{ word: 'b', location: '2:1:2', start_ms: 400, end_ms: 800 }]);
        commit.mockReset();
        stop = startAutoRealign();
    });
    afterEach(() => {
        stop();
        vi.useRealTimers();
    });

    it('counts down, restarts on a follow-up edit, then realigns and commits', async () => {
        finalizeOp(2, op('u1'));
        expect(get(realignStatus).u1).toEqual({ phase: 'countdown', seconds: 10 });
        vi.advanceTimersByTime(4000);
        expect(get(realignStatus).u1).toEqual({ phase: 'countdown', seconds: 6 });
        finalizeOp(2, op('u1', 'split_segment'));
        vi.advanceTimersByTime(1000);
        expect(get(realignStatus).u1).toEqual({ phase: 'countdown', seconds: 9 });

        await vi.advanceTimersByTimeAsync(REALIGN_DELAY_MS);
        expect(realign).toHaveBeenCalledWith('sid', {
            segment_uid: 'u1', matched_ref: '2:1:1-2:1:2', time_start: 100, time_end: 900,
        });
        expect(commit).toHaveBeenCalledTimes(1);
        expect(get(realignStatus).u1).toBeUndefined();
    });

    it('skips segments whose timings already cover the ref and non-invalidating ops', async () => {
        segs[0]!.word_timings!.push({ word: 'b', location: '2:1:2', start_ms: 400, end_ms: 800 });
        finalizeOp(2, op('u1'));
        expect(get(realignStatus).u1).toBeUndefined();
        segs[0]!.word_timings!.pop();
        finalizeOp(2, op('u1', 'set_is_wasl'));
        expect(get(realignStatus).u1).toBeUndefined();
        await vi.advanceTimersByTimeAsync(REALIGN_DELAY_MS);
        expect(realign).not.toHaveBeenCalled();
    });
});
