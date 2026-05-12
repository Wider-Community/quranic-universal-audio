<script context="module" lang="ts">
    import type { PublicBucket, PublicDelivery, PublicReciter } from '../../types/public-state';

    /**
     * Result emitted on the `select` event. ``delivery`` is null only
     * when the reciter has zero deliveries (e.g. `requested` bucket);
     * the consumer decides whether such a selection is actionable.
     */
    export interface PickerSelection {
        kind: 'reciter';
        reciter: PublicReciter;
        delivery: PublicDelivery | null;
    }

    export interface InitialFilter {
        bucket?: PublicBucket;
        search?: string;
    }
</script>

<script lang="ts">
    /**
     * ReciterPicker — modal or inline reciter+delivery picker.
     *
     * - `modal` mode  : full overlay with Modal.svelte shell.
     * - `inline` mode : body-only (no modal chrome, no scroll-lock); the
     *                   consumer is responsible for its own enclosing chrome.
     *
     * Search uses ``fuzzy-match.ts`` (Arabic-normalizing); facets come from
     * ``buildSchemaDescriptor()`` so no taxonomy literals exist here.
     *
     * Keyboard: ↑↓ navigate, ↵ commit, Esc close, `/` focus search.
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';

    import { fetchPublicReciters, fetchPublicStats } from '../../api/public-reciters';
    import {
        buildSchemaDescriptor,
        type Axis,
        type SchemaDescriptor,
    } from '../../catalog/schema-descriptor';
    import StatePill from '../StatePill.svelte';
    import Modal from '../Modal.svelte';
    import { type FacetSpec, recomputeFacets } from '../../utils/facets';
    import { match } from '../../utils/fuzzy-match';
    import type { BucketCounts } from '../../types/public-state';
    import DeliveryPicker from './DeliveryPicker.svelte';
    import PickerFilterRail from './PickerFilterRail.svelte';
    import PickerFooter from './PickerFooter.svelte';
    import PickerHeader from './PickerHeader.svelte';
    import PickerStateTabs from './PickerStateTabs.svelte';

    export let open = true;
    export let mode: 'modal' | 'inline' = 'modal';
    export let title = 'Switch reciter';
    export let initialFilter: InitialFilter = {};

    const dispatch = createEventDispatcher<{
        select: PickerSelection;
        close: void;
        cancel: void;
    }>();

    let reciters: PublicReciter[] = [];
    let stats: BucketCounts | null = null;
    let descriptor: SchemaDescriptor | null = null;
    let loading = true;
    let error: string | null = null;

    let search = initialFilter.search ?? '';
    let activeBucket: PublicBucket | null = initialFilter.bucket ?? null;
    let activeFilters: Record<string, Set<string>> = {};
    let expandedSlug: string | null = null;
    let focusedIdx = -1;

    let headerEl: PickerHeader | null = null;
    let listEl: HTMLDivElement | null = null;

    onMount(() => {
        void load();
    });

    async function load(): Promise<void> {
        loading = true;
        error = null;
        try {
            const [page, s] = await Promise.all([
                fetchPublicReciters({ limit: 200 }),
                fetchPublicStats(),
            ]);
            reciters = page.reciters;
            stats = s;
            descriptor = buildSchemaDescriptor(reciters);
            for (const axis of descriptor.axes) {
                activeFilters[axis.key] = new Set();
            }
            activeFilters = activeFilters;
            await tick();
            headerEl?.focusSearch();
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load reciters';
        } finally {
            loading = false;
        }
    }

    // Bucket filtering happens first, then facets, then search.
    $: bucketScoped = activeBucket
        ? reciters.filter((r) => r.primary_bucket === activeBucket)
        : reciters;

    $: facetSpecs = (descriptor?.axes ?? []).map<FacetSpec<PublicReciter>>((axis: Axis) => ({
        key: axis.key,
        tagsOf: axis.tagsOf,
    }));

    $: facetResult = recomputeFacets(bucketScoped, activeFilters, facetSpecs);

    $: facetVisible = bucketScoped.filter((_, i) => facetResult.rowVisibility[i]);

    $: visible = search
        ? facetVisible.filter((r) => match(r.name, search))
        : facetVisible;

    $: resultsLabel =
        loading
            ? null
            : `${visible.length} of ${reciters.length}`;

    function toggleFacet(detail: { axis: string; tag: string }): void {
        const set = new Set(activeFilters[detail.axis] ?? []);
        if (set.has(detail.tag)) set.delete(detail.tag);
        else set.add(detail.tag);
        activeFilters = { ...activeFilters, [detail.axis]: set };
        focusedIdx = -1;
    }

    function selectBucket(b: PublicBucket | null): void {
        activeBucket = b;
        focusedIdx = -1;
    }

    function onRowClick(reciter: PublicReciter): void {
        if (reciter.deliveries_count <= 1) {
            commit(reciter, reciter.deliveries[0] ?? null);
        } else if (expandedSlug === reciter.deliveries[0]?.slug) {
            expandedSlug = null;
        } else {
            expandedSlug = reciter.deliveries[0]?.slug ?? null;
        }
    }

    function onDeliveryPick(reciter: PublicReciter, ev: CustomEvent<PublicDelivery>): void {
        commit(reciter, ev.detail);
    }

    function commit(reciter: PublicReciter, delivery: PublicDelivery | null): void {
        dispatch('select', { kind: 'reciter', reciter, delivery });
        dispatch('close');
    }

    function onSearch(ev: CustomEvent<string>): void {
        search = ev.detail;
        focusedIdx = visible.length > 0 ? 0 : -1;
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            focusedIdx = Math.min(focusedIdx + 1, visible.length - 1);
            if (focusedIdx < 0 && visible.length > 0) focusedIdx = 0;
            scrollFocusedIntoView();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            focusedIdx = Math.max(focusedIdx - 1, 0);
            scrollFocusedIntoView();
        } else if (e.key === 'Enter') {
            const r = visible[focusedIdx];
            if (r) {
                e.preventDefault();
                onRowClick(r);
            }
        } else if (e.key === '/') {
            const active = document.activeElement as HTMLElement | null;
            if (active?.tagName !== 'INPUT') {
                e.preventDefault();
                headerEl?.focusSearch();
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            dispatch('cancel');
            dispatch('close');
        }
    }

    function scrollFocusedIntoView(): void {
        if (!listEl) return;
        const el = listEl.querySelector<HTMLElement>('.row.focused');
        el?.scrollIntoView({ block: 'nearest' });
    }

    function onClose(): void {
        dispatch('cancel');
        dispatch('close');
    }

    function bucketCountsForTabs(): Partial<BucketCounts> {
        if (!stats) return {};
        if (!activeBucket) return stats;
        // Tab counts are absolute (global), not faceted by sibling filters.
        return stats;
    }
</script>

{#if mode === 'modal'}
    <Modal {open} {title} on:close={onClose}>
        <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
        <div
            class="picker modal-shell"
            role="dialog"
            aria-label={title}
            on:keydown={onKey}
            tabindex="-1"
        >
            <PickerHeader
                bind:this={headerEl}
                {title}
                {search}
                {resultsLabel}
                on:search={onSearch}
                on:close={onClose}
            />
            <PickerStateTabs
                activeBucket={activeBucket}
                totalCount={reciters.length}
                counts={bucketCountsForTabs()}
                on:select={(e) => selectBucket(e.detail)}
            />
            <div class="body">
                {#if descriptor}
                    <PickerFilterRail
                        axes={descriptor.axes}
                        {activeFilters}
                        perFacetCounts={facetResult.perFacetCounts}
                        on:toggle={(e) => toggleFacet(e.detail)}
                    />
                {/if}
                <div class="list" bind:this={listEl}>
                    {#if loading}
                        <div class="state">Loading…</div>
                    {:else if error}
                        <div class="state error">{error}</div>
                    {:else if visible.length === 0}
                        <div class="state">No matches. Try a different filter or search.</div>
                    {:else}
                        {#each visible as r, i (r.name + (r.deliveries[0]?.slug ?? ''))}
                            {@const expanded = r.deliveries[0]?.slug === expandedSlug}
                            <button
                                type="button"
                                class="row"
                                class:focused={i === focusedIdx}
                                class:expanded
                                on:click={() => onRowClick(r)}
                                on:mouseenter={() => (focusedIdx = i)}
                            >
                                <span class="row-name">{r.name}</span>
                                <span class="row-meta">
                                    {r.deliveries_count > 1
                                        ? `${r.deliveries_count} deliveries`
                                        : r.riwayat.join(' · ')}
                                </span>
                                <span class="row-state">
                                    <StatePill state={r.primary_bucket} size="sm" />
                                </span>
                            </button>
                            {#if expanded && r.deliveries.length > 1}
                                <DeliveryPicker
                                    deliveries={r.deliveries}
                                    on:pick={(ev) => onDeliveryPick(r, ev)}
                                />
                            {/if}
                        {/each}
                    {/if}
                </div>
            </div>
            <footer class="foot">
                <PickerFooter on:cancel={onClose} />
            </footer>
        </div>
    </Modal>
{:else}
    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
    <div
        class="picker inline"
        role="region"
        aria-label={title}
        on:keydown={onKey}
        tabindex="-1"
    >
        <PickerHeader
            bind:this={headerEl}
            {title}
            {search}
            {resultsLabel}
            on:search={onSearch}
            on:close={onClose}
        />
        <PickerStateTabs
            activeBucket={activeBucket}
            totalCount={reciters.length}
            counts={bucketCountsForTabs()}
            on:select={(e) => selectBucket(e.detail)}
        />
        <div class="body inline-body">
            {#if descriptor}
                <PickerFilterRail
                    axes={descriptor.axes}
                    {activeFilters}
                    perFacetCounts={facetResult.perFacetCounts}
                    on:toggle={(e) => toggleFacet(e.detail)}
                />
            {/if}
            <div class="list" bind:this={listEl}>
                {#if loading}
                    <div class="state">Loading…</div>
                {:else if error}
                    <div class="state error">{error}</div>
                {:else if visible.length === 0}
                    <div class="state">No matches.</div>
                {:else}
                    {#each visible as r, i (r.name + (r.deliveries[0]?.slug ?? ''))}
                        {@const expanded = r.deliveries[0]?.slug === expandedSlug}
                        <button
                            type="button"
                            class="row"
                            class:focused={i === focusedIdx}
                            class:expanded
                            on:click={() => onRowClick(r)}
                            on:mouseenter={() => (focusedIdx = i)}
                        >
                            <span class="row-name">{r.name}</span>
                            <span class="row-meta">
                                {r.deliveries_count > 1
                                    ? `${r.deliveries_count} deliveries`
                                    : r.riwayat.join(' · ')}
                            </span>
                            <span class="row-state">
                                <StatePill state={r.primary_bucket} size="sm" />
                            </span>
                        </button>
                        {#if expanded && r.deliveries.length > 1}
                            <DeliveryPicker
                                deliveries={r.deliveries}
                                on:pick={(ev) => onDeliveryPick(r, ev)}
                            />
                        {/if}
                    {/each}
                {/if}
            </div>
        </div>
    </div>
{/if}

<style>
    .picker {
        display: flex;
        flex-direction: column;
        height: 100%;
        min-height: 0;
        outline: none;
    }
    .body {
        display: grid;
        grid-template-columns: 220px 1fr;
        flex: 1;
        min-height: 0;
    }
    .inline-body { min-height: 360px; }
    .list {
        overflow-y: auto;
        padding: var(--s-2) 0 var(--s-4);
    }
    .state {
        padding: var(--s-12) var(--s-6);
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-publishing-fg); }

    .row {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-6);
        align-items: center;
        cursor: pointer;
        background: transparent;
        border: none;
        border-left: 2px solid transparent;
        text-align: left;
        transition: background var(--t-fast), border-color var(--t-fast);
    }
    .row:hover { background: var(--panel); }
    .row.focused {
        background: var(--panel);
        border-left-color: var(--accent);
    }
    .row-name {
        color: var(--text-primary);
        font-size: var(--fs-row);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .row-meta {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        white-space: nowrap;
    }
    .row-state {
        font-size: var(--fs-meta);
    }

    .foot {
        padding: var(--s-3) var(--s-6);
        border-top: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
</style>
