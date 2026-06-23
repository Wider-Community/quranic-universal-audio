/**
 * Tajweed-rule → colour-badge mapping for the Timestamps analysis row.
 *
 * The single home for "which cell `tag` gets which colour". Cells carry the
 * canonical tajweed `tag` (phonemizer-owned); the *renderer* decides the palette.
 * Mirrors the convention in `tajweed-script.ts` (renderer owns visual detail).
 *
 * Each colour is a CSS custom property (`--tj-*`, defined in `styles/base.css`),
 * so the actual hues live in one themable place. A tag absent from the map →
 * `null` → no badge (madd ṭabīʿī, bila-ghunnah idgham, mutamathilayn family, and
 * the structural keys madd_iwad / allah_dagger_alef / hamza_wasl_vowel / iltiqaa /
 * qalqala are all intentionally uncoloured).
 */

const TAG_COLOR: Record<string, string> = {
    // madd subtypes — colour the carrier grapheme only (ṭabīʿī is uncoloured)
    madd_jaiz_munfasil: 'var(--tj-madd-jaiz)',
    madd_wajib_muttasil: 'var(--tj-madd-wajib)',
    madd_lazim: 'var(--tj-madd-lazim)',
    madd_arid_lissukun: 'var(--tj-madd-arid)',
    madd_leen: 'var(--tj-madd-leen)',
    // ghunnah family
    idgham_ghunnah_noon: 'var(--tj-idgham-ghunnah)',
    idgham_ghunnah_tanween: 'var(--tj-idgham-ghunnah)',
    idgham_shafawi: 'var(--tj-idgham-shafawi)',
    noon_ghunnah: 'var(--tj-ghunnah)',
    meem_ghunnah: 'var(--tj-ghunnah)',
    ikhfaa_noon: 'var(--tj-ikhfaa)',
    ikhfaa_tanween: 'var(--tj-ikhfaa)',
    iqlab_noon: 'var(--tj-iqlab)',
    iqlab_tanween: 'var(--tj-iqlab)',
    ikhfaa_shafawi: 'var(--tj-ikhfaa-shafawi)',
};

/**
 * Cross-word idgham tags — these manifest as ONE bridge phoneme between two words
 * (not an inline box). The letter row colours both involved letters (the source
 * holds the tag; the receiver gets the colour by `share_group` propagation), while
 * the phoneme row colours only the bridge tile. Used to: (a) drive that letter-row
 * propagation, and (b) keep the source cell's own (vowel) phoneme out of the inline
 * phoneme map. bila-ghunnah / mutamathilayn are here too (they bridge) but carry no
 * colour, so they propagate nothing.
 */
export const CROSS_WORD_IDGHAM_TAGS: ReadonlySet<string> = new Set([
    'idgham_ghunnah_noon',
    'idgham_ghunnah_tanween',
    'idgham_bila_ghunnah_noon',
    'idgham_bila_ghunnah_tanween',
    'idgham_shafawi',
    'idgham_mutamathilayn',
    'idgham_mutaqaribayn',
    'idgham_mutajanisayn_kamil',
    'idgham_mutajanisayn_naqis',
]);

/** The `var(--tj-*)` badge colour for a tag, or `null` if the rule is uncoloured. */
export function tajweedColorVar(tag: string | null | undefined): string | null {
    return tag ? (TAG_COLOR[tag] ?? null) : null;
}

/** True for a tag whose phoneme renders as a cross-word bridge (not an inline box). */
export function isBridgeTag(tag: string | null | undefined): boolean {
    return !!tag && CROSS_WORD_IDGHAM_TAGS.has(tag);
}
