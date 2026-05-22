<script lang="ts">
    /** Trigger above the Admin notifications rail. Visible to maintainers +
     * owners ($isAdmin); opens the admin dashboard modal. Carries a quiet dot
     * (no number) when the caller has unviewed open requests — polled from
     * /api/admin/requests/unviewed-count and shared via the dashboard store. */
    import { onDestroy } from 'svelte';

    import { fetchUnviewedRequestCount } from '../../../../lib/api/admin-requests';
    import { isAdmin } from '../../../../lib/stores/current-user';
    import { visiblePoll } from '../../../../lib/utils/visible-poll';
    import { adminDashboard } from '../../stores/admin-dashboard.svelte';

    let teardown: (() => void) | null = null;

    // Start polling once the caller is admin. Guard keeps it idempotent so the
    // dev role-switcher flipping admin → contributor → admin doesn't stack
    // pollers (mirrors AdminActivityRail's reactive-start pattern).
    $effect(() => {
        if (!$isAdmin || teardown !== null) return;
        teardown = visiblePoll<number>({
            intervalMs: 30_000,
            fetcher: (signal) => fetchUnviewedRequestCount(signal),
            onResult: (n) => adminDashboard.setUnviewedRequests(n),
            onError: () => {},
        });
    });

    onDestroy(() => teardown?.());

    const hasUnviewed = $derived(adminDashboard.unviewedRequests > 0);
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
        {#if hasUnviewed}
            <span
                class="notif-dot"
                aria-label={`${adminDashboard.unviewedRequests} unviewed request${adminDashboard.unviewedRequests === 1 ? '' : 's'}`}
                title="Unviewed requests"
            ></span>
        {/if}
    </button>
{/if}

<style>
    .admin-open {
        position: relative;
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
    /* Quiet presence cue — no count on the button itself (the count lives on
       the Requests tab). Tinted ring so it reads on the accent fill. */
    .notif-dot {
        position: absolute;
        top: 8px;
        right: 10px;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--accent-fg);
        box-shadow: 0 0 0 2px var(--accent);
    }
</style>
