<script lang="ts">
    /**
     * HistoryPanel — top-level edit-history view.
     *
     * Responsibilities:
     *   - Visibility gate via `$historyVisible` → `hidden` attribute on the
     *     outer `#seg-history-view` div. The ID is preserved so the
     *     waveform IntersectionObserver (see waveform-utils.ts) can scope
     *     canvas redraws to this container.
     *   - Summary stat cards from `$historyData.summary` (with verses count
     *     patched from `countVersesFromBatches`) OR filtered summary when
     *     any filter is active.
     *   - `<HistoryFilters>` section.
     *   - Batches list: applies filter + sort via `buildDisplayItems`
     *     → `{#each}` dispatch to `<SplitChainRow>` / `<HistoryBatch>`.
     *
     * What lives outside this component:
     *   - `#seg-history-btn` (in SegmentsTab toolbar) — opens the view.
     *   - Normal-content hide when `$historyVisible` is true — SegmentsTab
     *     gates the normal-content block with `{#if !$historyVisible && ...}`.
     */

    import HistoryBatch from './HistoryBatch.svelte';
    import HistoryFilters from './HistoryFilters.svelte';
    import SplitChainRow from './SplitChainRow.svelte';
    import { hideHistoryView } from '../../../lib/utils/segments/history-actions';
    import {
        buildDisplayItems,
        computeFilteredItemSummary,
        countVersesFromBatches,
        filterErrCats,
        filterOpTypes,
        flatItems,
        historyData,
        historyVisible,
        itemMatchesCatFilter,
        itemMatchesOpFilter,
        sortMode,
        splitChains,
        type DisplayEntry,
        type FilteredItemSummary,
    } from '../../../lib/stores/segments/history';

    // Filtered flat items -----------------------------------------------------
    $: hasFilters = $filterOpTypes.size > 0 || $filterErrCats.size > 0;
    $: filteredItems = hasFilters
        ? $flatItems.filter((it) => {
              if ($filterOpTypes.size > 0 && !itemMatchesOpFilter(it, $filterOpTypes)) return false;
              if ($filterErrCats.size > 0 && !itemMatchesCatFilter(it, $filterErrCats)) return false;
              return true;
          })
        : $flatItems;

    // Summary derivation ------------------------------------------------------
    interface SummaryCard { value: number | string; label: string }
    $: summary = computeSummary();

    function computeSummary(): SummaryCard[] | null {
        if (!$historyData || !$historyData.batches || $historyData.batches.length === 0) {
            return null;
        }
        if (hasFilters) {
            const fs: FilteredItemSummary = computeFilteredItemSummary(filteredItems);
            return [
                { value: fs.total_operations, label: 'Operations' },
                { value: fs.chapters_edited, label: 'Chapters' },
                { value: fs.verses_edited, label: 'Verses' },
            ];
        }
        // Unfiltered summary comes from server-computed data.summary, with
        // verses patched via countVersesFromBatches (preserved verbatim).
        const s = $historyData.summary;
        const versesEdited = countVersesFromBatches($historyData.batches);
        return [
            { value: s?.total_operations ?? 0, label: 'Operations' },
            { value: s?.chapters_edited ?? 0, label: 'Chapters' },
            { value: versesEdited, label: 'Verses' },
        ];
    }

    // Batches display ---------------------------------------------------------
    $: displayEntries = displayEntriesFor(filteredItems);

    function displayEntriesFor(items: typeof filteredItems): DisplayEntry[] {
        if (!$historyData || !$historyData.batches) return [];
        return buildDisplayItems(
            items,
            $historyData.batches,
            $sortMode,
            $splitChains,
            $filterOpTypes,
            $filterErrCats,
        );
    }

    function entryKey(di: DisplayEntry): string {
        if (di.type === 'chain') {
            const first = di.chain.ops[0];
            return `chain:${first?.op.op_id ?? 'x'}`;
        }
        return `op:${di.item.batchId ?? 'p'}:${di.item.batchIdx}:${di.item.groupIdx}:${di.item.type}`;
    }
</script>

<div
    id="seg-history-view"
    class="seg-history-view"
    hidden={!$historyVisible}
>
    <div class="seg-history-toolbar">
        <button id="seg-history-back-btn" class="btn" on:click={() => hideHistoryView()}>
            &larr; Back
        </button>
        <span class="seg-history-title">Edit History</span>
    </div>

    <div id="seg-history-stats" class="seg-history-stats">
        {#if summary}
            <div class="seg-history-stat-cards">
                {#each summary as card}
                    <div class="seg-history-stat-card">
                        <div class="seg-history-stat-value">{card.value}</div>
                        <div class="seg-history-stat-label">{card.label}</div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <HistoryFilters />

    <div id="seg-history-batches" class="seg-history-batches">
        {#if filteredItems.length === 0 && hasFilters}
            <div class="seg-history-empty">No edits match the active filters.</div>
        {:else}
            {#each displayEntries as entry (entryKey(entry))}
                {#if entry.type === 'chain'}
                    <SplitChainRow chain={entry.chain} />
                {:else}
                    <HistoryBatch item={entry.item} />
                {/if}
            {/each}
        {/if}
    </div>
</div>
