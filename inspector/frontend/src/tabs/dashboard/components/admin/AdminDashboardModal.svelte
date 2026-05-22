<script lang="ts">
    /** Admin dashboard modal: wide Modal shell + top tab strip. Only the Users
     * compartment ships now; the rest are disabled placeholders for the shape. */
    import Modal from '../../../../lib/components/Modal.svelte';
    import { adminDashboard, type AdminTab } from '../../stores/admin-dashboard.svelte';
    import UsersCompartment from './UsersCompartment.svelte';

    const TABS: { id: AdminTab; label: string; enabled: boolean }[] = [
        { id: 'users', label: 'Users', enabled: true },
        { id: 'requests', label: 'Requests', enabled: false },
        { id: 'to_publish', label: 'To publish', enabled: false },
        { id: 'permissions', label: 'Permissions', enabled: false },
    ];
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
            {#each TABS as t (t.id)}
                <button
                    class="am-tab"
                    class:active={adminDashboard.activeTab === t.id}
                    class:disabled={!t.enabled}
                    disabled={!t.enabled}
                    onclick={() => adminDashboard.setTab(t.id)}
                >
                    {t.label}
                </button>
            {/each}
        </nav>
    </div>

    {#if adminDashboard.activeTab === 'users'}
        <UsersCompartment />
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
</style>
