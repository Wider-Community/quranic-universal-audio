/**
 * Resolve the set of reciters playable on the redesigned Timestamps tab:
 * PUBLISHED, by_surah (continuous-chapter) deliveries whose slug also appears
 * in the TS manifest (i.e. actually has word timestamps). Pure helpers over the
 * public catalog snapshot + the TS manifest slug set — shared by the footer
 * reciter picker and the tab's entry/continuity resolution.
 */
import type { PublicDelivery, PublicReciter } from '../../../lib/types/generated/schemas';

export interface TsPublishedEntry {
    reciter: PublicReciter;
    delivery: PublicDelivery;
}

/** Is this delivery a continuous-chapter (by_surah) file we can ride? */
function isBySurah(d: PublicDelivery): boolean {
    // The catalog marks per-verse deliveries 'by_ayah'; everything else is a
    // single chapter file (matches PlayerMetaChip's playable filter).
    return d.audio_category !== 'by_ayah';
}

/** All published + by_surah + timestamped (reciter, delivery) pairs, sorted by
 *  reciter display name. One entry per qualifying delivery. */
export function resolveTsDeliveries(
    reciters: PublicReciter[],
    manifestSlugs: Set<string>,
): TsPublishedEntry[] {
    const out: TsPublishedEntry[] = [];
    for (const reciter of reciters) {
        for (const delivery of reciter.deliveries) {
            if (
                delivery.bucket === 'published'
                && isBySurah(delivery)
                && manifestSlugs.has(delivery.slug)
            ) {
                out.push({ reciter, delivery });
            }
        }
    }
    out.sort((a, b) => a.reciter.name.localeCompare(b.reciter.name));
    return out;
}

/** Find the TS-capable published entry for a given delivery slug, or null. */
export function findTsEntryBySlug(
    reciters: PublicReciter[],
    manifestSlugs: Set<string>,
    slug: string,
): TsPublishedEntry | null {
    if (!slug) return null;
    for (const reciter of reciters) {
        for (const delivery of reciter.deliveries) {
            if (delivery.slug === slug && delivery.bucket === 'published' && isBySurah(delivery)) {
                return manifestSlugs.has(slug) ? { reciter, delivery } : null;
            }
        }
    }
    return null;
}

/** True when the given delivery (e.g. the one currently in playerContext) is a
 *  published, by_surah, timestamped delivery — used for the continuity check. */
export function isTsCapable(
    delivery: PublicDelivery | null,
    manifestSlugs: Set<string>,
): boolean {
    return (
        !!delivery
        && delivery.bucket === 'published'
        && isBySurah(delivery)
        && manifestSlugs.has(delivery.slug)
    );
}
