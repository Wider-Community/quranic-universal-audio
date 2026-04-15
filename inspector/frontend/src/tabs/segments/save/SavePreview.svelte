<script lang="ts">
    /**
     * SavePreview — reactive save-preview panel.
     *
     * Wave 11a: migrated from shell-delegation (Wave 9) to full reactive
     * rendering. The panel now renders summary stats + batch cards via
     * the same store-driven path as HistoryPanel (Opus F bifurcation
     * resolved). `segments/save.ts` no longer writes innerHTML to
     * #seg-save-preview-stats / #seg-save-preview-batches.
     *
     * Approach (c) Hybrid per Wave 11a advisor:
     *   SavePreview imports HistoryBatch + SplitChainRow directly and
     *   feeds preview data via buildDisplayItems — no HistoryPanel middleman.
     *
     * Visibility: $savePreviewVisible (unchanged — save.ts calls showPreview/
     *   hidePreview alongside its imperative show/hide logic until dom refs
     *   are swept in P2).
     * Content: $savePreviewData (new in Wave 11a — set by setSavePreviewData
     *   in showSavePreview; cleared by clearSavePreviewData in hideSavePreview).
     */

    import HistoryBatch from '../history/HistoryBatch.svelte';
    import SplitChainRow from '../history/SplitChainRow.svelte';
    import {
        buildDisplayItems,
        flattenBatchesToItems,
        splitChains,
        type DisplayEntry,
    } from '../../../lib/stores/segments/history';
    import { savePreviewData, savePreviewVisible } from '../../../lib/stores/segments/save';

    // Derive display entries from the preview data --------------------------
    $: previewBatches = ($savePreviewData?.batches ?? []) as import('../../../types/domain').HistoryBatch[];

    $: flatPreviewItems = flattenBatchesToItems(previewBatches, new Set<string>());

    $: displayEntries = buildDisplayItems(
        flatPreviewItems,
        previewBatches,
        'time',
        $splitChains,
        new Set<string>(),
        new Set<string>(),
    ) as DisplayEntry[];

    // Summary stat cards ----------------------------------------------------
    $: summaryCards = computeSummarycards();

    function computeSummarycards(): Array<{ value: number | string; label: string }> | null {
        const d = $savePreviewData;
        if (!d) return null;
        return [
            { value: d.summary.total_operations, label: 'Operations' },
            { value: d.summary.chapters_edited, label: 'Chapters' },
            { value: d.summary.verses_edited, label: 'Verses' },
        ];
    }

    // Key helper for {#each} keying -----------------------------------------
    function entryKey(di: DisplayEntry): string {
        if (di.type === 'chain') {
            const first = di.chain.ops[0];
            return `chain:${first?.op.op_id ?? 'x'}`;
        }
        return `op:${di.item.batchId ?? 'p'}:${di.item.batchIdx}:${di.item.groupIdx}:${di.item.type}`;
    }
</script>

<div id="seg-save-preview" class="seg-history-view" hidden={!$savePreviewVisible}>
    <div class="seg-history-toolbar seg-save-preview-toolbar">
        <button id="seg-save-preview-cancel" class="btn">&larr; Cancel</button>
        <span class="seg-history-title">Review Changes</span>
        <button id="seg-save-preview-confirm" class="btn btn-save">Confirm Save</button>
    </div>

    <div id="seg-save-preview-stats" class="seg-history-stats">
        {#if $savePreviewData?.warningChapters && $savePreviewData.warningChapters.length > 0}
            <div class="seg-save-preview-warning">
                {$savePreviewData.warningChapters.length} chapter(s) marked as changed
                but have no detailed operations recorded.
            </div>
        {/if}
        {#if summaryCards}
            <div class="seg-history-stat-cards">
                {#each summaryCards as card}
                    <div class="seg-history-stat-card">
                        <div class="seg-history-stat-value">{card.value}</div>
                        <div class="seg-history-stat-label">{card.label}</div>
                    </div>
                {/each}
            </div>
        {/if}
    </div>

    <div id="seg-save-preview-batches" class="seg-history-batches">
        {#each displayEntries as entry (entryKey(entry))}
            {#if entry.type === 'chain'}
                <SplitChainRow chain={entry.chain} />
            {:else}
                <HistoryBatch item={entry.item} />
            {/if}
        {/each}
    </div>
</div>
