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
 * activity rail, which polls on the same cadence. Each tick first fetches the
 * tiny `/api/public/version` probe (`db_seq`, the monotonic write counter) and
 * only refetches the full multi-page roster + stats when it has moved — so an
 * idle catalog costs one small request per tick instead of paging the whole
 * ~1k-reciter list every 30s. `applyPage` still guards the store write on a
 * structural signature, so even a forced refetch that changed nothing skips
 * re-reconciling the (virtualized) list.
 */
import { get, writable } from 'svelte/store';

import { fetchCatalogVersion, fetchPublicReciters, fetchPublicStats } from '../../../lib/api/public-reciters';
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

/** Consecutive failed poll ticks tolerated before the dashboard surfaces an
 *  error. A single transient 5xx (the Space proxy momentarily can't reach the
 *  single worker) shouldn't blank a working dashboard — keep the last-good
 *  snapshot and only surface once failures persist. */
const POLL_ERROR_TOLERANCE = 3;

let pollTeardown: (() => void) | null = null;
let pollRefs = 0;

/** Running count of consecutive failed poll ticks; reset on any success. */
let pollErrorStreak = 0;

/** Signature of the last applied snapshot, so a poll that returns an unchanged
 *  catalog skips the store write (and the list re-reconcile it would trigger). */
let lastSnapshotSig: string | null = null;

/** `db_seq` of the last roster the poll actually fetched. A tick whose version
 *  probe matches this skips the multi-page roster refetch entirely. */
let lastVersion: number | null = null;

/** Poll payload: the freshly-fetched roster + stats, or `null` when the version
 *  probe was unchanged and nothing needs applying. */
type CatalogPollResult = {
    page: { reciters: PublicReciter[] };
    stats: BucketCounts;
    version: number;
} | null;

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
        pollErrorStreak = 0;
        pollTeardown = visiblePoll<CatalogPollResult>({
            intervalMs: CATALOG_POLL_MS,
            fetcher: async (signal) => {
                const version = await fetchCatalogVersion(signal);
                // Unchanged since the last applied roster (and we have one) —
                // skip the expensive multi-page refetch for this tick.
                if (version === lastVersion && get(catalogData).reciters.length > 0) {
                    return null;
                }
                const [reciters, stats] = await Promise.all([
                    fetchAllReciters(signal),
                    fetchPublicStats(signal),
                ]);
                return { page: { reciters }, stats, version };
            },
            onResult: (result) => {
                pollErrorStreak = 0;
                // A recovered tick clears any transient error a prior failed
                // tick surfaced (applyPage only clears it when the data changed).
                const cur = get(catalogData);
                if (cur.error) catalogData.set({ ...cur, error: null });
                if (result === null) return;
                lastVersion = result.version;
                applyPage(result.page, result.stats);
            },
            onError: (e) => {
                pollErrorStreak += 1;
                const haveData = get(catalogData).reciters.length > 0;
                // Swallow a transient blip while we still have data to show;
                // only surface once we've never loaded or failures persist.
                if (!haveData || pollErrorStreak >= POLL_ERROR_TOLERANCE) {
                    catalogData.update((s) => ({
                        ...s,
                        loading: false,
                        error: (e as Error).message ?? 'Failed to load catalog',
                    }));
                }
            },
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
