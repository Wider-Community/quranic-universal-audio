<script lang="ts">
    /**
     * SavePreview — reactive save-preview panel.
     *
     * Renders summary stats + batch cards via the same store-driven path as
     * HistoryPanel. Imports HistoryBatch + SplitChainRow directly and feeds
     * preview data via buildDisplayItems — no HistoryPanel middleman.
     *
     * Visibility: `$savePreviewVisible` (toggled by showSavePreview /
     *   hideSavePreview in lib/utils/segments/save-actions.ts).
     * Content: `$savePreviewData` — set by setSavePreviewData in
     *   showSavePreview; cleared by clearSavePreviewData in hideSavePreview.
     */

    import { onDestroy } from 'svelte';

    import AudioElement from '../../../../lib/components/AudioElement.svelte';
    import { localeStore, tr } from '../../../../lib/i18n/locale-store';
    import * as m from '../../../../lib/paraglide/messages';
    import {
        buildDisplayItems,
        chainedOpIds,
        type DisplayEntry,
        editChains,
        flattenBatchesToItems,
    } from '../../stores/history';
    import { waveformContainer } from '../../stores/playback';
    import { savePreviewData, savePreviewVisible } from '../../stores/save';
    import { createPreviewPlaybackContext } from '../../utils/playback/preview';
    import EditChainRow from '../history/EditChainRow.svelte';
    import HistoryBatch from '../history/HistoryBatch.svelte';

    // Derive display entries from the preview data --------------------------
    $: previewBatches = ($savePreviewData?.batches ?? []) as import('../../../../lib/types/view-models').HistoryBatch[];

    // Filter chained ops out of the flat list so they only render via
    // <SplitChainRow>. Without this, ops belonging to a split chain would
    // appear twice — once in the chain row, once as a duplicate op-card
    // (the latter carrying its own Discard button). The chainedOpIds set
    // is populated by `showSavePreview` (utils/save/actions.ts), which
    // rebuilds chains across history + pending batches.
    $: flatPreviewItems = flattenBatchesToItems(previewBatches, $chainedOpIds ?? new Set<string>());

    $: displayEntries = buildDisplayItems(
        flatPreviewItems,
        previewBatches,
        'time',
        $editChains,
        new Set<string>(),
        new Set<string>(),
    ) as DisplayEntry[];

    // Summary stat cards ----------------------------------------------------
    $: summaryCards = tr($localeStore, computeSummarycards());

    function computeSummarycards(): Array<{ value: number | string; label: string }> | null {
        const d = $savePreviewData;
        if (!d) return null;
        return [
            { value: d.summary.total_operations, label: m.segments_save_preview_stat_operations() },
            { value: d.summary.chapters_edited, label: m.segments_save_preview_stat_chapters() },
            { value: d.summary.verses_edited, label: m.segments_save_preview_stat_verses() },
        ];
    }

    $: warningChaptersText = $savePreviewData?.warningChapters
        ? tr($localeStore, m.segments_save_preview_warning_chapters({ count: $savePreviewData.warningChapters.length }))
        : '';

    // Key helper for {#each} keying -----------------------------------------
    function entryKey(di: DisplayEntry): string {
        if (di.type === 'chain') {
            const first = di.chain.ops[0];
            return `chain:${first?.op.op_id ?? 'x'}`;
        }
        return `op:${di.item.batchId ?? 'p'}:${di.item.batchIdx}:${di.item.groupIdx}:${di.item.type}`;
    }

    // Preview playback context — owns one hidden <audio> element and one
    // AudioRange instance. SegmentRow children with `readOnly + previewCtx`
    // route their play button through this. Disposed on panel unmount.
    const previewCtx = createPreviewPlaybackContext();
    let audio: AudioElement;
    $: if (audio && $savePreviewVisible) {
        previewCtx.attachAudioEl(audio.element());
    }
    onDestroy(() => previewCtx.dispose());
</script>

<div id="seg-save-preview" class="seg-history-view" hidden={!$savePreviewVisible} use:waveformContainer>
    <AudioElement bind:this={audio} preload="metadata" />

    <div id="seg-save-preview-stats" class="seg-history-stats">
        {#if $savePreviewData?.warningChapters && $savePreviewData.warningChapters.length > 0}
            <div class="seg-save-preview-warning">
                {warningChaptersText}
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
            <div>
                {#if entry.type === 'chain'}
                    <EditChainRow chain={entry.chain} {previewCtx} mode="preview" />
                {:else}
                    <HistoryBatch item={entry.item} {previewCtx} mode="preview" />
                {/if}
            </div>
        {/each}
    </div>
</div>
