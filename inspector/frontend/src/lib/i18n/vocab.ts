/**
 * Locale-aware display labels for catalog DB enum vocabulary — riwayah, recitation
 * style, recording context, and coverage kind. `vocabLabel` maps a raw enum slug to
 * its `vocab_<kind>_<value>` message (Arabic when the locale is `ar`) and falls back
 * to `titleCaseSlug` for values without a registered translation.
 *
 * The implementation lives in `$lib/utils/delivery-label` (co-located with
 * `titleCaseSlug` and the message import) to avoid an import cycle; this module is
 * the semantic import location for component/render code.
 *
 * Paraglide message functions read the ambient locale (set by `switchLocale`), so
 * no locale argument is needed for correctness — read the reactive locale at the
 * call site only to re-render on a locale switch (see `docs/reference/i18n.md`).
 * Channels and brand names are deliberately NOT a kind here: they stay Latin.
 */
export { vocabLabel, type VocabKind } from '$lib/utils/delivery-label';
