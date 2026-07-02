import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchJson } from '../../../../lib/api';
import type { SegmentEntry, TsShardResponse, TsShardWord } from '../../../../lib/types/ts-client';
import {
    assembleOccasion,
    assembleWaslGroup,
    chapterVerseRefs,
    resolveVbrChaptersForReciter,
    shardOccasions,
    type TsReciterAudio,
    vbrChaptersFromManifest,
} from '../ts_client';

// audio_category is sourced from the manifest's reciter block; the canonical
// per-chapter URL is injected by the caller (resolved from /api/audio/surahs).
const RA_SURAH: TsReciterAudio = { audio_category: 'by_surah' };
const RA_AYAH: TsReciterAudio = { audio_category: 'by_ayah' };

// Canonical URLs the caller would pass in (no longer template-derived).
const CH_URL = 'https://server7.mp3quran.net/s_gmd/001.mp3'; // by_surah chapter file
const AYAH_URL = 'https://everyayah.com/data/Saad_40k/001001.mp3'; // by_ayah verse file

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

/** Resolve the (first) occasion for a verse ref in a freshly-built shard. */
function occasionFor(shard: TsShardResponse, ref: string) {
    const occ = shardOccasions(shard).find((o) => o.ref === ref);
    if (!occ) throw new Error(`no occasion for ${ref}`);
    return occ;
}

function bySurahShard(): TsShardResponse {
    // by_surah: word offsets are absolute file timestamps; the assembler
    // subtracts the occasion's start to make timings relative to playback.
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
// assembleOccasion — canonical audio URL injection
//
// `audio_category` is sourced from the manifest's reciter block; the per-chapter
// URL is the canonical link the caller resolved from /api/audio/surahs and is
// echoed verbatim into `audio_url` (never recomputed from a template). The
// by_surah offset adjustment 0-anchors word times to the occasion's clip start.
// ---------------------------------------------------------------------------

describe('assembleOccasion — canonical audio URL', () => {
    it('uses the injected canonical chapter URL and 0-anchors by_surah words', () => {
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
            segments: [seg('1:1', 5000, 6000, [makeWord(1, 5000, 6000)])],
        };
        const url = 'https://server7.mp3quran.net/shur/001.mp3';
        const result = assembleOccasion('r', occasionFor(shard, '1:1'), fakeQpc, fakeDk, RA_SURAH, url);
        expect(result.audio_url).toBe(url);
        expect(result.audio_category).toBe('by_surah_audio');
        expect(result.time_start_ms).toBe(5000);
        expect(result.words[0]!.start).toBeCloseTo(0);
    });

    it('uses a non-templatable per-chapter URL verbatim (YouTube by_surah)', () => {
        // Regression: a YouTube by_surah delivery has a distinct video id per
        // chapter (no {surah} pattern). The old template path emitted "" here and
        // the waveform blanked; the canonical URL must flow through unchanged.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 2, audio_category: 'by_surah' },
            segments: [seg('2:1', 4000, 12000, [makeWord(1, 4000, 12000)])],
        };
        const url = 'https://www.youtube.com/watch?v=E5sWmvpn0EI';
        const result = assembleOccasion('r', occasionFor(shard, '2:1'), fakeQpc, fakeDk, RA_SURAH, url);
        expect(result.audio_url).toBe(url);
    });
});

// ---------------------------------------------------------------------------
// assembleOccasion — by_ayah path
// ---------------------------------------------------------------------------

describe('assembleOccasion (by_ayah)', () => {
    const shard = byAyahShard();

    it('builds a verse with second-scaled timings, location strings, and intervals', () => {
        const result = assembleOccasion('saad_al_ghamdi', occasionFor(shard, '1:1'), fakeQpc, fakeDk, RA_AYAH, AYAH_URL);
        expect(result.reciter).toBe('saad_al_ghamdi');
        expect(result.chapter).toBe(1);
        expect(result.verse_ref).toBe('1:1');
        expect(result.audio_category).toBe('by_ayah_audio');
        expect(result.audio_url).toBe('https://everyayah.com/data/Saad_40k/001001.mp3');

        // Words: locations + ms→sec + display_text fallback to QPC when DK missing.
        expect(result.words).toHaveLength(2);
        expect(result.words[0]!.location).toBe('1:1:1');
        expect(result.words[0]!.text).toBe('بِسْمِ');
        expect(result.words[0]!.display_text).toBe('بسم[dk]');
        expect(result.words[0]!.start).toBeCloseTo(0);
        expect(result.words[0]!.end).toBeCloseTo(0.8);
        expect(result.words[1]!.display_text).toBe('ٱللَّهِ');

        // Intervals concatenated; phoneme_indices points back into them.
        expect(result.intervals).toHaveLength(3);
        expect(result.intervals[0]).toEqual({ phone: 'b', start: 0, end: 0.2 });
        expect(result.words[0]!.phoneme_indices).toEqual([0, 1]);
        expect(result.words[1]!.phoneme_indices).toEqual([2]);
    });

    it('time_start_ms stays 0 and time_end_ms tracks the occasion span end for by_ayah', () => {
        const result = assembleOccasion('saad_al_ghamdi', occasionFor(shard, '1:1'), fakeQpc, fakeDk, RA_AYAH, AYAH_URL);
        expect(result.time_start_ms).toBe(0);
        expect(result.time_end_ms).toBe(1500); // occasion span end (ms)
    });

    it('has no occasion for an unknown verse ref', () => {
        expect(shardOccasions(byAyahShard()).find((o) => o.ref === '99:99')).toBeUndefined();
    });
});

