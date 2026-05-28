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
    import ReviewsOpsDrawer from './ReviewsOpsDrawer.svelte';
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

    const allRows = $derived(resp?.rows ?? []);

    // Filter — q matches Arabic + Latin name; facets are AND-combined.
    function matchFilter(r: AdminReviewRow): boolean {
        const f = reviewsStore.filters;
        const q = f.q.trim().toLowerCase();
        if (q) {
            const ar = (r.name_ar ?? '').toLowerCase();
            const en = (r.name_en ?? '').toLowerCase();
            if (!ar.includes(q) && !en.includes(q)) return false;
        }
        if (f.riwayah && r.riwayah !== f.riwayah) return false;
        if (f.style && r.style !== f.style) return false;
        if (f.channel && r.channel !== f.channel) return false;
        return true;
    }

    // Sort — "stalled first" sorts by state_since ASC (longest time in state
    // surfaces first); "name" sorts by Latin reciter name ASC.
    function compareRows(a: AdminReviewRow, b: AdminReviewRow): number {
        if (reviewsStore.sortBy === 'name') {
            return (a.name_en ?? a.reciter_id).localeCompare(b.name_en ?? b.reciter_id);
        }
        const aTs = a.state_since ?? '';
        const bTs = b.state_since ?? '';
        return aTs.localeCompare(bTs);
    }

    const filteredRows = $derived(allRows.filter(matchFilter).sort(compareRows));

    // Facet value lists (sorted, with counts from the full unfiltered set).
    function countBy(rows: AdminReviewRow[], key: 'riwayah' | 'style' | 'channel'): Array<[string, number]> {
        const m = new Map<string, number>();
        for (const r of rows) {
            const v = r[key];
            if (!v) continue;
            m.set(v, (m.get(v) ?? 0) + 1);
        }
        return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    }

    const riwayahValues = $derived(countBy(allRows, 'riwayah'));
    const styleValues = $derived(countBy(allRows, 'style'));
    const channelValues = $derived(countBy(allRows, 'channel'));

    const markedReady = $derived(filteredRows.filter(isMarkedReady));
    const underReview = $derived(filteredRows.filter(isUnderReview));
    const published = $derived(filteredRows.filter(isPublished));
    const available = $derived(filteredRows.filter(isAvailable));

    const narrowedToZero = $derived(
        allRows.length > 0
            && filteredRows.length === 0
            && reviewsStore.hasActiveFilters,
    );

    type SectionKey = 'marked_ready' | 'under_review' | 'published' | 'available';

    const COLLAPSE_LS_KEY = 'insp_reviews_collapsed';

    // Collapsed-by-default: only Available. The other three are where the
    // urgency lives. Cached to localStorage so the maintainer's section
    // preferences persist across reloads.
    function loadCollapsed(): Record<SectionKey, boolean> {
        const fallback: Record<SectionKey, boolean> = {
            marked_ready: false,
            under_review: false,
            published: false,
            available: true,
        };
        try {
            const raw = localStorage.getItem(COLLAPSE_LS_KEY);
            if (!raw) return fallback;
            const parsed = JSON.parse(raw) as Partial<Record<SectionKey, boolean>>;
            return {
                marked_ready: parsed.marked_ready ?? fallback.marked_ready,
                under_review: parsed.under_review ?? fallback.under_review,
                published: parsed.published ?? fallback.published,
                available: parsed.available ?? fallback.available,
            };
        } catch {
            return fallback;
        }
    }

    let collapsed = $state<Record<SectionKey, boolean>>(loadCollapsed());

    function toggle(key: SectionKey): void {
        collapsed[key] = !collapsed[key];
        try {
            localStorage.setItem(COLLAPSE_LS_KEY, JSON.stringify(collapsed));
        } catch {
            /* localStorage unavailable — toggle still works for this session */
        }
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
        <!-- Filter bar -->
        <div class="filter-bar">
            <span class="search">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14.5" y2="14.5" />
                </svg>
                <input
                    type="text"
                    placeholder="Search reciter (Arabic or Latin)"
                    value={reviewsStore.filters.q}
                    oninput={(e) => reviewsStore.setQ((e.currentTarget as HTMLInputElement).value)}
                />
            </span>

            <div class="facet-group">
                <span class="facet-label">Riwayah</span>
                {#each riwayahValues as [val, count] (val)}
                    <button
                        class="chip"
                        class:active={reviewsStore.filters.riwayah === val}
                        type="button"
                        onclick={() => reviewsStore.toggleFacet('riwayah', val)}
                    >{val} <span class="c-count">{count}</span></button>
                {/each}
            </div>

            <div class="facet-group">
                <span class="facet-label">Style</span>
                {#each styleValues as [val, count] (val)}
                    <button
                        class="chip"
                        class:active={reviewsStore.filters.style === val}
                        type="button"
                        onclick={() => reviewsStore.toggleFacet('style', val)}
                    >{val} <span class="c-count">{count}</span></button>
                {/each}
            </div>

            <div class="facet-group channel-group">
                <span class="facet-label">Channel</span>
                {#each channelValues as [val, count] (val)}
                    <button
                        class="chip"
                        class:active={reviewsStore.filters.channel === val}
                        type="button"
                        onclick={() => reviewsStore.toggleFacet('channel', val)}
                    >{val} <span class="c-count">{count}</span></button>
                {/each}
            </div>

            <div class="filter-trail">
                <label class="sort">
                    <span>sort</span>
                    <select
                        value={reviewsStore.sortBy}
                        onchange={(e) => reviewsStore.setSort(
                            (e.currentTarget as HTMLSelectElement).value as 'stalled' | 'name',
                        )}
                    >
                        <option value="stalled">stalled first</option>
                        <option value="name">name</option>
                    </select>
                </label>
                {#if reviewsStore.hasActiveFilters}
                    <button class="clear-btn" type="button" onclick={() => reviewsStore.clearFilters()}>
                        Clear
                    </button>
                {/if}
            </div>
        </div>

        {#if narrowedToZero}
            <div class="narrowed">
                <span>No recitations match the active filter.</span>
                <button class="clear-link" type="button" onclick={() => reviewsStore.clearFilters()}>
                    Clear filters
                </button>
            </div>
        {/if}

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

    {#if reviewsStore.selectedSlug && reviewsStore.openDrawer !== null}
        <div
            class="drawer-scrim"
            role="presentation"
            onclick={() => reviewsStore.close()}
        ></div>
        {#if reviewsStore.openDrawer === 'general'}
            <ReviewsGeneralDrawer
                slug={reviewsStore.selectedSlug}
                onclose={() => reviewsStore.close()}
                onaction={refetch}
            />
        {:else if reviewsStore.openDrawer === 'ops'}
            <ReviewsOpsDrawer
                slug={reviewsStore.selectedSlug}
                onclose={() => reviewsStore.close()}
                onaction={refetch}
            />
        {/if}
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

    /* filter bar */
    .filter-bar {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        flex-wrap: wrap;
        padding: var(--s-1) var(--s-1) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-2);
    }
    .search {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        height: 28px;
        padding: 0 var(--s-3);
        min-width: 220px;
        color: var(--text-muted);
        flex: 0 0 auto;
    }
    .search svg { width: 14px; height: 14px; flex-shrink: 0; }
    .search input {
        flex: 1;
        background: transparent;
        border: 0;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        outline: 0;
        min-width: 120px;
    }
    .search input::placeholder { color: var(--text-faint); }
    .search:focus-within {
        border-color: var(--accent-tint);
        box-shadow: 0 0 0 2px var(--accent-tint-soft);
    }

    .facet-group {
        display: flex;
        align-items: center;
        gap: 6px;
        max-width: 100%;
        flex-wrap: wrap;
    }
    .channel-group {
        max-width: 360px;
        overflow-x: auto;
        flex-wrap: nowrap;
        scrollbar-width: thin;
    }
    .facet-label {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-right: 2px;
    }
    .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        height: 24px;
        padding: 0 8px;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: var(--text-secondary);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
        white-space: nowrap;
        transition: color var(--t-fast), border-color var(--t-fast), background-color var(--t-fast);
    }
    .chip:hover { border-color: var(--border-default); color: var(--text-primary); }
    .chip.active {
        color: var(--text-primary);
        border-color: var(--accent-tint);
        background: var(--accent-tint-soft);
    }
    .c-count {
        font-family: var(--font-mono);
        color: var(--text-faint);
        font-size: 10px;
        font-variant-numeric: tabular-nums;
    }
    .chip.active .c-count { color: var(--accent-strong); }

    .filter-trail {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        margin-left: auto;
    }
    .sort {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .sort select {
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font: inherit;
        font-size: 11px;
        padding: 3px 6px;
        border-radius: var(--r-1);
        cursor: pointer;
    }
    .sort select:focus { outline: 0; border-color: var(--accent-tint); }

    .clear-btn {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-muted);
        font: inherit;
        font-size: 11px;
        padding: 3px 10px;
        border-radius: var(--r-1);
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .clear-btn:hover { color: var(--text-primary); border-color: var(--border-default); }

    .narrowed {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-1);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-2);
    }
    .clear-link {
        background: transparent;
        border: 0;
        color: var(--accent);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0;
    }
    .clear-link:hover { color: var(--accent-strong); text-decoration: underline; }
</style>
