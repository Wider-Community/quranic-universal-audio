/**
 * Arabic-normalizing substring matcher.
 *
 * Single canonical implementation consumed by ``SearchableSelect``,
 * ``ReciterPicker`` (Phase 6), and any other component that filters a
 * user-typed query against a list of Arabic-or-Latin labels.
 *
 * Symmetric with the backend helper at ``inspector/services/search_normalize.py``;
 * the same input string must normalize to the same output in both
 * languages so client-side preview and server-side search agree.
 *
 * Normalizations applied (in order):
 *   1. Lowercase (Latin only — has no effect on Arabic).
 *   2. Strip Arabic diacritics (tashkeel, dagger alef, Quranic marks).
 *   3. Collapse alif variants (أ إ آ ٱ) -> ا.
 *   4. Taa marbuta (ة) -> haa (ه).
 *   5. Alif maksura (ى) -> yaa (ي).
 *
 * Diacritic ranges (matches SearchableSelect's historical regex):
 *   U+0610-U+061A, U+064B-U+065F, U+0670,
 *   U+06D6-U+06DC, U+06DF-U+06E4, U+06E7-U+06E8, U+06EA-U+06ED.
 */

const ARABIC_DIACRITICS = /[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۤۧۨ-ۭ]/g;
const ALIF_VARIANTS = /[أإآٱ]/g;
const TAA_MARBUTA = /ة/g;
const ALIF_MAKSURA = /ى/g;

export function normalizeArabic(str: string): string {
    return str
        .toLowerCase()
        .replace(ARABIC_DIACRITICS, '')
        .replace(ALIF_VARIANTS, 'ا')
        .replace(TAA_MARBUTA, 'ه')
        .replace(ALIF_MAKSURA, 'ي');
}

/**
 * Substring match after Arabic normalization on both sides.
 * Empty needle matches everything (filter pattern: "no query -> all rows").
 */
export function match(haystack: string, needle: string): boolean {
    if (!needle) return true;
    return normalizeArabic(haystack).includes(normalizeArabic(needle));
}
