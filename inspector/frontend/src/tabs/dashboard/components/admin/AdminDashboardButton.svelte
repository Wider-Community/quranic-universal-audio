<script lang="ts">
    /** Trigger above the Admin notifications rail. Visible to maintainers +
     * owners ($isAdmin); opens the admin dashboard modal. */
    import { isAdmin } from '../../../../lib/stores/current-user';
    import { adminDashboard } from '../../stores/admin-dashboard.svelte';
</script>

{#if $isAdmin}
    <button class="admin-open" type="button" onclick={() => adminDashboard.openModal()}>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
            <rect x="1.5" y="1.5" width="5" height="5" rx="1" />
            <rect x="9.5" y="1.5" width="5" height="5" rx="1" />
            <rect x="1.5" y="9.5" width="5" height="5" rx="1" />
            <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
        </svg>
        Admin dashboard
    </button>
{/if}

<style>
    .admin-open {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: var(--s-2);
        width: 100%;
        padding: var(--s-3) var(--s-4);
        margin-bottom: var(--s-4);
        background: var(--accent);
        color: var(--accent-fg);
        border: 1px solid var(--accent);
        border-radius: var(--r-2);
        font-size: var(--fs-body);
        font-weight: 500;
        cursor: pointer;
        transition: background var(--t-fast);
    }
    .admin-open:hover { background: var(--accent-strong); }
    .admin-open svg { width: 15px; height: 15px; }
</style>
