<script lang="ts">
    /**
     * In-row expansion for a Releases row — one shared, button-switched panel.
     *
     * Renders exactly one view per the ``mode`` the row requested:
     *   - ts        → ReleasesTsSettings (unified generate / regenerate)
     *   - timeline  → ExpandedTimeline (lazy AdminReviewDetail)
     *   - reviewers → ReviewerHistoryView (same lazy detail)
     *   - jobs      → ReleasesPastJobs (history + live log)
     * Segments is a redirect on the row, not a mode here.
     *
     * timeline + reviewers share one lazy ``fetchAdminReviewDetail`` (cached
     * for the life of this expansion). No backend change — the detail route
     * already exists for the Reviews drawer.
     */
    import { fetchAdminReviewDetail } from '../../../../../lib/api/admin-reviews';
    import type { ReleaseStatusRow } from '../../../../../lib/api/admin-releases';
    import type { AdminReviewDetail } from '../../../../../lib/types/generated/schemas';
    import ExpandedTimeline from '../reviews/ExpandedTimeline.svelte';
    import ReleasesPastJobs from './ReleasesPastJobs.svelte';
    import ReleasesTsSettings from './ReleasesTsSettings.svelte';
    import ReviewerHistoryView from './ReviewerHistoryView.svelte';

    export type RowExpandMode = 'ts' | 'timeline' | 'reviewers' | 'jobs';

    interface Props {
        row: ReleaseStatusRow;
        mode: RowExpandMode;
        /** Job id to poll live in the jobs view (set right after a launch). */
        activeJobId?: string | null;
        onlaunched: (_jobId: string) => void;
    }
    let { row, mode, activeJobId = null, onlaunched }: Props = $props();

    let detail = $state<AdminReviewDetail | null>(null);
    let detailLoading = $state(false);
    let detailError = $state<string | null>(null);

    const needsDetail = $derived(mode === 'timeline' || mode === 'reviewers');

    // Lazy-fetch the review detail when a detail view (timeline/reviewers) is
    // open. Key the effect ONLY on the stable inputs (needsDetail + row.slug) —
    // mirroring the Reviews drawer. Reading the mutable detail/detailLoading
    // flags here would make the effect's own `detailLoading = true` write
    // invalidate it; the re-run's cleanup then aborts the in-flight fetch, whose
    // aborted .then/.catch never clear detailLoading → stuck "Loading…" forever.
    $effect(() => {
        if (!needsDetail) return;
        const slug = row.slug;
        const ac = new AbortController();
        detail = null;
        detailLoading = true;
        detailError = null;
        fetchAdminReviewDetail(slug, ac.signal)
            .then((d) => {
                if (ac.signal.aborted) return;
                if (d === null) detailError = 'unknown slug';
                else detail = d;
                detailLoading = false;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                detailError = (e as Error).message ?? 'Failed to load detail';
                detailLoading = false;
            });
        return () => ac.abort();
    });
</script>

<div class="expansion">
    {#if mode === 'ts'}
        <ReleasesTsSettings {row} {onlaunched} />
    {:else if mode === 'jobs'}
        <ReleasesPastJobs slug={row.slug} {activeJobId} />
    {:else if detailLoading}
        <div class="muted">Loading…</div>
    {:else if detailError}
        <div class="muted err" role="alert">{detailError}</div>
    {:else if detail}
        {#if mode === 'timeline'}
            <div class="pad"><ExpandedTimeline transitions={detail.transitions ?? []} newestFirst /></div>
        {:else if mode === 'reviewers'}
            <ReviewerHistoryView {detail} />
        {/if}
    {/if}
</div>

<style>
    .expansion {
        border-top: 1px solid var(--border-quiet);
        background: var(--panel-2);
        padding: var(--s-1) var(--s-3) var(--s-3);
    }
    @media (prefers-reduced-motion: no-preference) {
        .expansion { animation: exp-in var(--t-fast) var(--ease-out-quart); }
    }
    @keyframes exp-in {
        from { opacity: 0; transform: translateY(-2px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .pad { padding: var(--s-2) var(--s-1); }
    .muted { font-size: var(--fs-meta); color: var(--text-faint); padding: var(--s-3) var(--s-1); }
    .muted.err { color: var(--state-error-fg); }
</style>
