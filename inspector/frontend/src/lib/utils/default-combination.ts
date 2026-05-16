/**
 * Resolve which combination (delivery) of a reciter should be the default
 * playback target.
 *
 * Tiebreak chain (highest priority first):
 *   1. Hafs riwayah + Murattal style
 *   2. Hafs riwayah (any style)
 *   3. Highest coverage (chapter_count)
 *   4. Highest bitrate_kbps_nominal
 *   5. Alphabetical channel slug
 */
import type { PublicDelivery } from '../types/public-state';

export function defaultCombination(deliveries: readonly PublicDelivery[]): PublicDelivery | null {
    if (deliveries.length === 0) return null;
    const sorted = [...deliveries].sort(compare);
    return sorted[0]!;
}

function compare(a: PublicDelivery, b: PublicDelivery): number {
    const ah = a.riwayah === 'hafs' && a.style === 'murattal' ? 0 : 1;
    const bh = b.riwayah === 'hafs' && b.style === 'murattal' ? 0 : 1;
    if (ah !== bh) return ah - bh;

    const ar = a.riwayah === 'hafs' ? 0 : 1;
    const br = b.riwayah === 'hafs' ? 0 : 1;
    if (ar !== br) return ar - br;

    if (a.chapter_count !== b.chapter_count) return b.chapter_count - a.chapter_count;

    const abr = a.bitrate_kbps_nominal ?? -1;
    const bbr = b.bitrate_kbps_nominal ?? -1;
    if (abr !== bbr) return bbr - abr;

    return a.channel.localeCompare(b.channel);
}
