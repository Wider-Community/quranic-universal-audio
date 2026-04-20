<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Mounted by SegmentRow inside `.seg-left` when that row is the active
     * edit target (see SegmentRow `isEditingThisRow && $editMode === 'split'`).
     * Renders Cancel / Play Left / Play Right / Split buttons plus a
     * reactive L/R duration readout driven by the `splitState` store that
     * `edit-split.ts` mirrors from the canvas drag handler.
     *
     * The imperative parts — waveform draw, drag math, pointer cursor — stay
     * on the canvas (`edit-split.ts::setupSplitDragHandle`). This component
     * replaces only the `document.createElement` chrome built by the old
     * `enterSplitMode`.
     */

    import { get } from 'svelte/store';

    import type { Segment } from '../../../../lib/types/domain';
    import { editingMountId, splitState, editStatusText } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { exitEditMode } from '../../utils/edit/common';
    import { confirmSplit, previewSplitAudio } from '../../utils/edit/split';

    export let seg: Segment;
    export let canvas: SegCanvas;

    function onConfirm(): void {
        // Thread the initiating row's mountId through to confirmSplit so the
        // chained first-half ref-edit stays pinned to the accordion row that
        // started the split (not the main-list twin). Reads editingMountId
        // live at click time rather than caching in a prop — covers both
        // accordion (mountId = row's _mountId) and main-list (same) paths.
        const mountId = get(editingMountId);
        confirmSplit(seg, canvas, mountId);
    }

    $: infoText = $splitState
        ? `L ${(($splitState.currentSplit - $splitState.seg.time_start) / 1000).toFixed(2)}s | R ${(($splitState.seg.time_end - $splitState.currentSplit) / 1000).toFixed(2)}s`
        : '';
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('left', canvas)}>Play Left</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('right', canvas)}>Play Right</button>
        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-info">{infoText}</span>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
