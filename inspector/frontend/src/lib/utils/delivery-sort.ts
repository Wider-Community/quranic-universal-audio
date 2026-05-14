/**
 * Canonical sort order for combinations (deliveries) — shared between the
 * reciter detail modal and the player meta chip dropup.
 *
 * Priority chain:
 *   1. Bucket rank (released > under_review > …)
 *   2. Audio category (by_surah first, by_ayah last)
 *   3. Coverage (full > partial)
 *   4. Riwayah (Hafs first, then alphabetical)
 *   5. Style (alphabetical)
 *   6. Bitrate (higher first)
 */
import type { PublicDelivery } from '../types/public-state';
import { bucketRank } from '../types/public-state';

function catRank(cat: string): number {
    if (cat === 'by_surah') return 0;
    if (cat === 'by_ayah')  return 2;
    return 1;
}

function riwayahRank(r: string): number {
    return r.toLowerCase().startsWith('hafs') ? 0 : 1;
}

export function compareDeliveries(a: PublicDelivery, b: PublicDelivery): number {
    const s = bucketRank(a.bucket) - bucketRank(b.bucket);
    if (s !== 0) return s;
    const c = catRank(a.audio_category) - catRank(b.audio_category);
    if (c !== 0) return c;
    if (a.coverage_kind !== b.coverage_kind) {
        return a.coverage_kind === 'full' ? -1 : 1;
    }
    const r = riwayahRank(a.riwayah) - riwayahRank(b.riwayah);
    if (r !== 0) return r;
    const ra = a.riwayah.localeCompare(b.riwayah);
    if (ra !== 0) return ra;
    const st = a.style.localeCompare(b.style);
    if (st !== 0) return st;
    return (b.bitrate_kbps_nominal ?? 0) - (a.bitrate_kbps_nominal ?? 0);
}
