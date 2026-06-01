/**
 * Single-line paging helper.
 *
 * The line shows one row of words. `LineAnimation` renders the rest of the
 * current ayah from `pageStart` into a `nowrap` + `overflow: hidden` row, then
 * measures which rendered words fit fully inside the row (direction-agnostic —
 * Arabic is RTL, so we test each word's bounding rect against the row's rect
 * rather than assuming a left-to-right edge). When the active word passes the
 * last fully-fitting word, the page re-starts from the active word (the "out of
 * space" clear). Ayah-end clears are handled by the component (it resets
 * `pageStart` to the new ayah's first word).
 */

/**
 * Length of the leading run of `true` in a per-word "fits the line" array.
 *
 * Words render in recitation order, so the words that fit are a contiguous
 * prefix; the first word that overflows ends the page. Returns at least 1 when
 * the array is non-empty so a single word wider than the line still shows (it
 * clips) rather than paging forever.
 */
export function fittedPrefixLength(fits: boolean[]): number {
    if (fits.length === 0) return 0;
    let n = 0;
    for (const f of fits) {
        if (f) n++;
        else break;
    }
    return Math.max(1, n);
}
