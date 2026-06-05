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

    import {
        buildDisplayItems,
        chainHasWaslAnnotation,
        editChains,
        filterErrCats,
        filterHasWasl,
        filterOpTypes,
        flatItems,
        historyData,
        itemHasWaslAnnotation,
        setSortMode,
        sortMode,
        toggleFilter,
        toggleWaslFilter,
    } from '../../stores/history';
    import { EDIT_OP_LABELS, ERROR_CAT_LABELS } from '../../utils/constants';
    import { deriveOpIssueDelta } from '../../utils/validation/classified-issues';

    const HISTORY_NEUTRAL_CATEGORIES = new Set(['basmala_amin', 'muqattaat']);
    const historyCategory = (cat: string | null | undefined): string | null =>
        cat && !HISTORY_NEUTRAL_CATEGORIES.has(cat) ? cat : null;

    // Derived pill data ------------------------------------------------------

    $: unfilteredEntries = (() => {
        if (!$historyData || !$historyData.batches) return [];
        return buildDisplayItems(
            $flatItems,
            $historyData.batches,
            'time',
            $editChains,
            new Set(),
            new Set()
        );
    })();

    // Base counts (for stable ordering and showing 0-count pills)
    $: baseOpCounts = (() => {
        const counts: Record<string, number> = {};
        for (const entry of unfilteredEntries) {
            if (entry.type === 'chain') {
                for (const { op } of entry.chain.ops) counts[op.op_type] = (counts[op.op_type] || 0) + 1;
            } else {
                for (const op of entry.item.group) counts[op.op_type] = (counts[op.op_type] || 0) + 1;
            }
        }
        return counts;
    })();

    $: baseCatCounts = (() => {
        const counts: Record<string, number> = {};
        for (const entry of unfilteredEntries) {
            const ops = entry.type === 'chain' ? entry.chain.ops.map(c => c.op) : entry.item.group;
            if (ops.length === 0) continue;
            const delta = deriveOpIssueDelta(ops);
            const touched = new Set<string>([
                ...delta.involved,
                ...ops.map((op) => historyCategory(op.op_context_category)).filter((c): c is string => !!c),
            ]);
            for (const cat of touched) counts[cat] = (counts[cat] || 0) + 1;
        }
        return counts;
    })();

    $: sourceForOps = (() => {
        if (!$historyData || !$historyData.batches) return [];
        return buildDisplayItems(
            $flatItems,
            $historyData.batches,
            'time',
            $editChains,
            new Set(), // No op-type filter
            $filterErrCats // Respect active category filter
        );
    })();

    // Op-type counts (faceted by active category filter).
    $: opCounts = (() => {
        const counts: Record<string, number> = {};
        for (const key of Object.keys(baseOpCounts)) counts[key] = 0;
        for (const entry of sourceForOps) {
            if (entry.type === 'chain') {
                for (const { op } of entry.chain.ops) counts[op.op_type] = (counts[op.op_type] || 0) + 1;
            } else {
                for (const op of entry.item.group) counts[op.op_type] = (counts[op.op_type] || 0) + 1;
            }
        }
        return counts;
    })();

    $: sourceForCats = (() => {
        if (!$historyData || !$historyData.batches) return [];
        return buildDisplayItems(
            $flatItems,
            $historyData.batches,
            'time',
            $editChains,
            $filterOpTypes, // Respect active op-type filter
            new Set() // No category filter
        );
    })();

    // Category counts (faceted by active op-type filter).
    $: catCounts = (() => {
        const counts: Record<string, number> = {};
        for (const key of Object.keys(baseCatCounts)) counts[key] = 0;
        for (const entry of sourceForCats) {
            const ops = entry.type === 'chain' ? entry.chain.ops.map(c => c.op) : entry.item.group;
            if (ops.length === 0) continue;
            const delta = deriveOpIssueDelta(ops);
            const touched = new Set<string>([
                ...delta.involved,
                ...ops.map((op) => historyCategory(op.op_context_category)).filter((c): c is string => !!c),
            ]);
            for (const cat of touched) counts[cat] = (counts[cat] || 0) + 1;
        }
        return counts;
    })();

    // Sort ordered entries for stable pill order using base counts.
    $: opEntries = Object.entries(opCounts).sort((a, b) => (baseOpCounts[b[0]] || 0) - (baseOpCounts[a[0]] || 0));
    $: catEntries = Object.entries(catCounts).sort((a, b) => (baseCatCounts[b[0]] || 0) - (baseCatCounts[a[0]] || 0));

    // Wasl-annotation pill count: any entry in the unfiltered list whose ops
    // carry an is_wasl annotation in any targets_after snapshot. Counted off
    // the same `unfilteredEntries` base so the count is stable regardless of
    // other active filters.
    $: waslCount = (() => {
        let n = 0;
        for (const entry of unfilteredEntries) {
            if (entry.type === 'chain') {
                if (chainHasWaslAnnotation(entry.chain)) n++;
            } else if (itemHasWaslAnnotation(entry.item)) {
                n++;
            }
        }
        return n;
    })();

    $: showOps = Object.keys(baseOpCounts).length >= 2;
    $: showCats = Object.keys(baseCatCounts).length >= 2;
    $: showWasl = waslCount > 0;
    $: hasAny = showOps || showCats || showWasl;
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
                        class:empty={count === 0}
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
                        class:empty={count === 0}
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

    {#if showWasl}
        <div class="seg-history-filter-section">
            <span class="seg-history-filter-label">Annotation:</span>
            <div id="seg-history-filter-wasl" class="seg-history-filter-pills">
                <button
                    class="seg-history-filter-pill"
                    class:active={$filterHasWasl}
                    data-filter-type="wasl"
                    data-filter-value="wasl"
                    title="Show only edits that mark a boundary as WASL"
                    on:click={() => toggleWaslFilter()}
                >
                    Wasl <span class="pill-count">{waslCount}</span>
                </button>
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

</div>

<style>
    .hidden-none {
        display: none !important;
    }
</style>
