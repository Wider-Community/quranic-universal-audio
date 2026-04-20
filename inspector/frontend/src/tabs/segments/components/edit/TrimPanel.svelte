<script lang="ts">
    /**
     * TrimPanel — Svelte-rendered inline chrome for trim-mode edit.
     *
     * Mounted by SegmentRow inside `.seg-left` when that row is the active
     * edit target (see SegmentRow `isEditingThisRow && $editMode === 'trim'`).
     * Renders Cancel / Preview / Apply buttons plus a reactive duration /
     * status readout driven by the `trimWindow` + `editStatusText` stores
     * that `edit-trim.ts` mirrors from the canvas drag handlers.
     *
     * The imperative parts — waveform draw, drag math, pointer cursor — stay
     * on the canvas (`edit-trim.ts::setupTrimDragHandles`). This component
     * replaces only the `document.createElement` chrome built by the old
     * `enterTrimMode`.
     */

    import type { Segment } from '../../../../lib/types/domain';
    import { editStatusText, trimWindow } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { exitEditMode } from '../../utils/edit/common';
    import { previewLooping } from '../../utils/playback/play-range';
    import { confirmTrim, previewTrimAudio } from '../../utils/edit/trim';

    export let seg: Segment;
    export let canvas: SegCanvas;

    $: durText = $trimWindow
        ? `${(($trimWindow.currentEnd - $trimWindow.currentStart) / 1000).toFixed(2)}s`
        : `${((seg.time_end - seg.time_start) / 1000).toFixed(2)}s`;
    $: previewGlyph = $previewLooping === 'trim' ? '\u25A0' : '\u25B6';
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        <button class="btn btn-sm seg-card-play-btn" title="Play / pause trim preview"
            on:click={() => previewTrimAudio(canvas)}>{previewGlyph}</button>
        <button class="btn btn-sm btn-confirm" on:click={() => confirmTrim(seg, canvas)}>Apply</button>
        <span class="seg-edit-duration">{durText}</span>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
