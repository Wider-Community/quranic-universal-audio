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
}

export const adminDashboard = new AdminDashboardStore();
