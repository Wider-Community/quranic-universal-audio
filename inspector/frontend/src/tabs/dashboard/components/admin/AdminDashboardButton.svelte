<script lang="ts">
    /** Trigger above the Admin notifications rail. Visible to maintainers +
     * owners ($isAdmin); opens the admin dashboard modal. Carries a single
     * quiet dot (no number) when the caller has any unviewed admin work —
     * polled in parallel from /api/admin/requests/unviewed-count and
     * /api/admin/reviews/unviewed-count and OR'd via the dashboard store.
     * One dot keeps the trigger calm; the per-tab pills inside the modal
     * differentiate which surface needs attention. */
    import { onDestroy } from 'svelte';

    import { fetchUnviewedRequestCount } from '../../../../lib/api/admin-requests';
    import { fetchUnviewedReviewCount } from '../../../../lib/api/admin-reviews';
    import { isAdmin } from '../../../../lib/stores/current-user';
    import { visiblePoll } from '../../../../lib/utils/visible-poll';
    import { adminDashboard } from '../../stores/admin-dashboard.svelte';

    let teardownRequests: (() => void) | null = null;
    let teardownReviews: (() => void) | null = null;

    // Two independent pollers — failure of one (e.g. transient 5xx) doesn't
    // blank the other's dot. Same 30s cadence; Page-Visibility-aware via
    // visiblePoll so background tabs don't churn. Idempotent guards keep
    // the pollers stable across dev role-switcher flips.
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
        if (teardownReviews === null) {
            teardownReviews = visiblePoll<number>({
                intervalMs: 30_000,
                fetcher: (signal) => fetchUnviewedReviewCount(signal),
                onResult: (n) => adminDashboard.setUnviewedReviews(n),
                onError: () => {},
            });
        }
    });

    onDestroy(() => {
        teardownRequests?.();
        teardownReviews?.();
    });

    const unviewedRequests = $derived(adminDashboard.unviewedRequests);
    const unviewedReviews = $derived(adminDashboard.unviewedReviews);
    const hasUnviewed = $derived(unviewedRequests > 0 || unviewedReviews > 0);

    const dotLabel = $derived.by(() => {
        const parts: string[] = [];
        if (unviewedRequests > 0) {
            parts.push(`${unviewedRequests} unviewed request${unviewedRequests === 1 ? '' : 's'}`);
        }
        if (unviewedReviews > 0) {
            parts.push(`${unviewedReviews} marked-ready review${unviewedReviews === 1 ? '' : 's'}`);
        }
        return parts.join(' · ');
    });
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
