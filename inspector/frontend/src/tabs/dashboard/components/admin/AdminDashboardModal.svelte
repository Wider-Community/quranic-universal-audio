<script lang="ts">
    /** Admin dashboard modal: wide Modal shell + top tab strip. The Permissions
     * tab is owner-only — maintainers don't see it at all (the
     * ``manage_permissions`` capability is owner-only fixed). */
    import Modal from '../../../../lib/components/Modal.svelte';
    import { isOwner } from '../../../../lib/stores/current-user';
    import { adminDashboard, type AdminTab } from '../../stores/admin-dashboard.svelte';
    import PermissionsCompartment from './PermissionsCompartment.svelte';
    import RequestsCompartment from './RequestsCompartment.svelte';
    import ReviewsCompartment from './reviews/ReviewsCompartment.svelte';
    import UsersCompartment from './UsersCompartment.svelte';

    type TabDef = { id: AdminTab; label: string; enabled: boolean; ownerOnly?: boolean };

    const ALL_TABS: TabDef[] = [
        { id: 'users', label: 'Users', enabled: true },
        { id: 'requests', label: 'Requests', enabled: true },
        { id: 'reviews', label: 'Reviews', enabled: true },
        { id: 'permissions', label: 'Permissions', enabled: true, ownerOnly: true },
    ];

    // Owner-only tabs vanish entirely for non-owners (not a disabled stub).
    const tabs = $derived(ALL_TABS.filter((t) => !t.ownerOnly || $isOwner));

    // If the visible tab set changes out from under the active tab (e.g. a
    // live owner→maintainer demotion with the modal open), snap back to Users.
    $effect(() => {
        if (!tabs.some((t) => t.id === adminDashboard.activeTab)) {
            adminDashboard.setTab('users');
        }
    });
</script>

<Modal
    open={adminDashboard.open}
    size="wide"
    title="Admin dashboard"
    on:close={() => adminDashboard.close()}
>
    <div slot="header" class="am-head">
        <h2 class="am-title">Admin dashboard</h2>
        <nav class="am-tabs">
            {#each tabs as t (t.id)}
                <button
                    class="am-tab"
                    class:active={adminDashboard.activeTab === t.id}
                    class:disabled={!t.enabled}
                    disabled={!t.enabled}
                    onclick={() => adminDashboard.setTab(t.id)}
                >
                    {t.label}
                    {#if t.id === 'requests' && adminDashboard.unviewedRequests > 0}
                        <span class="am-tab-count">{adminDashboard.unviewedRequests}</span>
                    {:else if t.id === 'reviews' && adminDashboard.unviewedReviews > 0}
                        <span class="am-tab-count">{adminDashboard.unviewedReviews}</span>
                    {/if}
                </button>
            {/each}
        </nav>
    </div>

    {#if adminDashboard.activeTab === 'users'}
        <UsersCompartment />
    {:else if adminDashboard.activeTab === 'requests'}
        <RequestsCompartment />
    {:else if adminDashboard.activeTab === 'reviews'}
        <ReviewsCompartment />
    {:else if adminDashboard.activeTab === 'permissions' && $isOwner}
        <PermissionsCompartment />
    {/if}
</Modal>

<style>
    .am-head { display: flex; align-items: center; gap: var(--s-6); flex: 1; min-width: 0; }
    .am-title { font-size: var(--fs-h3); font-weight: 500; color: var(--text-primary); margin: 0; white-space: nowrap; }
    .am-tabs { display: flex; align-items: stretch; gap: var(--s-1); height: 32px; }
    .am-tab {
        position: relative;
        display: inline-flex; align-items: center;
        padding: 0 var(--s-3);
        background: transparent; border: 0;
        color: var(--text-muted); font-size: var(--fs-body);
        cursor: pointer; white-space: nowrap;
        transition: color var(--t-fast);
    }
    .am-tab:hover:not(.disabled):not(.active) { color: var(--text-secondary); }
    .am-tab.active { color: var(--text-primary); }
    .am-tab.active::after {
        content: ''; position: absolute; left: var(--s-3); right: var(--s-3); bottom: -2px;
        height: 2px; background: var(--accent); border-radius: 2px 2px 0 0;
    }
    .am-tab.disabled { color: var(--text-faint); cursor: not-allowed; }
    .am-tab-count {
        margin-left: var(--s-1);
        min-width: 17px;
        padding: 0 5px;
        font-family: var(--font-mono);
        font-size: 10.5px;
        line-height: 17px;
        font-variant-numeric: tabular-nums;
        text-align: center;
        color: var(--accent);
        background: var(--accent-tint);
        border-radius: 999px;
    }

    @media (max-width: 767px) {
        .am-head {
            flex-direction: column;
            align-items: stretch;
            gap: var(--s-3);
            margin-right: 28px; /* Leave space for the close (x) button */
        }
        .am-title {
            font-size: var(--fs-body);
        }
        .am-tabs {
            width: 100%;
            height: auto;
            flex-wrap: wrap;
            gap: var(--s-1);
        }
        .am-tab {
            flex: 1 1 auto;
            justify-content: center;
            font-size: 12px;
            padding: var(--s-2) var(--s-1);
            border: 1px solid var(--border-quiet);
            border-radius: var(--r-2);
            background: var(--panel);
        }
        .am-tab.active {
            background: var(--panel-2);
            border-color: var(--accent);
        }
        .am-tab.active::after {
            display: none; /* Hide desktop bottom-line active indicator on mobile */
        }
    }
</style>
