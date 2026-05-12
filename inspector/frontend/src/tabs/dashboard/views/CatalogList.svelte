<script lang="ts">
    /**
     * Dashboard list-view orchestrator.
     * Standfirst → [FilterRail | catalog body] grid.
     *
     * Activity rail (Slice H) mounts later; for now the right column is
     * a placeholder that keeps the grid spaced correctly.
     */
    import { onMount } from 'svelte';

    import PickerFilterRail from '../../../lib/components/picker/PickerFilterRail.svelte';
    import {
        buildSchemaDescriptor,
        type SchemaDescriptor,
    } from '../../../lib/catalog/schema-descriptor';
    import FilterPill from '../../../lib/components/FilterPill.svelte';
    import { type FacetSpec, recomputeFacets } from '../../../lib/utils/facets';
    import { match } from '../../../lib/utils/fuzzy-match';
    import StatePill from '../../../lib/components/StatePill.svelte';
    import type { PublicBucket, PublicDelivery, PublicReciter } from '../../../lib/types/public-state';
    import AvailableToClaimStrip from '../components/AvailableToClaimStrip.svelte';
    import CatalogTable from '../components/CatalogTable.svelte';
    import Standfirst from '../components/Standfirst.svelte';
    import { catalogData, loadCatalog } from '../stores/catalog-data';
    import {
        clearAllFilters,
        dashboardState,
        openDetail,
        setBucket,
        setSearch,
        setSort,
        toggleFacet,
    } from '../stores/dashboard-state';

    onMount(() => {
        void loadCatalog();
    });

    let descriptor: SchemaDescriptor | null = null;
    $: if ($catalogData.reciters.length > 0) {
        descriptor = buildSchemaDescriptor($catalogData.reciters);
    }

    // bucket scope first, then facets, then search
    $: bucketScoped = $dashboardState.activeBucket
        ? $catalogData.reciters.filter((r) => r.primary_bucket === $dashboardState.activeBucket)
        : $catalogData.reciters;

    $: facetSpecs = (descriptor?.axes ?? []).map<FacetSpec<PublicReciter>>((a) => ({
        key: a.key,
        tagsOf: a.tagsOf,
    }));

    $: facetResult = recomputeFacets(bucketScoped, $dashboardState.activeFilters, facetSpecs);

    $: facetVisible = bucketScoped.filter((_, i) => facetResult.rowVisibility[i]);

    $: searched = $dashboardState.search
        ? facetVisible.filter((r) => match(r.name, $dashboardState.search))
        : facetVisible;

    $: sorted = sortReciters(searched, $dashboardState.sort);

    $: availableToClaim = $catalogData.reciters.filter(
        (r) => r.primary_bucket === 'available_for_review',
    );

    function sortReciters(rs: PublicReciter[], sort: typeof $dashboardState.sort): PublicReciter[] {
        const copy = [...rs];
        if (sort === 'alphabetical') {
            copy.sort((a, b) => a.name.localeCompare(b.name));
        } else if (sort === 'deliveries') {
            copy.sort((a, b) => b.deliveries_count - a.deliveries_count);
        } else {
            copy.sort((a, b) => {
                const ax = a.last_activity ?? '';
                const bx = b.last_activity ?? '';
                if (ax === bx) return a.name.localeCompare(b.name);
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
        $dashboardState.activeBucket !== null
        || $dashboardState.search.length > 0
        || hasActiveFacets();

    function onSearchInput(ev: Event): void {
        setSearch((ev.target as HTMLInputElement).value);
    }

    function onPlay(reciter: PublicReciter): void {
        // BottomPlayer wiring in Slice I; for now no-op.
        void reciter;
    }

    function onPlayDelivery(detail: { reciter: PublicReciter; delivery: PublicDelivery }): void {
        // BottomPlayer wiring in Slice I; for now no-op.
        void detail;
    }
</script>

<Standfirst stats={$catalogData.stats} on:select={(e) => setBucket(e.detail)} />

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
        <div class="sort-row">
            <span class="label">Sort</span>
            <FilterPill
                label="Recent"
                active={$dashboardState.sort === 'recent'}
                sort
                on:click={() => setSort('recent')}
            />
            <FilterPill
                label="A–Z"
                active={$dashboardState.sort === 'alphabetical'}
                sort
                on:click={() => setSort('alphabetical')}
            />
            <FilterPill
                label="Deliveries"
                active={$dashboardState.sort === 'deliveries'}
                sort
                on:click={() => setSort('deliveries')}
            />
        </div>
    </aside>

    <section class="body">
        {#if $catalogData.loading}
            <div class="state">Loading reciters…</div>
        {:else if $catalogData.error}
            <div class="state error">{$catalogData.error}</div>
        {:else}
            <div class="chips-bar" class:empty={!hasFilters}>
                <span class="chips-label">Filters</span>
                {#if $dashboardState.activeBucket}
                    <span class="chip">
                        <StatePill state={$dashboardState.activeBucket} size="sm" />
                        <button class="chip-close" aria-label="Clear bucket" on:click={() => setBucket(null)}>×</button>
                    </span>
                {/if}
                {#each Object.entries($dashboardState.activeFilters) as [axisKey, tags]}
                    {#each [...tags] as tag (axisKey + ':' + tag)}
                        <span class="chip">
                            {tag}
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

            <div class="search">
                <input
                    type="search"
                    placeholder="Search reciters"
                    value={$dashboardState.search}
                    on:input={onSearchInput}
                />
                <span class="search-count">{sorted.length} of {$catalogData.reciters.length}</span>
            </div>

            <AvailableToClaimStrip
                reciters={availableToClaim}
                on:open={(e) => openDetail(e.detail.reciter_id)}
                on:play={(e) => onPlay(e.detail)}
            />

            <CatalogTable
                reciters={sorted}
                on:open={(e) => openDetail(e.detail.reciter_id)}
                on:play={(e) => onPlay(e.detail)}
                on:playDelivery={(e) => onPlayDelivery(e.detail)}
            />
        {/if}
    </section>
</div>

<style>
    .grid {
        display: grid;
        grid-template-columns: 240px minmax(0, 1fr);
        gap: var(--s-6);
        padding: 0 var(--gutter) var(--s-12);
    }
    .rail {
        display: flex;
        flex-direction: column;
        gap: var(--s-5);
        padding-top: var(--s-5);
    }
    .sort-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
        padding-top: var(--s-2);
    }
    .sort-row .label {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
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
    .search {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3) 0;
    }
    .search input {
        flex: 1;
        max-width: 380px;
        padding: var(--s-2) var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-body);
        outline: none;
    }
    .search input:focus {
        border-color: var(--accent);
    }
    .search-count {
        font-size: 10.5px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
</style>
