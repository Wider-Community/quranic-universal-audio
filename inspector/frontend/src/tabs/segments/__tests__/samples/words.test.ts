import { describe, expect, it } from 'vitest';

import type { SegWordTiming } from '../../../../lib/types/generated/schemas';
import { activeWordLocation, tokenizeBody } from '../../utils/samples/words';

const VWC = { '11:1': 2, '11:2': 4 };

describe('tokenizeBody', () => {
    it('assigns locations across a verse boundary and skips markers', () => {
        const tokens = tokenizeBody('الٓرۚ كِتَٰبٌ ۝١ أَلَّا تَعْبُدُوٓا۟', '11:1:1-11:2:2', VWC);
        expect(tokens.map((t) => t.location)).toEqual(['11:1:1', '11:1:2', null, '11:2:1', '11:2:2']);
    });

    it('yields null locations for a non-Quran ref', () => {
        expect(tokenizeBody('بِسْمِ ٱللَّهِ', 'Basmala', VWC).every((t) => t.location === null)).toBe(true);
    });
});

describe('activeWordLocation', () => {
    const words: SegWordTiming[] = [
        { word: 'a', location: '11:1:1', start_ms: 1000, end_ms: 2000 },
        { word: 'b', location: '11:1:2', start_ms: 2000, end_ms: 3500 },
    ];
    it('picks the word containing the playhead', () => {
        expect(activeWordLocation(words, 1500)).toBe('11:1:1');
        expect(activeWordLocation(words, 2000)).toBe('11:1:2');
        expect(activeWordLocation(words, 3500)).toBeNull();
        expect(activeWordLocation(words, 500)).toBeNull();
    });
});
