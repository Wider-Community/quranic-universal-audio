import { describe, expect, it } from 'vitest';

import { assembleOccasion, shardOccasions, type TsReciterAudio } from '../ts-source';
import { nativeReading, nativeShard } from '../test-native-fixture';

const audio: TsReciterAudio = { audio_category: 'by_surah' };

describe('native source-unit animation rows', () => {
    it('uses letter-unit timing directly and preserves truly untimed marks', () => {
        const reading = nativeReading('r1', [{ ref: '2:1', start: 0, end: 300 }]);
        reading.source.source.units = [
            { id: 10, word_id: 0, text: 'ب', kind: 'letter', owned_sound_ids: [0], presented_sound_ids: [] },
            { id: 11, word_id: 0, text: 'ا', kind: 'letter', owned_sound_ids: [], presented_sound_ids: [] },
            { id: 12, word_id: 0, text: 'َ', kind: 'mark', owned_sound_ids: [], presented_sound_ids: [] },
        ];
        reading.timing.units = [
            { source_unit_id: 10, start_ms: 0, end_ms: 300 },
            { source_unit_id: 11, start_ms: null, end_ms: null },
            { source_unit_id: 12, start_ms: null, end_ms: null },
        ];
        const occasion = shardOccasions(nativeShard([reading]))[0]!;
        const data = assembleOccasion('r', occasion, {}, {}, audio, '');
        expect(data.words[0]!.letters).toEqual([
            { char: 'ب', start: 0, end: 0.3, silent: false },
            { char: 'ا', start: null, end: null, silent: true },
        ]);
    });
});
