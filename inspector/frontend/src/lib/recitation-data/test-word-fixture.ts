/**
 * A word-profile (non-Hafs) shard fixture, shared by the decode, assembly and
 * row-render suites so the three never drift apart.
 *
 * Al-Ikhlas in Qalun: four words, a waṣl into the next verse and one real stop
 * with a verse end — enough geometry to exercise every branch the word row has.
 */

const AR = ['قُلْ', 'هُوَ', 'ٱللَّهُ', 'أَحَدٌ'];

/** Raw stored shape — feed to `decodeTimestampShard`, never to the assemblers. */
export const WORD_SHARD = {
    _meta: {
        schema_version: 14,
        profile: 'word',
        chapter: 112,
        audio_category: 'by_surah',
        riwayah: 'qalun',
        edition_id: 'qalun-v21+sdk-words-v1',
        words_sha256: 'a'.repeat(64),
        timing_provider: 'hafs_proxy_mfa',
        reference_riwayah: 'hafs',
        reference_id: 'qul-text-qpc-hafs-312',
    },
    readings: [
        {
            id: 'r1',
            parts: [['112:1', 0, 3000, 0, 4]],
            words: [
                ['112:1:1', AR[0], 0, 700],
                ['112:1:2', AR[1], 800, 1500],
                ['112:1:3', AR[2], 1500, 2200],
                ['112:1:4', AR[3], 2200, 2900],
            ],
            // join, join, join, stop-at-the-end-of-verse-1
            boundaries: [[1, null], [1, null], [1, null], [3, 1]],
        },
    ],
};

export const WORD_TEXTS = AR;
