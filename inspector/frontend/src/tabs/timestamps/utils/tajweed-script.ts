/**
 * DK (DigitalKhatt) script vocabulary for the Timestamps analysis row — the
 * single home for the diacritic codepoints + the glyph-form maps the renderer
 * derives from a cell's `tag` + `chars`. Per the phonemizer's design principle
 * (cells carry canonical domain only — no script/visual detail), the *renderer*
 * owns these script conventions; this keeps them out of the component body.
 */

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
const MEEM_HI = 'ۢ'; // U+06E2 mini-meem above (iqlab)
const MEEM_LO = 'ۭ'; // U+06ED mini-meem below (iqlab)

/** Marks that pin to the BELOW edge of the letter row (others pin top). */
export const BELOW_MARKS = new Set([KASRA, KASRATAN]);

/** iqlab tanwīn → a SINGLE short vowel + a mini-meem composed in one DK glyph
 *  (never a doubled tanwīn); sized by the haraka's own calibration. */
export const IQLAB_FORM: Record<string, { haraka: string; meem: string }> = {
    [FATHATAN]: { haraka: FATHA, meem: MEEM_HI },
    [DAMMATAN]: { haraka: DAMMA, meem: MEEM_HI },
    [KASRATAN]: { haraka: KASRA, meem: MEEM_LO },
};

/** Open (parallel) tanwīn forms — DK encodes them as distinct codepoints
 *  (U+08F0–08F2). The canonical char alone renders STACKED; map to the open
 *  codepoint when the tanwīn assimilates into the next word. */
export const OPEN_TANWEEN: Record<string, string> = {
    [FATHATAN]: 'ࣰ',
    [DAMMATAN]: 'ࣱ',
    [KASRATAN]: 'ࣲ',
};

/** Tags whose tanwīn assimilates → render the OPEN form (else stacked). Mirrors
 *  the phonemizer's `TANWEEN_ASSIMILATES_VALUES`; iẓhar carries no tanwīn tag. */
export const OPEN_TANWEEN_TAGS = new Set([
    'idgham_ghunnah_tanween',
    'idgham_bila_ghunnah_tanween',
    'ikhfaa_tanween',
]);

/** First combining mark of `chars`, skipping a leading shadda (shadda+haraka
 *  composed → the second mark is the haraka). */
export function firstMark(chars: string): string {
    if (!chars) return '';
    const arr = [...chars];
    if (arr[0] === SHADDA && arr[1]) return arr[1];
    return arr[0]!;
}

/** Pin slot for a small cell's mark — top unless it's a below-mark. */
export function cellSlot(glyph: string): 'top' | 'bottom' {
    return BELOW_MARKS.has(glyph) ? 'bottom' : 'top';
}

/** The DK glyph for a SMALL cell — its own mark, or derived for an implicit
 *  graphemeless cell (the phonemizer keeps `chars` empty + carries the tag). */
export function cellGlyph(chars: string, tag: string | null, phone: string | undefined): string {
    if (chars) return firstMark(chars);
    if (tag === 'allah_dagger_alef') return DAGGER;
    if (tag === 'madd_iwad') return ALEF; // the added alef (full cell)
    if (tag === 'iltiqaa_kasra' || tag === 'iltiqaa') return KASRA;
    // hamza-waṣl connecting vowel: pick the haraka by the sounded vowel.
    return phone === 'i' ? KASRA : phone === 'u' ? DAMMA : FATHA;
}

/** The FULL-cell glyph for an implicit madd (chars==='') — dagger / alef. */
export function implicitMaddGlyph(tag: string | null): string {
    return tag === 'madd_iwad' ? ALEF : DAGGER;
}
