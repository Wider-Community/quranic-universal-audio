/**
 * Filmstrip cell model — recitation-correct geometry + per-verse word fractions.
 *
 * The ayah filmstrip is a verse ruler driven by the actual recitation. This
 * derives, from the chapter's deduped `units`, one `VerseCell` per ayah (in
 * reading order) carrying:
 *   - `canonDurSec` — the verse's canonical recited length (sum of each word's
 *     FIRST-occurrence duration), used to SIZE the cell. Never inflated by a
 *     loopback's later occurrence (unlike `AyahBoundary.endMs = max(end)`).
 *   - `words` — a fraction table: each word's `[frac0, frac1)` position within
 *     the verse, so the active cell's progress bar fills to the recited WORD's
 *     position (and loops back proportionally on a within-verse repeat) instead
 *     of growing with elapsed clock time.
 *
 * Plus reverse lookups (`indexByAyahKey`, `cellOfUnit`) so the playback loop can
 * go active-unit → cell in O(1). Built once per chapter. Pure; no fetch/tab
 * imports. Times are seconds (matching `AnimUnit`).
 */

import { ayahUnitRanges } from './chapter-words';
import type { AnimUnit } from './types';

/** Weighting for a word's share of its verse's progress bar.
 *  `duration` (default) = canonical word length; `equal` = one slot per word. */
export type WordWeighting = 'duration' | 'equal';

/** A word's position within its verse, as a half-open fraction range. */
export interface WordFrac {
    /** Global index into `units`. */
    unitIdx: number;
    /** Word index within the ayah (1-based, from the shard). */
    word: number;
    frac0: number;
    frac1: number;
}

/** One verse cell — geometry source + word-fraction table. */
export interface VerseCell {
    ayahKey: string;
    surah: number;
    ayah: number;
    /** Canonical recited duration (seconds) — sum of word first-occurrence
     *  durations. Drives cell WIDTH regardless of `weighting`. */
    canonDurSec: number;
    /** [start, end) global unit-index range for the verse (reading order). */
    unitStart: number;
    unitEnd: number;
    /** Word-fraction table, ordered by word (= reading order within the verse). */
    words: WordFrac[];
    /** Canonical first-occurrence start (seconds) — the click/drag seek target. */
    canonStartSec: number;
}

export interface FilmstripModel {
    cells: VerseCell[];
    /** ayahKey → cell index. */
    indexByAyahKey: Map<string, number>;
    /** Global unitIdx → cell index (−1 for none, though every unit maps). */
    cellOfUnit: Int32Array;
}

const EMPTY_MODEL: FilmstripModel = {
    cells: [],
    indexByAyahKey: new Map(),
    cellOfUnit: new Int32Array(0),
};

/** Each word's canonical duration = its FIRST occurrence's span (seconds). A
 *  repeat re-emits the word with a new interval, but the first is the canonical
 *  reading-order length; `>= eps` so a zero-length word still gets a slot. */
function canonDur(u: AnimUnit): number {
    const iv = u.intervals[0];
    if (!iv) return 0.001;
    return Math.max(0.001, iv.end - iv.start);
}

/**
 * Build the filmstrip cell model from the chapter's deduped units.
 *
 * @param units    deduped `AnimUnit[]` in reading order (from `buildChapterRecitation`)
 * @param weighting word-fraction weighting (`duration` default, `equal` swappable)
 */
export function buildFilmstripModel(
    units: AnimUnit[],
    weighting: WordWeighting,
): FilmstripModel {
    if (!units.length) return EMPTY_MODEL;

    const cells: VerseCell[] = [];
    const indexByAyahKey = new Map<string, number>();
    const cellOfUnit = new Int32Array(units.length).fill(-1);

    // `ayahUnitRanges` preserves reading order and assumes each ayah's units are
    // contiguous (true for the deduped reading-order list).
    for (const [ayahKey, [unitStart, unitEnd]] of ayahUnitRanges(units)) {
        const head = units[unitStart]!;
        let canonDurSec = 0;
        let total = 0;
        for (let i = unitStart; i < unitEnd; i++) {
            const d = canonDur(units[i]!);
            canonDurSec += d;
            total += weighting === 'equal' ? 1 : d;
        }
        if (total <= 0) total = 1; // degenerate guard (all-zero weights)

        const words: WordFrac[] = [];
        let cum = 0;
        for (let i = unitStart; i < unitEnd; i++) {
            const u = units[i]!;
            const wgt = weighting === 'equal' ? 1 : canonDur(u);
            const frac0 = cum / total;
            cum += wgt;
            words.push({ unitIdx: i, word: u.word, frac0, frac1: cum / total });
            cellOfUnit[i] = cells.length;
        }

        indexByAyahKey.set(ayahKey, cells.length);
        cells.push({
            ayahKey,
            surah: head.surah,
            ayah: head.ayah,
            canonDurSec,
            unitStart,
            unitEnd,
            words,
            canonStartSec: head.intervals[0]?.start ?? head.start,
        });
    }

    return { cells, indexByAyahKey, cellOfUnit };
}
