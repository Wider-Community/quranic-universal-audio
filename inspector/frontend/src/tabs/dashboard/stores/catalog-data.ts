/**
 * Dashboard catalog data store — fetches the full public reciter list +
 * stats once on first read and caches in-memory. Subsequent subscribers
 * receive the cached snapshot.
 *
 * The whole roster (paged via `next_cursor`) is held client-side and
 * filtered/searched in the browser: the endpoint supports server-side
 * filter+search, but client-side keeps the dashboard, picker, and detail
 * page consistent and lets facet counts reflect the complete catalog.
 *
 * Freshness: `startCatalogPolling()` drives a visibility-aware refresh so
 * the store tracks lifecycle transitions (e.g. a reciter flipping to
 * "available for review") without a manual reload — keeping every
 * catalog-fed surface (table, pickers, footer chip) in sync with the
 * activity rail, which polls on the same cadence. Backend
 * `/api/public/reciters` is `db_seq`-cached, so steady-state polls hit an
 * unchanged catalog; `applyPage` then skips the store write entirely so the
 * (now-virtualized) list isn't re-reconciled for nothing.
 */
import { get, writable } from 'svelte/store';

import { fetchPublicReciters, fetchPublicStats } from '../../../lib/api/public-reciters';
import type { BucketCounts, PublicDelivery, PublicReciter } from '../../../lib/types/generated/schemas';
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

const PAGE_SIZE = 500;

/**
 * Fetch the full reciter list across every page. The catalog outgrew a single
 * page (a new source can multiply the roster), so a one-shot `limit` would
 * silently truncate the browse + skew client-side facet counts.
 */
async function fetchAllReciters(signal?: AbortSignal): Promise<PublicReciter[]> {
    const all: PublicReciter[] = [];
    let cursor: number | undefined;
    for (;;) {
        const page = await fetchPublicReciters({ limit: PAGE_SIZE, cursor, signal });
        all.push(...page.reciters);
        if (page.next_cursor == null) break;
        cursor = page.next_cursor;
    }
    return all;
}

export async function loadCatalog(force = false): Promise<void> {
    if (inflight && !force) return inflight;
    // Already loaded — skip the network round-trip. Callers that need a
    // fresh snapshot (e.g. after a known mutation) pass `force=true`.
    if (!force && get(catalogData).reciters.length > 0) return;
    inflight = (async () => {
        catalogData.update((s) => ({ ...s, loading: true, error: null }));
        try {
            const [reciters, stats] = await Promise.all([
                fetchAllReciters(),
                fetchPublicStats(),
            ]);
            catalogData.set({
                loading: false,
                error: null,
                reciters,
                stats,
            });
            lastSnapshotSig = snapshotSig(reciters, stats);
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

/** Signature of the last applied snapshot, so a poll that returns an unchanged
 *  catalog skips the store write (and the list re-reconcile it would trigger). */
let lastSnapshotSig: string | null = null;

/** Cheap structural fingerprint: roster size + each reciter's volatile fields
 *  (state/activity/delivery count) + the bucket stat counts. Catches every
 *  change the UI renders without deep-comparing the full objects. */
function snapshotSig(reciters: PublicReciter[], stats: BucketCounts): string {
    let s = `${reciters.length}|`;
    for (const r of reciters) {
        s += `${r.reciter_id}:${r.last_activity ?? ''}:${r.primary_bucket}:${r.deliveries_count};`;
    }
    return `${s}|${JSON.stringify(stats)}`;
}

function applyPage(page: { reciters: PublicReciter[] }, stats: BucketCounts): void {
    const sig = snapshotSig(page.reciters, stats);
    if (sig === lastSnapshotSig) return;
    lastSnapshotSig = sig;
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
                    fetchAllReciters(signal).then((reciters) => ({ reciters })),
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
