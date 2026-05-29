/**
 * Reviews tab selection + drawer state + filters (Svelte 5 rune store).
 *
 * Lifecycle: row body click opens the General drawer; the Ops button on
 * each row opens the Ops drawer. ``close()`` clears selection too so the
 * scrim, the X button, and Esc all funnel through one path.
 *
 * Filters and sort persist across modal open/close (the store is a
 * module-level singleton). They reset on page reload — see
 * docs/planning/reviews-tab-deferred.md item 10 for the localStorage path.
 *
 * The fetched recitation list lives on ``ReviewsCompartment`` as local
 * ``$state`` — this store only owns selection + filters/sort. Detail
 * fetches live in the drawer's own ``$effect`` keyed on ``selectedSlug``.
 *
 * Also tracks ``viewedThisSession`` — slugs whose drawer the admin has
 * already opened in this session. Used by the row to drop its ``.unread``
 * dot synchronously on click (no flash while the optimistic POST is in
 * flight). Cross-store coordination with the admin-dashboard counter is
 * owned by the row component (which sits under ``tabs/dashboard/``) —
 * this store stays ``lib/``-pure (no tabs/ imports).
 */

import { markReviewViewed } from '../api/admin-reviews';

export type ReviewsDrawerKind = 'general' | 'ops';

export type ReviewsSort = 'stalled' | 'name';

export interface ReviewsFilters {
    q: string;
    riwayah: string | null;
    style: string | null;
    channel: string | null;
}

class ReviewsStore {
    selectedSlug = $state<string | null>(null);
    openDrawer = $state<ReviewsDrawerKind | null>(null);

    filters = $state<ReviewsFilters>({
        q: '',
        riwayah: null,
        style: null,
        channel: null,
    });
    sortBy = $state<ReviewsSort>('stalled');

    /** Slugs whose drawer was opened in this session — used by the row
     * to suppress its ``.unread`` dot the moment the click lands. The
     * server flag on the next compartment refetch is the durable truth. */
    viewedThisSession = $state<Set<string>>(new Set());

    /** Open a drawer of ``kind`` against ``slug``. On the first open for a
     * given slug in this session, fire the best-effort viewed-mark POST —
     * caller is expected to handle cross-store counter sync (lives under
     * ``tabs/dashboard/`` to keep this store ``lib/``-pure). */
    open(slug: string, kind: ReviewsDrawerKind): void {
        this.selectedSlug = slug;
        this.openDrawer = kind;
        if (!this.viewedThisSession.has(slug)) {
            // Mutate via assign-back so Svelte's $state proxy picks it up.
            const next = new Set(this.viewedThisSession);
            next.add(slug);
            this.viewedThisSession = next;
            markReviewViewed(slug).catch(() => {
                /* best-effort: next refetch reconciles the server-authoritative
                 * unread flag. The session-set drop persists so the dot stays
                 * cleared for the rest of this session. */
            });
        }
    }

    /** True if the calling admin has opened any drawer for ``slug`` in this
     * session — drives the row's local dot-suppression guard. */
    isViewedThisSession(slug: string): boolean {
        return this.viewedThisSession.has(slug);
    }

    /** Swap drawer kind without changing the selected row. */
    setDrawer(kind: ReviewsDrawerKind): void {
        this.openDrawer = kind;
    }

    /** Close all — clears selection too so the active-row ring drops. */
    close(): void {
        this.selectedSlug = null;
        this.openDrawer = null;
    }

    setQ(q: string): void {
        this.filters.q = q;
    }

    /** Toggle a facet: clicking the active value clears it. */
    toggleFacet(key: 'riwayah' | 'style' | 'channel', value: string): void {
        this.filters[key] = this.filters[key] === value ? null : value;
    }

    clearFilters(): void {
        this.filters.q = '';
        this.filters.riwayah = null;
        this.filters.style = null;
        this.filters.channel = null;
    }

    setSort(s: ReviewsSort): void {
        this.sortBy = s;
    }

    get hasActiveFilters(): boolean {
        const f = this.filters;
        return f.q.trim() !== '' || f.riwayah !== null || f.style !== null || f.channel !== null;
    }
}

export const reviewsStore = new ReviewsStore();
