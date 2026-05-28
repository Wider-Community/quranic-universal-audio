<script lang="ts">
    /**
     * Admin Reviews compartment.
     *
     * Fetches the per-recitation list once via /api/admin/reviews/list, splits
     * it across four state buckets, and renders a collapsible section per
     * bucket. Section order is fixed by priority: marked-ready first, available
     * last (collapsed by default — it's typically the longest tail).
     *
     * The state-vs-bucket mapping is computed FE-side from the canonical wire
     * shape; backend deliberately stays state-neutral. See
     * scripts/lib/schemas/admin_reviews.py for the bucket→predicate contract.
     *
     * Row body click opens the General drawer (M2). Action button drawers
     * (Ops) land in M3.
     */
    import { reviewsStore } from '../../../../../lib/stores/reviews.svelte';
    import { fetchAdminReviews } from '../../../../../lib/api/admin-reviews';
    import type {
        AdminReviewRow,
        AdminReviewsResponse,
    } from '../../../../../lib/types/generated/schemas';
    import ReviewsGeneralDrawer from './ReviewsGeneralDrawer.svelte';
    import ReviewsRow from './ReviewsRow.svelte';

    let resp = $state<AdminReviewsResponse | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    /** Bumping this triggers the fetch effect (used after an admin action
     * mutates state — the drawer calls back to invalidate). */
    let refetchSeq = $state(0);

    $effect(() => {
        refetchSeq;  // tracked dep
        const ac = new AbortController();
        loading = true;
        error = null;
        fetchAdminReviews(ac.signal)
            .then((r) => {
                if (ac.signal.aborted) return;
                resp = r;
                loading = false;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load reviews';
                loading = false;
            });
        return () => ac.abort();
    });

    function refetch(): void {
        refetchSeq += 1;
    }

    // Bucket predicates — see schemas/admin_reviews.py for the contract.
    function isMarkedReady(r: AdminReviewRow): boolean {
        return r.state === 'under_review' && !!r.open_claim?.marked_ready_at;
    }
    function isUnderReview(r: AdminReviewRow): boolean {
        return r.state === 'under_review' && !r.open_claim?.marked_ready_at;
    }
    function isPublished(r: AdminReviewRow): boolean {
        return r.state === 'awaiting_timestamps' || r.state === 'released';
    }
    function isAvailable(r: AdminReviewRow): boolean {
        return r.state === 'awaiting_review';
    }

    const rows = $derived(resp?.rows ?? []);
    const markedReady = $derived(rows.filter(isMarkedReady));
    const underReview = $derived(rows.filter(isUnderReview));
    const published = $derived(rows.filter(isPublished));
    const available = $derived(rows.filter(isAvailable));

    type SectionKey = 'marked_ready' | 'under_review' | 'published' | 'available';

    // Collapsed-by-default: only Available. The other three are where the
    // urgency lives.
    let collapsed = $state<Record<SectionKey, boolean>>({
        marked_ready: false,
        under_review: false,
        published: false,
        available: true,
    });

    function toggle(key: SectionKey): void {
        collapsed[key] = !collapsed[key];
    }

    // Section order is FIXED — see plan §State-machine mapping.
    const SECTIONS: { key: SectionKey; label: string; mark: string }[] = [
        { key: 'marked_ready', label: 'Marked ready', mark: 'marked-ready' },
        { key: 'under_review', label: 'Under review', mark: 'under-review' },
        { key: 'published', label: 'Published', mark: 'published' },
        { key: 'available', label: 'Available for review', mark: 'available' },
    ];

    function rowsFor(key: SectionKey): AdminReviewRow[] {
        switch (key) {
            case 'marked_ready': return markedReady;
            case 'under_review': return underReview;
            case 'published': return published;
            case 'available': return available;
        }
    }

    // Esc closes the drawer (mirror UsersCompartment's scrim+key dismissal).
    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape' && reviewsStore.openDrawer !== null) {
            reviewsStore.close();
        }
    }
</script>

<svelte:window on:keydown={onKey} />

<div class="reviews">
    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error" role="alert">{error}</div>
    {:else}
        {#each SECTIONS as section (section.key)}
            {@const sectionRows = rowsFor(section.key)}
            <section
                class="state-section"
                class:collapsed={collapsed[section.key]}
            >
                <button
                    class="state-head"
                    type="button"
                    aria-expanded={!collapsed[section.key]}
                    onclick={() => toggle(section.key)}
                >
                    <span class="state-mark {section.mark}"></span>
                    <span class="state-name">{section.label}</span>
                    <span class="state-count">{sectionRows.length}</span>
                    <span class="state-toggle" aria-hidden="true">▾</span>
                </button>
                {#if !collapsed[section.key]}
                    <div class="state-body">
                        {#if sectionRows.length === 0}
                            <div class="empty-line">No items.</div>
                        {:else}
                            <ul class="rows">
                                {#each sectionRows as row (row.slug)}
                                    <li>
                                        <ReviewsRow {row} />
                                    </li>
                                {/each}
                            </ul>
                        {/if}
                    </div>
                {/if}
            </section>
        {/each}
    {/if}

    {#if reviewsStore.selectedSlug && reviewsStore.openDrawer === 'general'}
        <div
            class="drawer-scrim"
            role="presentation"
            onclick={() => reviewsStore.close()}
        ></div>
        <ReviewsGeneralDrawer
            slug={reviewsStore.selectedSlug}
            onclose={() => reviewsStore.close()}
            onaction={refetch}
        />
    {/if}
</div>

<style>
    .reviews {
        position: relative;
        display: flex;
        flex-direction: column;
        padding: var(--s-3) var(--s-5) var(--s-5);
        gap: var(--s-3);
        height: 100%;
    }

    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-error-fg); }

    .state-head {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-1);
        background: transparent;
        border: 0;
        border-bottom: 1px solid var(--border-quiet);
        width: 100%;
        cursor: pointer;
        font: inherit;
        color: var(--text-primary);
        text-align: left;
        user-select: none;
    }
    .state-head:hover { background: var(--panel); }

    .state-mark {
        width: 8px;
        height: 8px;
        border-radius: 1px;
        flex: 0 0 auto;
    }
    .state-mark.marked-ready { background: oklch(0.84 0.130 70); }
    .state-mark.under-review { background: var(--state-under-review-fg); }
    .state-mark.published    { background: var(--state-published-fg); }
    .state-mark.available    { background: var(--state-available-fg); }

    .state-name {
        font-size: var(--fs-row);
        font-weight: 500;
        color: var(--text-primary);
    }
    .state-count {
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        font-variant-numeric: tabular-nums;
    }
    .state-toggle {
        margin-left: auto;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: 11px;
        transition: transform var(--t-fast) var(--ease-out-quart);
    }
    .state-section.collapsed .state-toggle { transform: rotate(-90deg); }

    .state-body { padding: 0; }

    .empty-line {
        font-size: var(--fs-body);
        color: var(--text-faint);
        padding: var(--s-3) var(--s-1);
    }

    .rows {
        list-style: none;
        padding: 0;
        margin: 0;
    }

    .drawer-scrim {
        position: absolute;
        inset: 0;
        background: oklch(0.06 0.005 268 / 0.45);
        z-index: 4;
    }
</style>