// ---------------------------------------------------------------------------
// assembleOccasion — by_surah offset adjustment
// ---------------------------------------------------------------------------

describe('assembleOccasion (by_surah)', () => {
    const shard = bySurahShard();

    it('subtracts the occasion start offset from word/letter/interval timings', () => {
        const result = assembleOccasion('saad_al_ghamdi', occasionFor(shard, '1:1'), fakeQpc, fakeDk, RA_SURAH, CH_URL);
        expect(result.audio_category).toBe('by_surah_audio');

        // Verse starts at 5s of the surah file → all timings shift by -5s.
        expect(result.time_start_ms).toBe(5000);
        expect(result.time_end_ms).toBe(7000);

        expect(result.words[0]!.start).toBeCloseTo(0); // 5000 - 5000
        expect(result.words[0]!.end).toBeCloseTo(1.0); // 6000 - 5000
        expect(result.words[1]!.start).toBeCloseTo(1.5); // 6500 - 5000
        expect(result.words[1]!.end).toBeCloseTo(2.0); // 7000 - 5000

        // Letters and intervals should also be shifted.
        expect(result.words[0]!.letters[0]!.start).toBeCloseTo(0);
        expect(result.words[0]!.letters[0]!.end).toBeCloseTo(0.2);
        expect(result.intervals[0]!.start).toBeCloseTo(0);
        expect(result.intervals[0]!.end).toBeCloseTo(0.2);
    });
});

// ---------------------------------------------------------------------------
// assembleOccasion — no dedup (every recited word kept)
//
// The shard stores every recited segment raw; a verse may recur (loopbacks /
// re-dos). One occasion = a contiguous run of same-verse segments; the assembler
// keeps EVERY word of it, and a verse re-recited after a foreign verse splits
// into separate occasions that each assemble independently.
// ---------------------------------------------------------------------------

