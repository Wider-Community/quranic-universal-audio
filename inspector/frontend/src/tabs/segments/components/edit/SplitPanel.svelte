<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Mounted by SegmentRow inside `.seg-left` when that row is the active
     * edit target (see SegmentRow `isEditingThisRow && $editMode === 'split'`).
     * Renders Cancel | Play Left | step-pair | Play Right | Split plus the
     * L/R duration readout driven by the `splitState` store that
     * `edit-split.ts` mirrors from the canvas drag handler.
     *
     * Steppers nudge the split cursor by `EDIT_NUDGE_MS` (default 50 ms) via
     * `nudgeSplitBoundary`, the same code path a drag uses — so the canvas
     * cursor, the L/R readout, and the panel state stay in lock-step. Buttons
     * disable when the next nudge would be clamped against the seg edge +
     * EDIT_MIN_DURATION_MS gap.
     *
     * The imperative parts — waveform draw, drag math, pointer cursor — stay
     * on the canvas (`edit-split.ts::setupSplitDragHandle`).
     */

    import { get } from 'svelte/store';

    import type { Segment } from '../../../../lib/types/domain';
    import { editingMountId, splitState, editStatusText } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import { confirmSplit, nudgeSplitBoundary, previewSplitAudio } from '../../utils/edit/split';

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

    // Stepper-disable gates. Disable when the next press would clamp to the
    // same position (`EDIT_MIN_DURATION_MS` away from the seg boundary). The
    // L/R readout that used to live here was dropped — same treatment the
    // trim panel got for its duration text: the row-level time display now
    // owns that info, this panel stays compact.
    $: ss = $splitState;
    $: splitBackDisabled = !ss || ss.currentSplit <= ss.seg.time_start + EDIT_MIN_DURATION_MS;
    $: splitFwdDisabled  = !ss || ss.currentSplit >= ss.seg.time_end   - EDIT_MIN_DURATION_MS;

    function nudgeSplitBack(): void { nudgeSplitBoundary(-EDIT_NUDGE_MS); }
    function nudgeSplitFwd():  void { nudgeSplitBoundary( EDIT_NUDGE_MS); }
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('left', canvas)}>Play Left</button>
        <button class="btn btn-sm seg-split-step"
            title="Move split back {EDIT_NUDGE_MS} ms"
            disabled={splitBackDisabled}
            on:click={nudgeSplitBack}>&lt;</button>
        <button class="btn btn-sm seg-split-step"
            title="Move split forward {EDIT_NUDGE_MS} ms"
            disabled={splitFwdDisabled}
            on:click={nudgeSplitFwd}>&gt;</button>
        <button class="btn btn-sm btn-preview" on:click={() => previewSplitAudio('right', canvas)}>Play Right</button>
        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
