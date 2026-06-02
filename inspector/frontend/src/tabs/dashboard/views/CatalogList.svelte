<script lang="ts">
    /**
     * Dashboard list view. Filters operate on combinations (deliveries),
     * then visible combinations are grouped back by reciter for display.
     */
    import { onMount } from 'svelte';

    import {
        type Axis,
        buildSchemaDescriptor,
        type SchemaDescriptor,
    } from '../../../lib/catalog/schema-descriptor';
    import PickerFilterRail from '../../../lib/components/picker/PickerFilterRail.svelte';
    import SearchInput from '../../../lib/components/SearchInput.svelte';
    import { playerContext } from '../../../lib/stores/player-context';
    import { bucketRank, type PublicDelivery, type PublicReciter } from '../../../lib/types/public-state';
    import { axisLabel as axisLabelOf, tagLabel as tagLabelOf } from '../../../lib/utils/axis-labels';
    import { defaultCombination } from '../../../lib/utils/default-combination';
    import { type FacetSpec, recomputeFacets } from '../../../lib/utils/facets';
    import { match } from '../../../lib/utils/fuzzy-match';
    import ActivityRail from '../components/ActivityRail.svelte';
    import type { RowEntry } from '../components/CatalogTable.svelte';
    import CatalogTable from '../components/CatalogTable.svelte';
    import SubmitWizard from '../components/submit/SubmitWizard.svelte';
    import { catalogData, loadCatalog } from '../stores/catalog-data';
    import {
        clearAllFilters,
        type DashboardSort,
        dashboardState,
        openDetail,
        setSearch,
        setSort,
        toggleFacet,
        setFilterDrawer,
        setActivityDrawer,
    } from '../stores/dashboard-state';
    import { openSubmitWizard } from '../stores/submit-wizard';

    onMount(() => {
        void loadCatalog();
    });

    let descriptor: SchemaDescriptor | null = null;
    $: allDeliveries = $catalogData.reciters.flatMap((r) => r.deliveries);
    $: if (allDeliveries.length > 0 && descriptor === null) {
        descriptor = buildSchemaDescriptor(allDeliveries);
    }

    $: facetSpecs = (descriptor?.axes ?? []).map<FacetSpec<PublicDelivery>>((axis: Axis) => ({
        key: axis.key,
        tagsOf: axis.tagsOf,
    }));

    $: facetResult = recomputeFacets(allDeliveries, $dashboardState.activeFilters, facetSpecs);

    $: visibleDeliveries = allDeliveries.filter((_, i) => facetResult.rowVisibility[i]);

    // Group visible combinations back under their reciter.
    $: rowEntries = groupByReciter($catalogData.reciters, visibleDeliveries);

    $: searched = $dashboardState.search
        ? rowEntries.filter((e) => match(e.reciter.name, $dashboardState.search)
            || (e.reciter.name_ar && match(e.reciter.name_ar, $dashboardState.search)))
        : rowEntries;

    $: sorted = sortRows(searched, $dashboardState.sort);

    // Total reciters in the catalog (search-bar denominator).
    $: totalReciters = $catalogData.reciters.length;

    function groupByReciter(
        reciters: PublicReciter[],
        visible: PublicDelivery[],
    ): RowEntry[] {
        const bySlug = new Set(visible.map((d) => d.slug));
        const out: RowEntry[] = [];
        for (const r of reciters) {
            const vis = r.deliveries.filter((d) => bySlug.has(d.slug));
            if (vis.length === 0) continue;
            out.push({ reciter: r, visibleDeliveries: vis });
        }
        return out;
    }

    function sortRows(rs: RowEntry[], sort: DashboardSort): RowEntry[] {
        const copy = [...rs];
        if (sort === 'alphabetical') {
            copy.sort((a, b) => a.reciter.name.localeCompare(b.reciter.name));
        } else if (sort === 'combinations') {
            copy.sort((a, b) => b.visibleDeliveries.length - a.visibleDeliveries.length);
        } else if (sort === 'status') {
            copy.sort((a, b) => {
                const s = bucketRank(a.reciter.primary_bucket) - bucketRank(b.reciter.primary_bucket);
                if (s !== 0) return s;
                return a.reciter.name.localeCompare(b.reciter.name);
            });
        } else {
            copy.sort((a, b) => {
                const ax = a.reciter.last_activity ?? '';
                const bx = b.reciter.last_activity ?? '';
                if (ax === bx) return a.reciter.name.localeCompare(b.reciter.name);
                return ax < bx ? 1 : -1;
            });
        }
        return copy;
    }

    function hasActiveFacets(): boolean {
        for (const set of Object.values($dashboardState.activeFilters)) {
            if (set && set.size > 0) return true;
        }
        return false;
    }

    $: hasFilters =
        $dashboardState.search.length > 0
        || hasActiveFacets();

    function onSortChange(ev: Event): void {
        const value = (ev.target as HTMLSelectElement).value;
        setSort(value as DashboardSort);
    }

    function onPlay(row: RowEntry): void {
        // Only `by_surah` is playable — `by_ayah` sidecars key chapters as
        // `"<surah>:<ayah>"`, which the BottomPlayer's `urls[String(surahNum)]`
        // lookup misses. Prefer a visible by_surah delivery so the play button
        // honors active facets; bail if there's none.
        const playable = row.visibleDeliveries.filter((d) => d.audio_category !== 'by_ayah');
        const delivery = defaultCombination(playable);
        if (!delivery) return;
        playerContext.update((s) => ({
            ...s,
            reciter: row.reciter,
            delivery,
            surahNum: s.surahNum ?? 1,
            positionMs: 0,
            isPlaying: true,
        }));
    }

    const tagLabel = (axisKey: string, tag: string): string => tagLabelOf(descriptor, axisKey, tag);
    const axisLabel = (axisKey: string): string => axisLabelOf(descriptor, axisKey);
