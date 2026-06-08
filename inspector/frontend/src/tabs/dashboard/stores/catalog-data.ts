/**
 * Dashboard catalog data store — fetches the public reciter list +
 * stats once on first read and caches in-memory. Subsequent subscribers
 * receive the cached snapshot.
 *
 * Data is small (a few hundred reciters), so we fetch everything once
 * with limit=500 and filter client-side. The endpoint already supports
 * server-side filter+search; we choose client-side for responsiveness
 * and to keep the picker, dashboard, and detail page consistent.
 *
 * Freshness: `startCatalogPolling()` drives a visibility-aware refresh so
 * the store tracks lifecycle transitions (e.g. a reciter flipping to
 * "available for review") without a manual reload — keeping every
 * catalog-fed surface (table, pickers, footer chip) in sync with the
 * activity rail, which polls on the same cadence. Backend
 * `/api/public/reciters` is `db_seq`-cached, so steady-state polls that
 * hit an unchanged catalog are near-free.
 */
import { get, writable } from 'svelte/store';

import { fetchPublicReciters, fetchPublicStats } from '../../../lib/api/public-reciters';
import type { BucketCounts, PublicDelivery, PublicReciter } from '../../../lib/types/public-state';
import { visiblePoll } from '../../../lib/utils/visible-poll';

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

const CATALOG_POLL_MS = 30_000;

let pollTeardown: (() => void) | null = null;
let pollRefs = 0;

function applyPage(page: { reciters: PublicReciter[] }, stats: BucketCounts): void {
    catalogData.set({ loading: false, error: null, reciters: page.reciters, stats });
}

/**
 * Begin (or join) the shared catalog refresh poll. Reference-counted so
 * multiple mounted surfaces share one poller; the underlying `visiblePoll`
 * pauses while the tab is hidden and fetches immediately on return. The
 * first tick replaces the initial `loadCatalog()` round-trip. Returns a
 * teardown that decrements the refcount and stops the poll once no surface
 * is subscribed.
 */
export function startCatalogPolling(): () => void {
    pollRefs += 1;
    if (!pollTeardown) {
        pollTeardown = visiblePoll<[{ reciters: PublicReciter[] }, BucketCounts]>({
            intervalMs: CATALOG_POLL_MS,
            fetcher: (signal) =>
                Promise.all([
                    fetchPublicReciters({ limit: 500, signal }),
                    fetchPublicStats(signal),
                ]),
            onResult: ([page, stats]) => applyPage(page, stats),
            onError: (e) =>
                catalogData.update((s) => ({
                    ...s,
                    loading: false,
                    error: (e as Error).message ?? 'Failed to load catalog',
                })),
        });
    }
    return () => {
        pollRefs -= 1;
        if (pollRefs <= 0) {
            pollTeardown?.();
            pollTeardown = null;
            pollRefs = 0;
        }
    };
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
