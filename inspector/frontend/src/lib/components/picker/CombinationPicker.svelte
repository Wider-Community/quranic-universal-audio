<script context="module" lang="ts">
    import type { PublicBucket, PublicDelivery, PublicReciter } from '../../types/public-state';

    /** One row in the combination picker — a `(reciter, delivery)` pair. */
    export interface CombinationSelection {
        kind: 'combination';
        reciter: PublicReciter;
        delivery: PublicDelivery;
    }

    export interface InitialFilter {
        bucket?: PublicBucket;
        search?: string;
    }
</script>

<script lang="ts">
    /**
     * CombinationPicker — modal picker keyed on (reciter, delivery) pairs.
     *
     * Sister to ReciterPicker, but every row is a delivery (one reciter can
     * appear multiple times in different buckets). The user's active claim
     * is pinned to the top in a "Your active claim" section; the rest are
     * grouped by `delivery.bucket` in the workflow order
     *   available_for_review → under_review → publishing → published.
     *
     * Only emits `select` for a non-null delivery. Audio preview is a
     * bubbled `preview` event — this component doesn't touch audio itself.
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';

    import { fetchPublicReciters, fetchPublicStats } from '../../api/public-reciters';
    import {
        type Axis,
        buildSchemaDescriptor,
        type SchemaDescriptor,
    } from '../../catalog/schema-descriptor';
    import { currentUser } from '../../stores/current-user';
    import { type BucketCounts, PUBLIC_BUCKET_LABELS } from '../../types/public-state';
    import { type FacetSpec, recomputeFacets } from '../../utils/facets';
    import { match } from '../../utils/fuzzy-match';
    import Modal from '../Modal.svelte';
    import StatePill from '../StatePill.svelte';
    import PickerFilterRail from './PickerFilterRail.svelte';
    import PickerFooter from './PickerFooter.svelte';
    import PickerHeader from './PickerHeader.svelte';
    import PickerStateTabs from './PickerStateTabs.svelte';

    interface Combo {
        reciter: PublicReciter;
        delivery: PublicDelivery;
    }

    export let open = true;
    export let title = 'Switch reciter';
    export let initialFilter: InitialFilter = {};
    /** Buckets eligible to appear in the picker. */
    export let allowedBuckets: readonly PublicBucket[] = [
        'available_for_review',
        'under_review',
        'publishing',
        'published',
    ];

    const dispatch = createEventDispatcher<{
        select: CombinationSelection;
        preview: { delivery: PublicDelivery };
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
    let focusedIdx = -1;

    let searchInputEl: HTMLInputElement | null = null;
    let listEl: HTMLDivElement | null = null;

    // Group order for non-pinned rows.
    const GROUP_ORDER: PublicBucket[] = [
        'available_for_review',
        'under_review',
        'publishing',
        'published',
    ];

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
            const allDeliveries = reciters.flatMap((r) => r.deliveries);
            descriptor = buildSchemaDescriptor(allDeliveries);
            for (const axis of descriptor.axes) {
                activeFilters[axis.key] = new Set();
            }
            activeFilters = activeFilters;
            await tick();
            searchInputEl?.focus();
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load reciters';
        } finally {
            loading = false;
        }
    }

    // Filter axes to the three relevant for combinations (no status,
    // no mushaf coverage, no recording context) — the state tabs already
    // cover bucket; the rail keeps cross-cutting taxonomy axes only.
    $: railAxes = (descriptor?.axes ?? []).filter((a) =>
        a.key === 'riwayah' || a.key === 'style' || a.key === 'channel',
    );

    // Flatten reciters into combos, keeping only deliveries whose own
    // bucket is in allowedBuckets — a reciter can show up twice if its
    // deliveries land in different buckets.
    $: allCombos = reciters.flatMap<Combo>((r) =>
        r.deliveries
            .filter((d) => allowedBuckets.includes(d.bucket))
            .map((d) => ({ reciter: r, delivery: d })),
    );

    $: bucketScoped = activeBucket
        ? allCombos.filter((c) => c.delivery.bucket === activeBucket)
        : allCombos;

    $: facetSpecs = railAxes.map<FacetSpec<Combo>>((axis: Axis) => ({
        key: axis.key,
        tagsOf: (c: Combo) => [...axis.tagsOf(c.delivery)],
    }));

    $: facetResult = recomputeFacets(bucketScoped, activeFilters, facetSpecs);
    $: facetVisible = bucketScoped.filter((_, i) => facetResult.rowVisibility[i]);
    $: visible = search
        ? facetVisible.filter(
              (c) => match(c.reciter.name, search)
                  || (c.reciter.name_ar ? match(c.reciter.name_ar, search) : false),
          )
        : facetVisible;

    // Split into pinned (active claim) + groups by bucket.
    $: mineSlug = $currentUser?.active_claim ?? null;
    $: mineRow = mineSlug
        ? visible.find((c) => c.delivery.slug === mineSlug) ?? null
        : null;
    $: restRows = mineRow
        ? visible.filter((c) => c.delivery.slug !== mineSlug)
        : visible;
    $: groupedRest = (() => {
        const out: Array<{ bucket: PublicBucket; rows: Combo[] }> = [];
        for (const b of GROUP_ORDER) {
            const rows = restRows.filter((c) => c.delivery.bucket === b);
            if (rows.length > 0) out.push({ bucket: b, rows });
        }
        return out;
    })();

    // Flat list of all visible rows in display order — drives keyboard nav.
    $: orderedRows = mineRow
        ? [mineRow, ...groupedRest.flatMap((g) => g.rows)]
        : groupedRest.flatMap((g) => g.rows);

    $: resultsLabel = loading ? null : `${orderedRows.length} of ${allCombos.length}`;

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

    function commit(combo: Combo): void {
        dispatch('select', {
            kind: 'combination',
            reciter: combo.reciter,
            delivery: combo.delivery,
        });
        dispatch('close');
    }

    function onPreview(ev: Event, combo: Combo): void {
        ev.stopPropagation();
        dispatch('preview', { delivery: combo.delivery });
    }

    function onSearchInput(e: Event): void {
        search = (e.target as HTMLInputElement).value;
        focusedIdx = orderedRows.length > 0 ? 0 : -1;
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            focusedIdx = Math.min(focusedIdx + 1, orderedRows.length - 1);
            if (focusedIdx < 0 && orderedRows.length > 0) focusedIdx = 0;
            scrollFocusedIntoView();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            focusedIdx = Math.max(focusedIdx - 1, 0);
            scrollFocusedIntoView();
        } else if (e.key === 'Enter') {
            const c = orderedRows[focusedIdx];
            if (c) {
                e.preventDefault();
                commit(c);
            }
        } else if (e.key === '/') {
            const active = document.activeElement as HTMLElement | null;
            if (active?.tagName !== 'INPUT') {
                e.preventDefault();
                searchInputEl?.focus();
            }
        } else if (e.key === ' ') {
            const c = orderedRows[focusedIdx];
            const active = document.activeElement as HTMLElement | null;
            if (c && active?.tagName !== 'INPUT') {
                e.preventDefault();
                dispatch('preview', { delivery: c.delivery });
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            dispatch('cancel');
            dispatch('close');
        }
    }

    function scrollFocusedIntoView(): void {
        if (!listEl) return;
        const el = listEl.querySelector<HTMLElement>('.combo-row.focused');
        el?.scrollIntoView({ block: 'nearest' });
    }

    function onClose(): void {
        dispatch('cancel');
        dispatch('close');
    }

    function bucketCountsForTabs(): Partial<BucketCounts> {
        if (!stats) return {};
        return stats;
    }

    function deliveryMeta(d: PublicDelivery): string {
        const parts: string[] = [];
        if (d.riwayah) parts.push(d.riwayah);
        if (d.style) parts.push(d.style);
        if (d.channel_name) parts.push(d.channel_name);
        else if (d.channel) parts.push(d.channel);
        return parts.join(' · ');
    }

    function coverageLabel(d: PublicDelivery): string {
        if (d.coverage_kind === 'full') return 'Full';
        return `${d.chapter_count}/114`;
    }

    function hoursLabel(d: PublicDelivery): string {
        if (d.total_duration_sec == null) return '—';
        const h = d.total_duration_sec / 3600;
        if (h < 1) return `${Math.round(h * 60)}m`;
        return `${h.toFixed(1)}h`;
    }
