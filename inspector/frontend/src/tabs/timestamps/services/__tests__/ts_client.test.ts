import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchJson } from '../../../../lib/api';
import type { SegmentEntry, TsShardResponse, TsShardWord } from '../../../../lib/types/api';
import {
    assembleVerseFromShard,
    chapterVerseRefs,
    resolveVbrChaptersForReciter,
    type TsReciterAudio,
    vbrChaptersFromManifest,
} from '../ts_client';

// Audio routing is sourced from the manifest's reciter block — these helpers
// build the same data the production code passes in.
const RA_SURAH: TsReciterAudio = {
    audio_category: 'by_surah',
    url_template: 'server7.mp3quran.net/s_gmd/{surah:03d}.mp3',
};
const RA_AYAH: TsReciterAudio = {
    audio_category: 'by_ayah',
    url_template: 'everyayah.com/data/Saad_40k/{surah:03d}{ayah:03d}.mp3',
};

vi.mock('../../../../lib/api', () => ({
    fetchArrayBuffer: vi.fn(),
    fetchJson: vi.fn(),
}));

beforeEach(() => {
    vi.mocked(fetchJson).mockReset();
});

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

function seg(ref: string, startMs: number, endMs: number, words: TsShardWord[]): SegmentEntry {
    return { ref, t: [startMs, endMs], words };
}

function bySurahShard(): TsShardResponse {
    // by_surah: word offsets are absolute file timestamps; ts_client
    // subtracts the verse's start to make timings relative to playback.
    return {
        _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
        segments: [
            seg('1:1', 5000, 7000, [
                makeWord(1, 5000, 6000,
                    [['ب', 5000, 5200], ['س', 5200, 5500], ['م', 5500, 6000]],
                    [['b', 5000, 5200], ['s', 5200, 5500], ['m', 5500, 6000]],
                ),
                makeWord(2, 6500, 7000,
                    [['ا', 6500, 6700], ['ل', 6700, 7000]],
                    [['a', 6500, 6700], ['l', 6700, 7000]],
                ),
            ]),
        ],
    };
}

