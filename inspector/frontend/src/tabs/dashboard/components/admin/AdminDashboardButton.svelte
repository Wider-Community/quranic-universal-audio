<script lang="ts">
    /** Trigger above the Admin notifications rail. Visible to maintainers +
     * owners ($isAdmin); opens the admin dashboard modal. Carries a single
     * quiet dot (no number) when the caller has unviewed open requests —
     * polled from /api/admin/requests/unviewed-count. (Review notifications
     * were retired with the Releases-tab restructure; the marked-ready queue
     * now lives in Releases without a notification.) */
    import { onDestroy } from 'svelte';

    import { fetchUnviewedRequestCount } from '../../../../lib/api/admin-requests';
    import { isAdmin } from '../../../../lib/stores/current-user';
    import { visiblePoll } from '../../../../lib/utils/visible-poll';
    import { adminDashboard } from '../../stores/admin-dashboard.svelte';

    let teardownRequests: (() => void) | null = null;

    // Page-Visibility-aware (visiblePoll) so background tabs don't churn.
    // Idempotent guard keeps the poller stable across dev role-switcher flips.
    $effect(() => {
        if (!$isAdmin) return;
        if (teardownRequests === null) {
            teardownRequests = visiblePoll<number>({
                intervalMs: 30_000,
                fetcher: (signal) => fetchUnviewedRequestCount(signal),
                onResult: (n) => adminDashboard.setUnviewedRequests(n),
                onError: () => {},
            });
        }
    });

    onDestroy(() => {
        teardownRequests?.();
    });

    const unviewedRequests = $derived(adminDashboard.unviewedRequests);
    const hasUnviewed = $derived(unviewedRequests > 0);

    const dotLabel = $derived(
        unviewedRequests > 0
            ? `${unviewedRequests} unviewed request${unviewedRequests === 1 ? '' : 's'}`
            : '',
    );
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
                aria-label={dotLabel}
                title={dotLabel}
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
