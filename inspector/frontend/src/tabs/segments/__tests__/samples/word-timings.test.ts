import { describe, expect, it } from 'vitest';

import type { SegWordTiming } from '../../../../lib/types/generated/schemas';
import { applyCommand } from '../../domain/apply-command';
import type { Segment } from '../../../../lib/types/view-models';
import {
    clipWordTimings,
    concatWordTimings,
    filterWordTimingsToRef,
    needsRealign,
    partitionWordTimings,
    wordCoverage,
} from '../../utils/samples/word-timings';

const w = (location: string, start_ms: number, end_ms: number): SegWordTiming => ({
    word: location, location, start_ms, end_ms,
});
const WORDS = [w('2:1:1', 1000, 1500), w('2:1:2', 1500, 2200), w('2:1:3', 2200, 3000), w('2:2:1', 3000, 3900)];
const VWC = { '2:1': 3, '2:2': 4 };

describe('word timing edit rules', () => {
    it('trim keeps only words fully inside the span', () => {
        expect(clipWordTimings(WORDS, 1400, 3000)?.map((x) => x.location)).toEqual(['2:1:2', '2:1:3']);
        expect(clipWordTimings(WORDS, 5000, 6000)).toBeNull();
        expect(clipWordTimings(null, 0, 1)).toBeNull();
    });

    it('split partitions at cursors and orphans a straddling word', () => {
        const parts = partitionWordTimings(WORDS, 1000, 3900, [2000, 3000]);
        expect(parts.map((p) => p?.map((x) => x.location) ?? null)).toEqual([
            ['2:1:1'], ['2:1:3'], ['2:2:1'],
        ]);
    });

    it('merge concatenates in time order', () => {
        expect(concatWordTimings([WORDS[2]!], [WORDS[0]!])?.map((x) => x.location)).toEqual(['2:1:1', '2:1:3']);
        expect(concatWordTimings(null, undefined)).toBeNull();
    });

    it('reference edit keeps the words still inside the ref', () => {
        expect(filterWordTimingsToRef(WORDS, '2:1:2-2:2:1')?.map((x) => x.location)).toEqual(['2:1:2', '2:1:3', '2:2:1']);
        expect(filterWordTimingsToRef(WORDS, 'Basmala')).toBeNull();
    });

    it('coverage compares ref word count with covered locations', () => {
        expect(wordCoverage('2:1:1-2:2:1', WORDS, VWC)).toEqual({ expected: 4, covered: 4 });
        expect(needsRealign('2:1:1-2:2:1', WORDS.slice(0, 2), VWC)).toBe(true);
        expect(needsRealign('2:1:1-2:2:1', WORDS, VWC)).toBe(false);
        expect(needsRealign('Basmala', null, VWC)).toBe(false);
    });
});

describe('reducers carry word timings', () => {
    const seg: Segment = {
        index: 0, entry_idx: 0, chapter: 2, segment_uid: 'u1',
        time_start: 1000, time_end: 3900, matched_ref: '2:1:1-2:2:1', confidence: 0.9,
        word_timings: WORDS,
    };
    const state = { byId: { u1: seg }, idsByChapter: { 2: ['u1'] }, selectedChapter: 2 };

    it('split hands each piece its words and filters to the piece ref', () => {
        const r = applyCommand(state, {
            type: 'split', segmentUid: 'u1', splitMs: [2200], refs: ['2:1:1-2:1:2', '2:1:3-2:2:1'], newUids: ['u2'],
        });
        expect(r.nextState.byId.u1?.word_timings?.map((x) => x.location)).toEqual(['2:1:1', '2:1:2']);
        expect(r.nextState.byId.u2?.word_timings?.map((x) => x.location)).toEqual(['2:1:3', '2:2:1']);
    });

    it('trim clips, ref edit filters, setWordTimings replaces and snapshots', () => {
        const trimmed = applyCommand(state, { type: 'trim', segmentUid: 'u1', delta: { time_start: 1500 } });
        expect(trimmed.nextState.byId.u1?.word_timings?.length).toBe(3);

        const edited = applyCommand(state, { type: 'editReference', segmentUid: 'u1', matched_ref: '2:1:1-2:1:2' });
        expect(edited.nextState.byId.u1?.word_timings?.map((x) => x.location)).toEqual(['2:1:1', '2:1:2']);

        const set = applyCommand(state, { type: 'setWordTimings', segmentUid: 'u1', word_timings: [WORDS[0]!] });
        expect(set.operation.op_type).toBe('set_word_timings');
        expect((set.operation.snapshots.after[0] as { word_timings?: unknown }).word_timings).toEqual([WORDS[0]]);
    });
});
