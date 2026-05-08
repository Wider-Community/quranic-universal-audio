import { describe, expect, it } from 'vitest';

import type { TsShardResponse, TsShardWord } from '../../../../lib/types/api';
import { assembleVerseFromShard, audioUrlFor, chapterVerseRefs } from '../ts_client';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeWord(
    idx: number,
    startMs: number,
    endMs: number,
    letters: Array<[string, number | null, number | null]> = [],
    phones: Array<(string | number | boolean)[]> = [],
): TsShardWord {
    return [idx, startMs, endMs, letters, phones];
}

function bySurahShard(): TsShardResponse {
    // by_surah: word offsets are absolute file timestamps; ts_client
    // subtracts the verse's start to make timings relative to playback.
    return {
        _meta: {
            schema_version: 1,
            reciter: 'saad_al_ghamdi',
            chapter: 1,
            audio_category: 'by_surah',
            url_template: 'server7.mp3quran.net/s_gmd/{surah:03d}.mp3',
        },
        '1:1': {
            words: [
                makeWord(1, 5000, 6000,
                    [['ب', 5000, 5200], ['س', 5200, 5500], ['م', 5500, 6000]],
                    [['b', 5000, 5200], ['s', 5200, 5500], ['m', 5500, 6000]],
                ),
                makeWord(2, 6500, 7000,
                    [['ا', 6500, 6700], ['ل', 6700, 7000]],
                    [['a', 6500, 6700], ['l', 6700, 7000]],
                ),
            ],
        },
    };
}

function byAyahShard(): TsShardResponse {
    return {
        _meta: {
            schema_version: 1,
            reciter: 'saad_al_ghamdi',
            chapter: 1,
            audio_category: 'by_ayah',
            url_template: 'everyayah.com/data/Saad_40k/{surah:03d}{ayah:03d}.mp3',
        },
        '1:1': {
            words: [
                makeWord(1, 0, 800, [['ب', 0, 200]], [['b', 0, 200], ['s', 200, 800]]),
                makeWord(2, 850, 1500, [['ا', 850, 1100]], [['a', 850, 1100]]),
            ],
        },
    };
}

const fakeQpc = {
    '1:1:1': { text: 'بِسْمِ' },
    '1:1:2': { text: 'ٱللَّهِ' },
    '37:151:3': { text: 'ثَلَاثٌ' },
    '37:152:1': { text: 'مَا' },
    '37:152:2': { text: 'كَانَ' },
};

const fakeDk = {
    '1:1:1': { text: 'بسم[dk]' },
    '37:151:3': { text: 'ثلاث[dk]' },
};

// ---------------------------------------------------------------------------
// audioUrlFor
// ---------------------------------------------------------------------------

