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
 */

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

    /** Open a drawer of ``kind`` against ``slug``. */
    open(slug: string, kind: ReviewsDrawerKind): void {
        this.selectedSlug = slug;
        this.openDrawer = kind;
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