function byAyahShard(): TsShardResponse {
    return {
        _meta: { schema_version: 2, chapter: 1, audio_category: 'by_ayah' },
        segments: [
            seg('1:1', 0, 1500, [
                makeWord(1, 0, 800, [['ب', 0, 200]], [['b', 0, 200], ['s', 200, 800]]),
                makeWord(2, 850, 1500, [['ا', 850, 1100]], [['a', 850, 1100]]),
            ]),
        ],
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
// assembleVerseFromShard — audio routing from the manifest
//
// Audio routing (url_template + audio_category) is sourced from the manifest's
// reciter block, never the shard's slim `_meta` (which carries no audio fields).
// The by_surah offset adjustment 0-anchors word times to the verse's clip start.
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard — audio routing from manifest', () => {
    it('templates the audio URL from the manifest and 0-anchors by_surah words', () => {
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
            segments: [seg('1:1', 5000, 6000, [makeWord(1, 5000, 6000)])],
        };
        const reciterAudio: TsReciterAudio = {
            audio_category: 'by_surah',
            url_template: 'server7.mp3quran.net/shur/{surah:03d}.mp3',
        };
        const result = assembleVerseFromShard('r', shard, '1:1', fakeQpc, fakeDk, reciterAudio);
        expect(result).not.toBeNull();
        expect(result!.audio_url).toBe('https://server7.mp3quran.net/shur/001.mp3');
        expect(result!.audio_category).toBe('by_surah_audio');
        expect(result!.time_start_ms).toBe(5000);
        expect(result!.words[0]!.start).toBeCloseTo(0);
    });

    it('returns an empty audio_url when the manifest template is empty', () => {
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_ayah' },
            segments: [seg('1:1', 0, 500, [makeWord(1, 0, 500)])],
        };
        const reciterAudio: TsReciterAudio = { audio_category: 'by_ayah', url_template: '' };
        const result = assembleVerseFromShard('r', shard, '1:1', fakeQpc, fakeDk, reciterAudio);
        expect(result!.audio_url).toBe('');
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — by_ayah path
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard (by_ayah)', () => {
    const shard = byAyahShard();

    it('builds a verse with second-scaled timings, location strings, and intervals', () => {
        const result = assembleVerseFromShard('saad_al_ghamdi', shard, '1:1', fakeQpc, fakeDk, RA_AYAH);
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

    it('time_start_ms stays 0 and time_end_ms tracks the segment span end for by_ayah', () => {
        const result = assembleVerseFromShard('saad_al_ghamdi', shard, '1:1', fakeQpc, fakeDk, RA_AYAH);
        expect(result!.time_start_ms).toBe(0);
        expect(result!.time_end_ms).toBe(1500); // segment span end (ms)
    });

    it('returns null for an unknown verse ref', () => {
        expect(assembleVerseFromShard('saad_al_ghamdi', shard, '99:99', fakeQpc, fakeDk, RA_AYAH)).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — by_surah offset adjustment
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard (by_surah)', () => {
    const shard = bySurahShard();

    it('subtracts the verse start offset from word/letter/interval timings', () => {
        const result = assembleVerseFromShard('saad_al_ghamdi', shard, '1:1', fakeQpc, fakeDk, RA_SURAH);
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
// assembleVerseFromShard — loopback occasion dedup
//
// The shard stores every recited segment raw; a verse may recur (loopbacks /
// re-dos). The assembler reduces a verse to its canonical (completing) occasion.
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard — loopback occasion dedup', () => {
    it('concatenates a single occasion (lead+trail) into one canonical clip', () => {
        // 2:2 recited as words 1-5 then 6-7 (a `lead+trail` loopback): one
        // contiguous occasion (no foreign verse interleaves) — all words kept.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 2, audio_category: 'by_surah' },
            segments: [
                seg('2:2', 7450, 11240, [makeWord(1, 7450, 8000), makeWord(5, 10000, 11240)]),
                seg('2:2', 11770, 14920, [makeWord(6, 11770, 13000), makeWord(7, 13000, 14920)]),
            ],
        };
        const result = assembleVerseFromShard('r', shard, '2:2', fakeQpc, fakeDk, RA_SURAH);
        expect(result).not.toBeNull();
        expect(result!.words.map((w) => w.location)).toEqual([
            '2:2:1', '2:2:5', '2:2:6', '2:2:7',
        ]);
        // Clip spans both segments; by_surah 0-anchors to the first start (7450).
        expect(result!.time_start_ms).toBe(7450);
        expect(result!.time_end_ms).toBe(14920);
    });

    it('picks one completing occasion when a foreign verse interleaves a re-do', () => {
        // 1:1 take A, then 1:2 (breaks the run), then 1:1 take B. With no
        // confidence join client-side, the EARLIEST completing occasion (A) wins.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_ayah' },
            segments: [
                seg('1:1', 0, 1000, [makeWord(1, 0, 500), makeWord(2, 500, 1000)]),
                seg('1:2', 1000, 1500, [makeWord(1, 1000, 1500)]),
                seg('1:1', 1500, 2500, [makeWord(1, 1500, 2000), makeWord(2, 2000, 2500)]),
            ],
        };
        const result = assembleVerseFromShard('r', shard, '1:1', fakeQpc, fakeDk, RA_AYAH);
        expect(result!.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2']);
        // Occasion A spans 0-1000.
        expect(result!.time_end_ms).toBe(1000);
    });
});

// ---------------------------------------------------------------------------
// assembleVerseFromShard — consecutive-repeat dedup
//
// A verse recited several times back-to-back is one occasion (no foreign verse
// interleaves). The canonical clip trims post-completion takes to one clean take.
// ---------------------------------------------------------------------------

describe('assembleVerseFromShard — consecutive repeats', () => {
    // 1:1 (words 1-2) recited twice, consecutively — a single occasion.
    function consecutiveRepeatShard(): TsShardResponse {
        return {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
            segments: [
                seg('1:1', 5000, 6000, [makeWord(1, 5000, 5500), makeWord(2, 5500, 6000)]),
                seg('1:1', 6500, 7500, [makeWord(1, 6500, 7000), makeWord(2, 7000, 7500)]),
            ],
        };
    }

    it('trims the repeat to one take (canonical clip)', () => {
        const shard = consecutiveRepeatShard();
        const result = assembleVerseFromShard('r', shard, '1:1', fakeQpc, fakeDk, RA_SURAH);
        expect(result!.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2']);
        // Clip ends at the first take's end (6000); take 2 is dropped.
        expect(result!.time_start_ms).toBe(5000);
        expect(result!.time_end_ms).toBe(6000);
    });
});

// ---------------------------------------------------------------------------
// chapterVerseRefs
// ---------------------------------------------------------------------------

describe('chapterVerseRefs', () => {
    it('lists distinct verse refs in recitation order (a verse appears once)', () => {
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_ayah' },
            segments: [
                seg('1:1', 0, 1000, [makeWord(1, 0, 1000)]),
                seg('1:2', 1000, 2000, [makeWord(1, 1000, 2000)]),
                // 1:1 recited again later (loopback) — still one ref in the list.
                seg('1:1', 2000, 3000, [makeWord(1, 2000, 3000)]),
                seg('1:3', 3000, 4000, [makeWord(1, 3000, 4000)]),
            ],
        };
        expect(chapterVerseRefs(shard)).toEqual(['1:1', '1:2', '1:3']);
    });
});

// ---------------------------------------------------------------------------
// VBR chapter metadata
// ---------------------------------------------------------------------------

describe('VBR chapter metadata', () => {
    it('reads sorted vbr_chapters from the manifest when present', () => {
        const manifest = {
            reciters: { r: { vbr_chapters: [7, 2] } },
        } as any;

        expect(vbrChaptersFromManifest(manifest, 'r')).toEqual([2, 7]);
    });

    it('falls back to /api/ts/vbr when the manifest predates vbr_chapters', async () => {
        vi.mocked(fetchJson).mockResolvedValue({ vbr_chapters: [4, 1] });
        const manifest = { reciters: { r: {} } } as any;

        await expect(resolveVbrChaptersForReciter('r', manifest)).resolves.toEqual([1, 4]);
        expect(fetchJson).toHaveBeenCalledWith('/api/ts/vbr/r');
    });
});
