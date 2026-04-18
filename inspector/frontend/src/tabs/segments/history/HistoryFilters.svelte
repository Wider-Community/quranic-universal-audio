<script lang="ts">
    /**
     * HistoryFilters — edit-type / issue-category pills + sort toggles.
     *
     * Derivations live in the store; pills are declarative `<button>`s with
     * `class:active` bound to the store filter sets.
     *
     * Count semantics:
     *   - Op-type counts are faceted by the active category filter set.
     *   - Category counts are faceted by the active op-type filter set.
     *   - Chain-type "split_segment" count is total chains + raw ops.
     *
     * A section is hidden when it has fewer than two distinct options
     * (there's nothing to filter on). The "Clear Filters" button shows
     * only when at least one filter is active.
     */

    import { EDIT_OP_LABELS, ERROR_CAT_LABELS } from '../../../lib/utils/segments/constants';
    import {
        clearFilters,
        filterErrCats,
        filterOpTypes,
        flatItems,
        itemMatchesCatFilter,
        itemMatchesOpFilter,
        setSortMode,
        sortMode,
        splitChains,
        toggleFilter,
    } from '../../../lib/stores/segments/history';
    import { _deriveOpIssueDelta } from '../../../lib/utils/segments/classify';

    // Derived pill data ------------------------------------------------------

    // Op-type counts (faceted by active category filter).
    $: opCounts = (() => {
        const catActive = $filterErrCats.size > 0;
        const source = catActive
            ? $flatItems.filter((it) => itemMatchesCatFilter(it, $filterErrCats))
            : $flatItems;
        const counts: Record<string, number> = {};
        for (const item of source) {
            if (item.group.length === 0) continue;
            const op = item.group[0];
            if (!op) continue;
            counts[op.op_type] = (counts[op.op_type] || 0) + 1;
        }
        // Chain count adds into split_segment (preserves imperative impl).
        if ($splitChains && !catActive) {
            counts['split_segment'] = (counts['split_segment'] || 0) + $splitChains.size;
        }
        return counts;
    })();

    // Category counts (faceted by active op-type filter).
    $: catCounts = (() => {
        const opActive = $filterOpTypes.size > 0;
        const source = opActive
            ? $flatItems.filter((it) => itemMatchesOpFilter(it, $filterOpTypes))
            : $flatItems;
        const counts: Record<string, number> = {};
        for (const item of source) {
            if (item.group.length === 0) continue;
            const delta = _deriveOpIssueDelta(item.group);
            const touched = new Set<string>([
                ...delta.resolved,
                ...delta.introduced,
                ...item.group.map((op) => op.op_context_category).filter((c): c is string => !!c),
            ]);
            for (const cat of touched) counts[cat] = (counts[cat] || 0) + 1;
        }
        return counts;
    })();

    // Sort ordered entries for stable pill order.
    $: opEntries = Object.entries(opCounts).sort((a, b) => b[1] - a[1]);
    $: catEntries = Object.entries(catCounts).sort((a, b) => b[1] - a[1]);

    $: hasFilters = $filterOpTypes.size > 0 || $filterErrCats.size > 0;
    $: showOps = opEntries.length >= 2;
    $: showCats = catEntries.length >= 2;
    $: hasAny = showOps || showCats;
</script>

<div id="seg-history-filters" class="seg-history-filters" class:hidden-none={!hasAny}>
    {#if showOps}
        <div class="seg-history-filter-section">
            <span class="seg-history-filter-label">Edit type:</span>
            <div id="seg-history-filter-ops" class="seg-history-filter-pills">
                {#each opEntries as [opType, count]}
                    <button
                        class="seg-history-filter-pill"
                        class:active={$filterOpTypes.has(opType)}
                        data-filter-type="op"
                        data-filter-value={opType}
                        on:click={() => toggleFilter('op', opType)}
                    >
                        {EDIT_OP_LABELS[opType] || opType} <span class="pill-count">{count}</span>
                    </button>
                {/each}
            </div>
        </div>
    {/if}

    {#if showCats}
        <div class="seg-history-filter-section">
            <span class="seg-history-filter-label">Issue/flag type:</span>
            <div id="seg-history-filter-cats" class="seg-history-filter-pills">
                {#each catEntries as [cat, count]}
                    <button
                        class="seg-history-filter-pill"
                        class:active={$filterErrCats.has(cat)}
                        data-filter-type="cat"
                        data-filter-value={cat}
                        on:click={() => toggleFilter('cat', cat)}
                    >
                        {ERROR_CAT_LABELS[cat]} <span class="pill-count">{count}</span>
                    </button>
                {/each}
            </div>
        </div>
    {/if}

    <div class="seg-history-filter-section">
        <span class="seg-history-filter-label">Sort by:</span>
        <div class="seg-history-filter-pills">
            <button
                id="seg-history-sort-time"
                class="seg-history-filter-pill"
                class:active={$sortMode === 'time'}
                on:click={() => setSortMode('time')}
            >Edit time</button>
            <button
                id="seg-history-sort-quran"
                class="seg-history-filter-pill"
                class:active={$sortMode === 'quran'}
                on:click={() => setSortMode('quran')}
            >Quran order</button>
        </div>
    </div>

    <button
        id="seg-history-filter-clear"
        class="btn btn-sm btn-cancel"
        class:hidden-none={!hasFilters}
        on:click={() => clearFilters()}
    >Clear Filters</button>
</div>

<style>
    .hidden-none {
        display: none !important;
    }
</style>