describe('assembleOccasion — keeps all recited words', () => {
    it('concatenates a single occasion (lead+trail) keeping every word', () => {
        // 2:2 recited as words 1-5 then 6-7: one contiguous occasion (no foreign
        // verse interleaves) — all words kept, in audio order.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 2, audio_category: 'by_surah' },
            segments: [
                seg('2:2', 7450, 11240, [makeWord(1, 7450, 8000), makeWord(5, 10000, 11240)]),
                seg('2:2', 11770, 14920, [makeWord(6, 11770, 13000), makeWord(7, 13000, 14920)]),
            ],
        };
        const result = assembleOccasion('r', occasionFor(shard, '2:2'), fakeQpc, fakeDk, RA_SURAH, CH_URL);
        expect(result.words.map((w) => w.location)).toEqual(['2:2:1', '2:2:5', '2:2:6', '2:2:7']);
        // Clip spans both segments; by_surah 0-anchors to the first start (7450).
        expect(result.time_start_ms).toBe(7450);
        expect(result.time_end_ms).toBe(14920);
    });

    it('splits a foreign-interleaved re-do into two occasions, each kept verbatim', () => {
        // 1:1 take A, then 1:2 (breaks the run), then 1:1 take B → two 1:1 occasions.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_ayah' },
            segments: [
                seg('1:1', 0, 1000, [makeWord(1, 0, 500), makeWord(2, 500, 1000)]),
                seg('1:2', 1000, 1500, [makeWord(1, 1000, 1500)]),
                seg('1:1', 1500, 2500, [makeWord(1, 1500, 2000), makeWord(2, 2000, 2500)]),
            ],
        };
        const takes = shardOccasions(shard).filter((o) => o.ref === '1:1');
        expect(takes).toHaveLength(2);

        const a = assembleOccasion('r', takes[0]!, fakeQpc, fakeDk, RA_AYAH, AYAH_URL);
        expect(a.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2']);
        expect(a.time_end_ms).toBe(1000);

        const b = assembleOccasion('r', takes[1]!, fakeQpc, fakeDk, RA_AYAH, AYAH_URL);
        expect(b.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2']);
        expect(b.time_end_ms).toBe(2500);
    });

    it('keeps a consecutive back-to-back repeat as both takes (no trim)', () => {
        // 1:1 (words 1-2) recited twice, consecutively — a single occasion. Both
        // takes are kept; the clip spans the whole occasion.
        const shard: TsShardResponse = {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
            segments: [
                seg('1:1', 5000, 6000, [makeWord(1, 5000, 5500), makeWord(2, 5500, 6000)]),
                seg('1:1', 6500, 7500, [makeWord(1, 6500, 7000), makeWord(2, 7000, 7500)]),
            ],
        };
        const result = assembleOccasion('r', occasionFor(shard, '1:1'), fakeQpc, fakeDk, RA_SURAH, CH_URL);
        expect(result.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2', '1:1:1', '1:1:2']);
        expect(result.time_start_ms).toBe(5000);
        expect(result.time_end_ms).toBe(7500);
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

// ---------------------------------------------------------------------------
// assembleWaslGroup — cross-verse context merge
//
// A chain of occasions recited into each other is merged into one TsVerseData:
// words concatenated in recitation order keeping per-verse locations, share_group
// ids running across members (no collision), one span / by_surah 0-anchor.
// ---------------------------------------------------------------------------

describe('assembleWaslGroup', () => {
    /** A word with one indexable phone + one cell carrying `shareGroup` (the cell
     *  row's index-6 slot), so we can assert cross-member share_group offsetting. */
    function wordCell(idx: number, start: number, end: number, phone: string, sg: number): TsShardWord {
        return [
            idx, start, end,
            [[phone, start, end]],
            [[phone, start, end]],
            [[[phone], 'base', 'present', [0], 0, null, sg]],
        ] as unknown as TsShardWord;
    }

    /** Two adjacent verses as separate occasions (a waṣl chain), by_surah. Each
     *  verse's cells restart share_group at 0 (per-segment numbering). */
    function groupShard(): TsShardResponse {
        return {
            _meta: { schema_version: 2, chapter: 1, audio_category: 'by_surah' },
            segments: [
                seg('1:1', 5000, 7000, [
                    wordCell(1, 5000, 6000, 'a', 0),
                    wordCell(2, 6000, 7000, 'b', 0),
                ]),
                seg('1:2', 7000, 8000, [wordCell(1, 7000, 8000, 'c', 0)]),
            ],
        };
    }

    const fakeQpcG = {
        '1:1:1': { text: 'و1' }, '1:1:2': { text: 'و2' }, '1:2:1': { text: 'و3' },
    };

    function members() {
        const shard = groupShard();
        const occs = shardOccasions(shard);
        return [occasionFor(shard, '1:1'), occasionFor(shard, '1:2'), occs] as const;
    }

    it('concatenates members keeping each word its own verse location', () => {
        const [o1, o2] = members();
        const g = assembleWaslGroup('r', [o1, o2], '1:1', fakeQpcG, {}, RA_SURAH, CH_URL);
        expect(g.words.map((w) => w.location)).toEqual(['1:1:1', '1:1:2', '1:2:1']);
        expect(g.verse_ref).toBe('1:1');
        // Intervals flat across both verses; each word indexes into them.
        expect(g.intervals.map((iv) => iv.phone)).toEqual(['a', 'b', 'c']);
        expect(g.words[2]!.phoneme_indices).toEqual([2]);
    });

    it('runs share_group ids across members so the two verses do not collide', () => {
        const [o1, o2] = members();
        const g = assembleWaslGroup('r', [o1, o2], '1:1', fakeQpcG, {}, RA_SURAH, CH_URL);
        // Verse 1:1 (one segment) → base 0; verse 1:2 (next segment) → base 1.
        expect(g.words[0]!.cells![0]!.shareGroup).toBe(0);
        expect(g.words[1]!.cells![0]!.shareGroup).toBe(0);
        expect(g.words[2]!.cells![0]!.shareGroup).toBe(1);
    });

    it('spans the whole group and 0-anchors by_surah times to the group start', () => {
        const [o1, o2] = members();
        const g = assembleWaslGroup('r', [o1, o2], '1:1', fakeQpcG, {}, RA_SURAH, CH_URL);
        expect(g.time_start_ms).toBe(5000);
        expect(g.time_end_ms).toBe(8000);
        expect(g.words[0]!.start).toBeCloseTo(0); // 5000 - 5000
        expect(g.words[2]!.end).toBeCloseTo(3.0); // 8000 - 5000
    });

    it('is identical to assembleOccasion for a single member', () => {
        const [o1] = members();
        const group = assembleWaslGroup('r', [o1], '1:1', fakeQpcG, {}, RA_SURAH, CH_URL);
        const occ = assembleOccasion('r', o1, fakeQpcG, {}, RA_SURAH, CH_URL);
        expect(group).toEqual(occ);
    });
});
