/**
 * Admin dashboard modal state (Svelte 5 rune store — the repo's first).
 * Owns open/closed + the active compartment tab. Future compartments slot
 * into the `AdminTab` union (currently: users · requests · reviews ·
 * permissions; reviews replaced the disabled `to_publish` placeholder).
 */

export type AdminTab = 'users' | 'requests' | 'reviews' | 'releases' | 'permissions';

const ALL_TABS: readonly AdminTab[] = ['users', 'requests', 'reviews', 'releases', 'permissions'];
const LS_TAB_KEY = 'insp_admin_active_tab';

/** Last admin tab the caller used, validated against the live union. Falls back
 * to ``users`` for an unknown/removed/renamed tab or when storage is blocked. */
function loadLastTab(): AdminTab {
    try {
        const raw = localStorage.getItem(LS_TAB_KEY);
        if (raw && (ALL_TABS as readonly string[]).includes(raw)) return raw as AdminTab;
    } catch {
        /* storage unavailable — fall through */
    }
    return 'users';
}

function persistTab(tab: AdminTab): void {
    try {
        localStorage.setItem(LS_TAB_KEY, tab);
    } catch {
        /* best-effort */
    }
}

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
    /** Active compartment, restored from localStorage so the modal reopens to
     * the last tab used. ``AdminDashboardModal``'s demotion effect guards the
     * live case (owner→maintainer hides Permissions); ``loadLastTab`` guards
     * the cold-start case. */
    activeTab = $state<AdminTab>(loadLastTab());
    /** Caller's unviewed-open request count. Drives the Requests tab pill +
     * the dot on the entry button. Polled by the button; refreshed by the
     * Requests compartment on load/view/resolve so both surfaces agree. */
    unviewedRequests = $state(0);

    /** Reopen to the caller's last tab unless an explicit tab is given. */
    openModal(tab: AdminTab = this.activeTab): void {
        this.setTab(tab);
        this.open = true;
    }

    close(): void {
        this.open = false;
    }

    setTab(tab: AdminTab): void {
        this.activeTab = tab;
        persistTab(tab);
    }

    setUnviewedRequests(n: number): void {
        this.unviewedRequests = Math.max(0, n);
    }
}

export const adminDashboard = new AdminDashboardStore();
