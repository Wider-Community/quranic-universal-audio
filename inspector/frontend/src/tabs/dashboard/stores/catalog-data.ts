/**
 * Dashboard catalog data store — fetches the public reciter list +
 * stats once on first read and caches in-memory. Subsequent subscribers
 * receive the cached snapshot.
 *
 * Phase 6: data is small (a few hundred reciters), so we fetch
 * everything once with limit=500 and filter client-side. The endpoint
 * already supports server-side filter+search; we choose client-side
 * for responsiveness and to keep the picker, dashboard, and detail
 * page consistent.
 */
import { get, writable } from 'svelte/store';

import { fetchPublicReciters, fetchPublicStats } from '../../../lib/api/public-reciters';
import type { BucketCounts, PublicDelivery, PublicReciter } from '../../../lib/types/public-state';

export interface CatalogSnapshot {
    loading: boolean;
    error: string | null;
    reciters: PublicReciter[];
    stats: BucketCounts | null;
}

const initial: CatalogSnapshot = {
    loading: true,
    error: null,
    reciters: [],
    stats: null,
};

export const catalogData = writable<CatalogSnapshot>(initial);

let inflight: Promise<void> | null = null;

export async function loadCatalog(force = false): Promise<void> {
    if (inflight && !force) return inflight;
    // Already loaded — skip the network round-trip. Callers that need a
    // fresh snapshot (e.g. after a known mutation) pass `force=true`.
    if (!force && get(catalogData).reciters.length > 0) return;
    inflight = (async () => {
        catalogData.update((s) => ({ ...s, loading: true, error: null }));
        try {
            const [page, stats] = await Promise.all([
                fetchPublicReciters({ limit: 500 }),
                fetchPublicStats(),
            ]);
            catalogData.set({
                loading: false,
                error: null,
                reciters: page.reciters,
                stats,
            });
        } catch (e) {
            catalogData.update((s) => ({
                ...s,
                loading: false,
                error: (e as Error).message ?? 'Failed to load catalog',
            }));
        } finally {
            inflight = null;
        }
    })();
    return inflight;
}

/**
 * Resolve a persisted delivery slug back to its `{reciter, delivery}` pair
 * from the loaded catalog. Returns null if the catalog isn't loaded yet or the
 * slug no longer exists (e.g. the combination was discarded). Used to restore
 * the dashboard player after a refresh.
 */
export function resolveDeliverySlug(
    slug: string,
): { reciter: PublicReciter; delivery: PublicDelivery } | null {
    for (const reciter of get(catalogData).reciters) {
        const delivery = reciter.deliveries.find((d) => d.slug === slug);
        if (delivery) return { reciter, delivery };
    }
    return null;
}
