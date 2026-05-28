/**
 * Reviews tab selection + drawer state (Svelte 5 rune store).
 *
 * Lifecycle: row body click opens the General drawer; action chip clicks
 * (Ops in M3) swap the drawer kind in place with the same slug. ``close()``
 * clears both — the scrim, the X button, and Esc all funnel through it.
 *
 * The fetched recitation list lives on ``ReviewsCompartment`` as local
 * ``$state`` — this store only owns selection and the (future) filter set.
 * Detail fetches (timeline + history + validation counts) live in the
 * drawer's own ``$effect``, keyed on ``selectedSlug``.
 *
 * Filters land in M4.
 */

export type ReviewsDrawerKind = 'general' | 'ops';

class ReviewsStore {
    selectedSlug = $state<string | null>(null);
    openDrawer = $state<ReviewsDrawerKind | null>(null);

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
}

export const reviewsStore = new ReviewsStore();