</script>

<div class="grid">
    <aside class="rail">
        {#if descriptor}
            <PickerFilterRail
                axes={descriptor.axes}
                activeFilters={$dashboardState.activeFilters}
                perFacetCounts={facetResult.perFacetCounts}
                on:toggle={(e) => toggleFacet(e.detail.axis, e.detail.tag)}
            />
        {/if}
    </aside>

    <section class="body">
        <div class="toolbar">
            <div class="search">
                <SearchInput
                    value={$dashboardState.search}
                    placeholder="Search reciters"
                    count={sorted.length}
                    total={totalReciters}
                    on:input={(e) => setSearch(e.detail)}
                />
            </div>
            <div class="sort">
                <label>
                    <span class="sort-label label-hide-mobile">Sort</span>
                    <select
                        value={$dashboardState.sort}
                        on:change={onSortChange}
                    >
                        <option value="recent">Recently updated</option>
                        <option value="status">Status</option>
                        <option value="alphabetical">A → Z</option>
                        <option value="combinations">Most combinations</option>
                    </select>
                </label>
            </div>
            <button
                type="button"
                class="submit-recitation"
                on:click={openSubmitWizard}
            >
                <span class="sr-glyph" aria-hidden="true">+</span>
                <span class="sr-label">Submit recitation</span>
            </button>
        </div>
        {#if $catalogData.loading}
            <div class="state">Loading reciters…</div>
        {:else if $catalogData.error}
            <div class="state error">{$catalogData.error}</div>
        {:else}
            <div class="chips-bar" class:empty={!hasFilters}>
                <span class="chips-label">Filters</span>
                {#each Object.entries($dashboardState.activeFilters) as [axisKey, tags]}
                    {#each [...tags] as tag (axisKey + ':' + tag)}
                        <span class="chip">
                            <span class="chip-axis">{axisLabel(axisKey)}:</span>
                            {tagLabel(axisKey, tag)}
                            <button class="chip-close" aria-label="Clear filter" on:click={() => toggleFacet(axisKey, tag)}>×</button>
                        </span>
                    {/each}
                {/each}
                {#if $dashboardState.search}
                    <span class="chip">
                        “{$dashboardState.search}”
                        <button class="chip-close" aria-label="Clear search" on:click={() => setSearch('')}>×</button>
                    </span>
                {/if}
                {#if hasFilters}
                    <button class="clear" on:click={clearAllFilters}>Clear all</button>
                {/if}
            </div>

            <CatalogTable
                rows={sorted}
                on:open={(e) => openDetail(e.detail.reciter_id)}
                on:play={(e) => onPlay(e.detail)}
            />
        {/if}
    </section>

    <div class="desktop-only-activity">
        <ActivityRail />
    </div>
</div>

<!-- Left / Right drawers for mobile view rendered natively in Svelte -->
<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div
    class="drawer-overlay"
    class:open={$dashboardState.filterDrawerOpen || $dashboardState.activityDrawerOpen}
    on:click={() => { setFilterDrawer(false); setActivityDrawer(false); }}
></div>

<aside class="drawer" class:open={$dashboardState.filterDrawerOpen} id="leftDrawer">
    <div class="drawer-head">
        <span class="drawer-title">Filters</span>
        <button class="icon-btn" aria-label="Close" on:click={() => setFilterDrawer(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 6l12 12M18 6L6 18"/>
            </svg>
        </button>
    </div>
    <div class="drawer-body">
        {#if descriptor}
            <PickerFilterRail
                axes={descriptor.axes}
                activeFilters={$dashboardState.activeFilters}
                perFacetCounts={facetResult.perFacetCounts}
                on:toggle={(e) => toggleFacet(e.detail.axis, e.detail.tag)}
            />
        {/if}
    </div>
</aside>

<aside class="drawer right" class:open={$dashboardState.activityDrawerOpen} id="rightDrawer">
    <div class="drawer-head">
        <span class="drawer-title">Recent activity</span>
        <button class="icon-btn" aria-label="Close" on:click={() => setActivityDrawer(false)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 6l12 12M18 6L6 18"/>
            </svg>
        </button>
    </div>
    <div class="drawer-body">
        <ActivityRail />
    </div>
</aside>

<SubmitWizard />

<style>
    .toolbar {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--s-4);
        padding: 0 0 var(--s-2);
        flex-wrap: nowrap;
    }
    /* Mobile toolbar: tighten gap, hide sort label, keep everything on one row, shrink search input and submit button */
    @media (max-width: 767px) {
        .toolbar {
            gap: var(--s-2);
            flex-wrap: nowrap;
        }
        .label-hide-mobile { display: none; }
        .search {
            min-width: 100px;
        }
        .sr-label {
            display: none;
        }
        .submit-recitation {
            padding: 0;
            width: 32px;
            justify-content: center;
            gap: 0;
        }
    }
    .search {
        flex: 1 1 auto;
        min-width: 140px;
        max-width: 420px;
    }
    .sort {
        flex-shrink: 0;
    }
    .sort label { display: inline-flex; align-items: center; gap: var(--s-2); }
    .sort-label {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .sort select {
        padding: var(--s-2) var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-meta);
        cursor: pointer;
    }
    .sort select:focus { border-color: var(--accent); outline: none; }
 
    .submit-recitation {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        height: 32px;
        padding: 0 var(--s-3);
        background: var(--accent);
        color: var(--accent-fg);
        border: 1px solid var(--accent);
        border-radius: var(--r-2);
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 500;
        cursor: pointer;
        transition: background var(--t-fast),
                    border-color var(--t-fast),
                    transform var(--t-fast),
                    box-shadow var(--t-base) var(--ease-out-quart);
        box-shadow: 0 1px 2px oklch(0 0 0 / 0.18);
        white-space: nowrap;
        flex-shrink: 0;
    }
    .submit-recitation:hover {
        background: var(--accent-strong);
        border-color: var(--accent-strong);
        box-shadow: 0 6px 18px oklch(0.785 0.13 220 / 0.18);
    }
    .submit-recitation:active { transform: translateY(1px); }
    .submit-recitation:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
    }
    .sr-glyph {
        font-size: 14px;
        line-height: 1;
        font-weight: 400;
        opacity: 0.9;
        transition: transform var(--t-base) var(--ease-out-quart);
    }
    .submit-recitation:hover .sr-glyph {
        transform: rotate(90deg);
    }
    .sr-label { letter-spacing: 0.01em; }

    .desktop-only-activity {
        display: contents;
    }
    .grid {
        display: grid;
        grid-template-columns: var(--sidebar-w, 260px) minmax(0, 1fr) var(--activity-w, 300px);
        gap: var(--s-6);
        padding: 0 var(--gutter) var(--s-12);
        min-height: calc(100vh - var(--header-h, 76px) - var(--player-h, 72px));
    }
    .rail {
        display: flex;
        flex-direction: column;
        gap: var(--s-5);
        padding-top: var(--s-3);
    }
    /* Web view intermediate widths: hide activity panel but keep filters sidebar */
    @media (max-width: 1280px) {
        .grid { grid-template-columns: var(--sidebar-w, 260px) minmax(0, 1fr); }
        .desktop-only-activity { display: none; }
    }
    /* Mobile <900px: full-width single column, hide both sidebar filters and recent activities */
    @media (max-width: 899px) {
        .grid { grid-template-columns: 1fr; }
        .rail { display: none; }
        .desktop-only-activity { display: none; }
    }
    .body { min-width: 0; }
    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-error-fg); }

    .chips-bar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-3) 0 var(--s-4);
        border-bottom: 1px solid var(--border-quiet);
        min-height: 32px;
    }
    .chips-bar.empty { min-height: 0; padding: 0; border-bottom: none; }
    .chips-bar.empty > * { display: none; }
    .chips-label {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-right: var(--s-2);
    }
    .chip {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        padding: 3px var(--s-2);
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-meta);
    }
    .chip-axis {
        color: var(--text-muted);
        text-transform: lowercase;
    }
    .chip-close {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: 14px;
        line-height: 1;
        padding: 0 0 0 2px;
        cursor: pointer;
        transition: color var(--t-fast);
    }
    .chip-close:hover { color: var(--accent-strong); }
    .clear {
        background: transparent;
        border: 0;
        margin-left: auto;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        text-decoration: underline;
        text-decoration-color: var(--border-default);
        text-underline-offset: 3px;
        cursor: pointer;
    }
    .clear:hover { color: var(--text-primary); }

    /* ── Drawer overlay ── */
    .drawer-overlay {
        position: fixed;
        inset: 0;
        background: rgba(10, 16, 32, 0.6);
        backdrop-filter: blur(4px);
        -webkit-backdrop-filter: blur(4px);
        z-index: 90;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.35s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .drawer-overlay.open {
        opacity: 1;
        pointer-events: auto;
    }

    /* ── Drawer panel ── */
    .drawer {
        display: none;
    }

    /* Show drawers only below 900px */
    @media (max-width: 899px) {
        .drawer {
            display: block;
            position: fixed;
            top: 0;
            bottom: 0;
            left: 0;
            width: 300px;
            background: var(--panel);
            border-right: 1px solid var(--border-default);
            z-index: 130;
            padding: 16px;
            overflow-y: auto;
            transform: translateX(-100%);
            visibility: hidden;
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1),
                        visibility 0.35s cubic-bezier(0.16, 1, 0.3, 1);
        }
        .drawer-overlay {
            z-index: 120;
        }
        .drawer.open {
            transform: translateX(0);
            visibility: visible;
        }
        .drawer.right {
            left: auto;
            right: 0;
            border-right: none;
            border-left: 1px solid var(--border-default);
            transform: translateX(100%);
        }
        .drawer.right.open {
            transform: translateX(0);
        }
    }

    .drawer-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 14px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--border-quiet);
    }
    .drawer-title {
        font-weight: 600;
        color: var(--text-primary);
        font-size: 14px;
    }
    .drawer-body {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    /* Close button base style inside drawers */
    .icon-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        border-radius: var(--radius-md, 6px);
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s, color 0.15s;
    }
    .icon-btn:hover {
        background: var(--panel-2);
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .icon-btn svg { width: 16px; height: 16px; display: block; }
</style>