</script>

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
            compact
            {title}
            on:close={onClose}
        />

        <div class="picker-controls">
            <div class="picker-controls-search">
                <span class="search-icon" aria-hidden="true">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="11" cy="11" r="7" />
                        <path d="M21 21l-4.35-4.35" />
                    </svg>
                </span>
                <input
                    bind:this={searchInputEl}
                    type="text"
                    autocomplete="off"
                    placeholder="Search reciters — name in English or Arabic"
                    value={search}
                    on:input={onSearchInput}
                />
                {#if resultsLabel}
                    <span class="results-hint">{resultsLabel}</span>
                {/if}
            </div>
            <div class="picker-controls-tabs">
                <PickerStateTabs
                    {activeBucket}
                    {allowedBuckets}
                    totalCount={allCombos.length}
                    counts={bucketCountsForTabs()}
                    on:select={(e) => selectBucket(e.detail)}
                />
            </div>
        </div>

        <div class="body">
            {#if descriptor}
                <PickerFilterRail
                    axes={railAxes}
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
                {:else if orderedRows.length === 0}
                    <div class="state">No matches. Try a different filter or search.</div>
                {:else}
                    {#if mineRow}
                        <div class="picker-section-head mine-head">
                            <span class="mine-dot" aria-hidden="true"></span>
                            Your active claim
                        </div>
                        {@const c = mineRow}
                        {@const idx = 0}
                        <!-- svelte-ignore a11y-click-events-have-key-events -->
                        <div
                            class="combo-row"
                            class:focused={idx === focusedIdx}
                            role="button"
                            tabindex="0"
                            on:click={() => commit(c)}
                            on:mouseenter={() => (focusedIdx = idx)}
                        >
                            <button
                                type="button"
                                class="play-btn"
                                aria-label="Preview audio"
                                on:click={(e) => onPreview(e, c)}
                            >▶</button>
                            <span class="row-name">{c.reciter.name}</span>
                            <span class="row-meta">{deliveryMeta(c.delivery)}</span>
                            <span class="row-coverage">{coverageLabel(c.delivery)}</span>
                            <span class="row-hours">{hoursLabel(c.delivery)}</span>
                            <span class="row-state">
                                <StatePill state={c.delivery.bucket} size="sm" />
                            </span>
                        </div>
                    {/if}
                    {#each groupedRest as group (group.bucket)}
                        <div class="picker-section-head">
                            {PUBLIC_BUCKET_LABELS[group.bucket]}
                            <span class="head-count">{group.rows.length}</span>
                        </div>
                        {#each group.rows as c (c.delivery.slug)}
                            {@const idx = orderedRows.indexOf(c)}
                            <!-- svelte-ignore a11y-click-events-have-key-events -->
                            <div
                                class="combo-row"
                                class:focused={idx === focusedIdx}
                                role="button"
                                tabindex="0"
                                on:click={() => commit(c)}
                                on:mouseenter={() => (focusedIdx = idx)}
                            >
                                <button
                                    type="button"
                                    class="play-btn"
                                    aria-label="Preview audio"
                                    on:click={(e) => onPreview(e, c)}
                                >▶</button>
                                <span class="row-name">{c.reciter.name}</span>
                                <span class="row-meta">{deliveryMeta(c.delivery)}</span>
                                <span class="row-coverage">{coverageLabel(c.delivery)}</span>
                                <span class="row-hours">{hoursLabel(c.delivery)}</span>
                                <span class="row-state">
                                    <StatePill state={c.delivery.bucket} size="sm" />
                                </span>
                            </div>
                        {/each}
                    {/each}
                {/if}
            </div>
        </div>

        <footer class="foot">
            <PickerFooter on:cancel={onClose} />
        </footer>
    </div>
</Modal>

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

    .picker-controls-search {
        position: relative;
        display: flex;
        align-items: center;
        width: 360px;
        flex-shrink: 0;
    }
    .search-icon {
        position: absolute;
        left: var(--s-3);
        color: var(--text-faint);
        pointer-events: none;
        display: flex;
    }
    .picker-controls-search input {
        width: 100%;
        padding: var(--s-3) var(--s-3) var(--s-3) calc(var(--s-3) + 24px);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-body);
        outline: none;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .picker-controls-search input:focus {
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .picker-controls-search input::placeholder { color: var(--text-faint); }
    .results-hint {
        position: absolute;
        right: var(--s-3);
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        pointer-events: none;
    }
    .picker-controls-tabs {
        flex: 1;
        min-width: 0;
    }
    .picker-controls-tabs :global(.tabs) {
        padding: 0;
        border-bottom: none;
    }

    .foot {
        padding: var(--s-3) var(--s-6);
        border-top: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
</style>