describe('audioUrlFor', () => {
    it('expands by_surah templates with zero-padded surah', () => {
        const meta: TsShardResponse['_meta'] = {
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_surah',
            url_template: 'server7.mp3quran.net/s_gmd/{surah:03d}.mp3',
        };
        expect(audioUrlFor(meta, 1, 1)).toBe('https://server7.mp3quran.net/s_gmd/001.mp3');
        expect(audioUrlFor(meta, 36, 1)).toBe('https://server7.mp3quran.net/s_gmd/036.mp3');
    });

    it('expands by_ayah templates with both zero-padded fields', () => {
        const meta: TsShardResponse['_meta'] = {
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_ayah',
            url_template: 'everyayah.com/data/X/{surah:03d}{ayah:03d}.mp3',
        };
        expect(audioUrlFor(meta, 2, 7)).toBe('https://everyayah.com/data/X/002007.mp3');
    });

    it('preserves an existing https:// prefix in the template', () => {
        const meta: TsShardResponse['_meta'] = {
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_surah',
            url_template: 'https://example.com/{surah}.mp3',
        };
        expect(audioUrlFor(meta, 5, 1)).toBe('https://example.com/5.mp3');
    });

    it('falls back to per-verse audio_urls when template is empty', () => {
        const meta: TsShardResponse['_meta'] = {
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_ayah',
            url_template: '',
            audio_urls: { '1:1': 'https://x/1-1.mp3', '1:2': 'https://x/1-2.mp3' },
        };
        expect(audioUrlFor(meta, 1, 1)).toBe('https://x/1-1.mp3');
        expect(audioUrlFor(meta, 1, 2)).toBe('https://x/1-2.mp3');
    });

    it('falls back to chapter-keyed by_surah audio_urls when present', () => {
        const meta: TsShardResponse['_meta'] = {
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_surah',
            url_template: '',
            audio_urls: { '1': 'https://x/001.mp3' },
        };
        expect(audioUrlFor(meta, 1, 5)).toBe('https://x/001.mp3');
    });

    it('returns empty string when neither template nor fallback is set', () => {
        expect(audioUrlFor({
            schema_version: 1, reciter: 'r', chapter: 1, audio_category: 'by_ayah',
            url_template: '',
        }, 1, 1)).toBe('');
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — by_ayah path
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard (by_ayah)', () => {
    const shard = byAyahShard();

    it('builds a verse with second-scaled timings, location strings, and intervals', () => {
        const result = assembleVerseFromShard(shard, '1:1', fakeQpc, fakeDk);
        expect(result).not.toBeNull();
        expect(result!.reciter).toBe('saad_al_ghamdi');
        expect(result!.chapter).toBe(1);
        expect(result!.verse_ref).toBe('1:1');
        expect(result!.audio_category).toBe('by_ayah_audio');
        expect(result!.audio_url).toBe('https://everyayah.com/data/Saad_40k/001001.mp3');

        // Words: locations + ms→sec + display_text fallback to QPC when DK missing.
        expect(result!.words).toHaveLength(2);
        expect(result!.words[0]!.location).toBe('1:1:1');
        expect(result!.words[0]!.text).toBe('بِسْمِ');
        expect(result!.words[0]!.display_text).toBe('بسم[dk]');
        expect(result!.words[0]!.start).toBeCloseTo(0);
        expect(result!.words[0]!.end).toBeCloseTo(0.8);
        expect(result!.words[1]!.display_text).toBe('ٱللَّهِ');

        // Intervals concatenated; phoneme_indices points back into them.
        expect(result!.intervals).toHaveLength(3);
        expect(result!.intervals[0]).toEqual({ phone: 'b', start: 0, end: 0.2 });
        expect(result!.words[0]!.phoneme_indices).toEqual([0, 1]);
        expect(result!.words[1]!.phoneme_indices).toEqual([2]);
    });

    it('time_start_ms stays 0 and time_end_ms tracks the last interval for by_ayah', () => {
        const result = assembleVerseFromShard(shard, '1:1', fakeQpc, fakeDk);
        expect(result!.time_start_ms).toBe(0);
        expect(result!.time_end_ms).toBe(1100); // last interval end (ms)
    });

    it('returns null for an unknown verse ref', () => {
        expect(assembleVerseFromShard(shard, '99:99', fakeQpc, fakeDk)).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — by_surah offset adjustment
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard (by_surah)', () => {
    const shard = bySurahShard();

    it('subtracts the verse start offset from word/letter/interval timings', () => {
        const result = assembleVerseFromShard(shard, '1:1', fakeQpc, fakeDk);
        expect(result!.audio_category).toBe('by_surah_audio');

        // Verse starts at 5s of the surah file → all timings shift by -5s.
        expect(result!.time_start_ms).toBe(5000);
        expect(result!.time_end_ms).toBe(7000);

        expect(result!.words[0]!.start).toBeCloseTo(0); // 5000 - 5000
        expect(result!.words[0]!.end).toBeCloseTo(1.0); // 6000 - 5000
        expect(result!.words[1]!.start).toBeCloseTo(1.5); // 6500 - 5000
        expect(result!.words[1]!.end).toBeCloseTo(2.0); // 7000 - 5000

        // Letters and intervals should also be shifted.
        expect(result!.words[0]!.letters[0]!.start).toBeCloseTo(0);
        expect(result!.words[0]!.letters[0]!.end).toBeCloseTo(0.2);
        expect(result!.intervals[0]!.start).toBeCloseTo(0);
        expect(result!.intervals[0]!.end).toBeCloseTo(0.2);
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — compound refs (cross-verse segments)
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard (compound refs)', () => {
    it('walks ayahs by detecting word_idx wrap and uses surah:ayah:word locations', () => {
        const compound: TsShardResponse = {
            _meta: {
                schema_version: 1,
                reciter: 'r',
                chapter: 37,
                audio_category: 'by_ayah',
                url_template: 'example.com/{surah:03d}{ayah:03d}.mp3',
            },
            '37:151:3-37:152:2': {
                words: [
                    // Tail of ayah 151, last 2 words.
                    makeWord(3, 0, 500),
                    // Wrap → ayah 152 from word 1.
                    makeWord(1, 600, 900),
                    makeWord(2, 950, 1300),
                ],
            },
        };

        const result = assembleVerseFromShard(compound, '37:151:3-37:152:2', fakeQpc, fakeDk);
        expect(result).not.toBeNull();
        expect(result!.verse_ref).toBe('37:151:3-37:152:2');
        expect(result!.words.map((w) => w.location)).toEqual([
            '37:151:3', '37:152:1', '37:152:2',
        ]);
        expect(result!.words[0]!.display_text).toBe('ثلاث[dk]'); // DK present
        expect(result!.words[1]!.text).toBe('مَا'); // QPC fallback
        // Audio URL uses the start tuple's surah/ayah.
        expect(result!.audio_url).toBe('https://example.com/037151.mp3');
    });
});

// ---------------------------------------------------------------------------
// chapterVerseRefs
// ---------------------------------------------------------------------------

describe('chapterVerseRefs', () => {
    it('lists verse keys excluding _meta, preserving insertion order', () => {
        const shard: TsShardResponse = {
            _meta: {
                schema_version: 1, reciter: 'r', chapter: 1,
                audio_category: 'by_ayah', url_template: '',
            },
            '1:1': { words: [] },
            '1:2': { words: [] },
            '1:3': { words: [] },
        };
        expect(chapterVerseRefs(shard)).toEqual(['1:1', '1:2', '1:3']);
    });
});
