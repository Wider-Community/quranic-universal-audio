/**
 * Arabic-normalizing substring matcher.
 *
 * Single canonical implementation consumed by ``SearchableSelect``,
 * ``ReciterPicker``, and any other component that filters a user-typed
 * query against a list of Arabic-or-Latin labels.
 *
 * Symmetric with the backend helper at
 * ``inspector/services/activity/search_normalize.py``; the same input
 * string must normalize to the same output in both languages so
 * client-side preview and server-side search agree.
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

// Memo for normalizeArabic. Search bars re-test the same stable haystacks
// (reciter names, option labels) on every keystroke, so caching the normalized
// form turns each repeat into a map lookup instead of five regex passes. Inputs
// are bounded label sets; the cap is a safety valve against unbounded growth.
const NORMALIZE_CACHE = new Map<string, string>();
const NORMALIZE_CACHE_CAP = 10_000;

export function normalizeArabic(str: string): string {
    const hit = NORMALIZE_CACHE.get(str);
    if (hit !== undefined) return hit;
    const out = normalizeRaw(str);
    if (NORMALIZE_CACHE.size >= NORMALIZE_CACHE_CAP) NORMALIZE_CACHE.clear();
    NORMALIZE_CACHE.set(str, out);
    return out;
}

function normalizeRaw(str: string): string {
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

/**
 * Filter ``items`` to those where any extracted field contains ``query``
 * (Arabic-normalized substring). The needle is normalized once; each field
 * normalization hits the shared cache. A blank query returns a copy of
 * ``items``. ``fieldsOf`` may return nullish fields — they're skipped.
 *
 * Single multi-field filter for every reciter/option search bar (CatalogList,
 * CombinationPicker, StepReciter, TimestampsFooterLeft, SearchableSelect).
 */
export function filterByFields<T>(
    items: readonly T[],
    query: string,
    fieldsOf: (item: T) => ReadonlyArray<string | null | undefined>,
): T[] {
    const needle = normalizeArabic(query);
    if (!needle) return items.slice();
    return items.filter((item) => {
        for (const field of fieldsOf(item)) {
            if (field && normalizeArabic(field).includes(needle)) return true;
        }
        return false;
    });
}
