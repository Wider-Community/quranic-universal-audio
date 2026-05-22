/**
 * Admin dashboard modal state (Svelte 5 rune store — the repo's first).
 * Owns open/closed + the active compartment tab. Future compartments
 * (requests / to_publish / permissions) slot into the `AdminTab` union.
 */

export type AdminTab = 'users' | 'requests' | 'to_publish' | 'permissions';

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
}

export const adminDashboard = new AdminDashboardStore();
