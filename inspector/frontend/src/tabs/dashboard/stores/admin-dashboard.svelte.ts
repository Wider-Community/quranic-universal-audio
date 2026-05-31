/**
 * Admin dashboard modal state (Svelte 5 rune store — the repo's first).
 * Owns open/closed + the active compartment tab. Future compartments slot
 * into the `AdminTab` union (currently: users · requests · reviews ·
 * permissions; reviews replaced the disabled `to_publish` placeholder).
 */

export type AdminTab = 'users' | 'requests' | 'reviews' | 'releases' | 'permissions';

/** Sortable columns in the Users table (clicking a header sorts by these). */
export type UsersSortKey =
    | 'role'
    | 'joined'
    | 'last_activity'
    | 'requests'
    | 'reviews'
    | 'active_claim';

class AdminDashboardStore {
    open = $state(false);
    activeTab = $state<AdminTab>('users');
    /** Caller's unviewed-open request count. Drives the Requests tab pill +
     * the dot on the entry button. Polled by the button; refreshed by the
     * Requests compartment on load/view/resolve so both surfaces agree. */
    unviewedRequests = $state(0);
    /** Caller's unviewed marked-ready review count. Drives the Reviews tab
     * pill + (combined with ``unviewedRequests``) the entry-button dot.
     * Polled by the button; refreshed by ReviewsCompartment on fetch + by
     * the reviews store on optimistic drawer-open. */
    unviewedReviews = $state(0);

    openModal(tab: AdminTab = 'users'): void {
        this.activeTab = tab;
        this.open = true;
    }

    close(): void {
        this.open = false;
    }

    setTab(tab: AdminTab): void {
        this.activeTab = tab;
    }

    setUnviewedRequests(n: number): void {
        this.unviewedRequests = Math.max(0, n);
    }

    setUnviewedReviews(n: number): void {
        this.unviewedReviews = Math.max(0, n);
    }
}

export const adminDashboard = new AdminDashboardStore();
