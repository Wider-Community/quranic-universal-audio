/**
 * DK (DigitalKhatt) script vocabulary for the Timestamps analysis row — the
 * single home for the diacritic codepoints + the glyph-form maps the renderer
 * derives from a cell's `tag` + `chars`. Per the phonemizer's design principle
 * (cells carry canonical domain only — no script/visual detail), the *renderer*
 * owns these script conventions; this keeps them out of the component body.
 */

import type { TajweedRule } from '../../../lib/types/generated/schemas';

// --- diacritic codepoints ----------------------------------------------------
export const FATHA = 'َ'; // U+064E
export const DAMMA = 'ُ'; // U+064F
export const KASRA = 'ِ'; // U+0650
export const FATHATAN = 'ً'; // U+064B
export const DAMMATAN = 'ٌ'; // U+064C
export const KASRATAN = 'ٍ'; // U+064D
export const SUKUN = 'ْ'; // U+0652
export const SHADDA = 'ّ'; // U+0651
export const DAGGER = 'ٰ'; // U+0670 dagger-alef
export const ALEF = 'ا'; // U+0627
export const ALEF_MAKSURA = 'ى'; // U+0649
export const MADDAH = 'ٓ'; // U+0653 maddah-above — the silah-madd mark
/** U+06E0 small high upright rectangular zero — the seven alifs (أَنَا۠). It is
 *  written on the alif before it and never opens a written unit of its own. */
export const PAUSAL_ZERO = '۠';
export const NOON = 'ن'; // U+0646
export const MEEM = 'م'; // U+0645
/** Mini-meem glyphs the phonemizer stamps onto an iqlab tanwīn's own meem cell —
 *  MEEM_HI for a ḍamma/fatḥa source, MEEM_LO for a kasra source. `cellGlyph`
 *  always DISPLAYS the low-meem glyph (cleaner than the isolated high-meem), but
 *  `pushSmall` slots + calibrates by the source mark — MEEM_HI → above (6e2),
 *  MEEM_LO → below (6ed) via `BELOW_MARKS`. Kept here as the single script home. */
export const MEEM_HI = 'ۢ'; // U+06E2 mini-meem, ḍamma/fatḥa source → above slot
export const MEEM_LO = 'ۭ'; // U+06ED mini-meem, kasra source → below slot

/** Marks that pin to the BELOW edge of the letter row (others pin top). */
export const BELOW_MARKS = new Set([KASRA, KASRATAN, MEEM_LO]);

/** Open (parallel) tanwīn forms — DK encodes them as distinct codepoints
 *  (U+08F0–08F2). The canonical char alone renders STACKED; map to the open
 *  codepoint when the tanwīn assimilates into the next word. */
export const OPEN_TANWEEN: Record<string, string> = {
    [FATHATAN]: 'ࣰ',
    [DAMMATAN]: 'ࣱ',
    [KASRATAN]: 'ࣲ',
};

/** Rules whose tanwīn assimilates → render the OPEN form (else stacked). Consulted
 *  only for a `tanween` cell, so the noon half of each rule never reaches it. The
 *  literal array is typed against `TajweedRule` so a rename is a compile error. */
const OPEN_TANWEEN_RULES: readonly TajweedRule[] = [
    'idgham_bi_ghunnah',
    'idgham_bila_ghunnah',
    'ikhfaa',
];
export const OPEN_TANWEEN_TAGS: ReadonlySet<string> = new Set(OPEN_TANWEEN_RULES);

/** First combining mark of `chars`, skipping a leading shadda (shadda+haraka
 *  composed → the second mark is the haraka). */
export function firstMark(chars: string): string {
    if (!chars) return '';
    const arr = [...chars];
    if (arr[0] === SHADDA && arr[1]) return arr[1];
    return arr[0]!;
}

/** The glyph for a length the rasm writes no letter for. The producer gives the
 *  letter the reading writes; a mushaf draws that alef DAGGER-sized where it only
 *  lengthens the ḥaraka it sits on (ٱللَّه, مِهَـٰد) and full where it stands in for
 *  a tanwīn a stop replaced (بِنَآءَا) — the seat's own status says which, and
 *  that is the only change made here. */
export function insertedLengthGlyph(chars: string, seatReplaced: boolean): string {
    return chars === ALEF && !seatReplaced ? DAGGER : chars;
}

/** Pin slot for a small cell's mark — top unless it's a below-mark. */
export function cellSlot(glyph: string): 'top' | 'bottom' {
    return BELOW_MARKS.has(glyph) ? 'bottom' : 'top';
}

/** The DK glyph for a SMALL cell — its own mark. A cell the rasm wrote nothing
 *  for still carries one: the producer takes it from the reading (the kasra a
 *  reader starting on `ٱئْتِ` says), so nothing here is inferred from a sound. */
export function cellGlyph(chars: string): string {
    // The iqlab mini-meem always DISPLAYS the low-meem glyph (cleaner than the
    // isolated high-meem); pushSmall slots it by the source mark (MEEM_HI →
    // above, MEEM_LO → below).
    const mark = firstMark(chars);
    return mark === MEEM_HI ? MEEM_LO : mark;
}
