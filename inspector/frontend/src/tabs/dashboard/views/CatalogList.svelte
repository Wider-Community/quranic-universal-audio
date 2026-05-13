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
    import { playerContext } from '../../../lib/stores/player-context';
    import type { PublicDelivery, PublicReciter } from '../../../lib/types/public-state';
    import { defaultCombination } from '../../../lib/utils/default-combination';
    import { titleCaseSlug } from '../../../lib/utils/delivery-label';
    import { type FacetSpec, recomputeFacets } from '../../../lib/utils/facets';
    import { match } from '../../../lib/utils/fuzzy-match';
    import ActivityRail from '../components/ActivityRail.svelte';
    import type { RowEntry } from '../components/CatalogTable.svelte';
    import CatalogTable from '../components/CatalogTable.svelte';
    import Standfirst from '../components/Standfirst.svelte';
    import { catalogData, loadCatalog } from '../stores/catalog-data';
    import {
        clearAllFilters,
        type DashboardSort,
        dashboardState,
        openDetail,
        setSearch,
        setSort,
        toggleFacet,
    } from '../stores/dashboard-state';

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

    // Standfirst totals from the full catalog (not filtered).
    $: totalReciters = $catalogData.reciters.length;
    $: totalCombinations = allDeliveries.length;
    $: totalChannels = new Set(allDeliveries.map((d) => d.channel)).size;

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

    function onSearchInput(ev: Event): void {
        setSearch((ev.target as HTMLInputElement).value);
    }

    function onSortChange(ev: Event): void {
        const value = (ev.target as HTMLSelectElement).value;
        setSort(value as DashboardSort);
    }

    function onPlay(reciter: PublicReciter): void {
        const delivery = defaultCombination(reciter.deliveries);
        if (!delivery) return;
        playerContext.update((s) => ({
            ...s,
            reciter,
            delivery,
            surahNum: s.surahNum ?? 1,
            positionMs: 0,
            isPlaying: true,
        }));
    }

    function tagLabel(axisKey: string, tag: string): string {
        if (!descriptor) return tag;
        const axis = descriptor.axes.find((a) => a.key === axisKey);
        const option = axis?.options.find((o) => o.key === tag);
        return option?.label ?? titleCaseSlug(tag);
    }

    function axisLabel(axisKey: string): string {
        if (!descriptor) return axisKey;
        return descriptor.axes.find((a) => a.key === axisKey)?.label ?? axisKey;
    }
</script>

<Standfirst
    reciterCount={totalReciters}
    combinationCount={totalCombinations}
    channelCount={totalChannels}
/>

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
                <input
                    type="search"
                    placeholder="Search reciters"
                    value={$dashboardState.search}
                    on:input={onSearchInput}
                />
                <span class="search-count">{sorted.length} of {totalReciters}</span>
            </div>
            <div class="sort">
                <label>
                    <span class="sort-label">Sort</span>
                    <select
                        value={$dashboardState.sort}
                        on:change={onSortChange}
                    >
                        <option value="recent">Recently updated</option>
                        <option value="alphabetical">A → Z</option>
                        <option value="combinations">Most combinations</option>
                    </select>
                </label>
            </div>
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

    <ActivityRail />
</div>

<style>
    .toolbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-4);
        padding: 0 0 var(--s-2);
        flex-wrap: wrap;
    }
    .search { display: flex; align-items: center; gap: var(--s-3); flex: 1; min-width: 240px; }
    .search input {
        flex: 1;
        max-width: 420px;
        padding: var(--s-2) var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-body);
        outline: none;
    }
    .search input:focus { border-color: var(--accent); }
    .search-count {
        font-size: 10.5px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
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

    .grid {
        display: grid;
        grid-template-columns: 300px minmax(0, 1fr) 320px;
        gap: var(--s-6);
        padding: 0 var(--gutter) var(--s-12);
    }
    @media (max-width: 1280px) {
        .grid { grid-template-columns: 330px minmax(0, 1fr); }
        .grid :global(.activity) { display: none; }
    }
    @media (max-width: 900px) {
        .grid { grid-template-columns: 1fr; }
    }
    .rail {
        display: flex;
        flex-direction: column;
        gap: var(--s-5);
        padding-top: var(--s-3);
    }
    .body { min-width: 0; }
    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-publishing-fg); }

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
</style>
