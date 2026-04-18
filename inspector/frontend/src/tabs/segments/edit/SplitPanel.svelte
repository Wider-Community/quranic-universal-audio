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

    import type { Segment } from '../../../lib/types/domain';
    import { splitState, trimStatusText } from '../../../lib/stores/segments/edit';
    import type { SegCanvas } from '../../../lib/types/segments-waveform';
    import { exitEditMode } from '../../../lib/utils/segments/edit-common';
    import { confirmSplit, previewSplitAudio } from '../../../lib/utils/segments/edit-split';

    export let seg: Segment;
    export let canvas: SegCanvas;

    $: infoText = $splitState
        ? `L ${(($splitState.currentSplit - $splitState.seg.time_start) / 1000).toFixed(2)}s | R ${(($splitState.seg.time_end - $splitState.currentSplit) / 1000).toFixed(2)}s`
        : '';
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('left', canvas)}>Play Left</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('right', canvas)}>Play Right</button>
        <button class="btn btn-sm btn-confirm" on:click={() => confirmSplit(seg, canvas)}>Split</button>
        <span class="seg-edit-info">{infoText}</span>
        <span class="seg-edit-status">{$trimStatusText}</span>
    </div>
</div>
