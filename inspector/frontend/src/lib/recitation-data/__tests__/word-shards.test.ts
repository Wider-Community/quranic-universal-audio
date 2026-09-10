import { describe, expect, it } from 'vitest';

import { decodeTimestampShard } from '../compact-shards';
import { WORD_SHARD, WORD_TEXTS } from '../test-word-fixture';
import { assembleOccasion, shardOccasions, type TsReciterAudio } from '../ts-source';
import type { TsWordShardResponse } from '../../types/ts-client';

const BY_SURAH: TsReciterAudio = { audio_category: 'by_surah' };

function assemble() {
    const shard = decodeTimestampShard(WORD_SHARD) as TsWordShardResponse;
    const occasion = shardOccasions(shard)[0]!;
    return assembleOccasion('r', occasion, {}, {}, BY_SURAH, 'chapter.mp3');
}

describe('word-profile assembly', () => {
    it('takes each word text from the shard row, not the Hafs script files', () => {
        // `qpc` and `dk` are passed empty on purpose: reaching for them would
        // render Qalun coordinates in the Hafs spelling.
        const data = assemble();
        expect(data.words.map((word) => word.text)).toEqual(WORD_TEXTS);
        expect(data.words.map((word) => word.display_text)).toEqual(WORD_TEXTS);
        expect(data.words.map((word) => word.location)).toEqual([
            '112:1:1', '112:1:2', '112:1:3', '112:1:4',
        ]);
    });

    it('emits no letters and no phoneme intervals', () => {
        const data = assemble();
        expect(data.intervals).toEqual([]);
        expect(data.words.every((word) => word.letters.length === 0)).toBe(true);
        expect(data.words.every((word) => word.phoneme_indices.length === 0)).toBe(true);
    });

    it('leaves `native` empty and fills `wordReadings` instead', () => {
        const data = assemble();
        expect(data.native).toEqual([]);
        expect(data.wordReadings.map((reading) => reading.id)).toEqual(['r1']);
    });

    it('anchors word times against the occasion start for by_surah audio', () => {
        // Occasion starts at 0 here, so the offset is 0 and the seconds are the
        // stored ms — the point is that the SAME offset reaches both views.
        const data = assemble();
        expect(data.words[1]!.start).toBeCloseTo(0.8, 6);
        expect(data.wordReadings[0]!.words[1]!.start).toBeCloseTo(0.8, 6);
        expect(data.time_start_ms).toBe(0);
        expect(data.time_end_ms).toBe(3000);
    });

    it('pairs each word with the gap that follows it', () => {
        const data = assemble();
        const gaps = data.wordReadings[0]!.words.map((word) => word.boundary);
        // Boundary `i + 1` follows word `i`; boundary 0 is the lead-in and is
        // never attached to a word.
        expect(gaps.map((gap) => gap?.id)).toEqual([1, 2, 3, 4]);
        expect(gaps[0]!.start).toBeCloseTo(0.7, 6);
        expect(gaps[0]!.end).toBeCloseTo(0.8, 6);
    });

    it('marks the verse end on the gap that closes the verse', () => {
        const data = assemble();
        const gaps = data.wordReadings[0]!.words.map((word) => word.boundary);
        expect(gaps.map((gap) => gap?.verseEnd)).toEqual([null, null, null, 1]);
        expect(gaps.map((gap) => gap?.state)).toEqual(['join', 'join', 'join', 'stop']);
    });

    it('keeps only the words this occasion selected', () => {
        const shard = decodeTimestampShard({
            ...WORD_SHARD,
            readings: [{ ...WORD_SHARD.readings[0]!, parts: [['112:1', 800, 1500, 1, 2]] }],
        }) as TsWordShardResponse;
        const data = assembleOccasion(
            'r', shardOccasions(shard)[0]!, {}, {}, BY_SURAH, 'chapter.mp3',
        );
        expect(data.words.map((word) => word.location)).toEqual(['112:1:2', '112:1:3']);
        expect(data.wordReadings[0]!.words.map((word) => word.id)).toEqual([1, 2]);
    });
});
