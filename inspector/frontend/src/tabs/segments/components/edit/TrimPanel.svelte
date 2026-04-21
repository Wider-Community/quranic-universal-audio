<script lang="ts">
    /**
     * TrimPanel — Svelte-rendered inline chrome for trim-mode edit.
     *
     * Mounted by SegmentRow inside `.seg-left` when that row is the active
     * edit target (see SegmentRow `isEditingThisRow && $editMode === 'trim'`).
     * Renders Cancel | start-stepper-pair | Preview | end-stepper-pair | Apply
     * plus the status readout. The duration moved out of this panel — it now
     * lives on the row's TimeRange (`A.MMM - B.MMM | dur`) so it tracks the
     * typed-edit display in one place.
     *
     * Steppers nudge the corresponding cursor by `EDIT_NUDGE_MS` (default
     * 50 ms) via `nudgeTrimBoundary`, the same code path drag and typed
     * commits use — so the trim handles, the row time-display, and the
     * panel state stay in lock-step. Buttons disable when the next nudge
     * would no-op against the trim window or the opposing handle's
     * EDIT_MIN_DURATION_MS gap.
     *
     * The imperative parts — waveform draw, drag math, pointer cursor — stay
     * on the canvas (`edit-trim.ts::setupTrimDragHandles`).
     */

    import type { Segment } from '../../../../lib/types/domain';
    import { editStatusText, trimWindow } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { exitEditMode } from '../../utils/edit/common';
    import { previewLooping } from '../../utils/playback/play-range';
    import { confirmTrim, nudgeTrimBoundary, previewTrimAudio } from '../../utils/edit/trim';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';

    export let seg: Segment;
    export let canvas: SegCanvas;

    $: previewGlyph = $previewLooping === 'trim' ? '\u25A0' : '\u25B6';

    // Stepper-disable gates. A stepper disables when the next press would be
    // a no-op. Two cases:
    //   1. Standard: cursor is on-view, but `actual ± step` would be clamped
    //      back to actual (already at windowStart/End or pinned against
    //      opposing handle + EDIT_MIN_DURATION_MS).
    //   2. Off-view "away" press: cursor is visually clamped at one canvas
    //      edge (start always strict-clips LEFT, end always RIGHT). Pressing
    //      in the direction further off-screen would step the actual time
    //      with no visible feedback — disable that direction.
    //
    // The "into-view" press from a clamped cursor is handled by
    // `nudgeTrimBoundary`'s snap-to-visual-border path: e.g. left-clamped
    // start + `>` lands at `viewStart + EDIT_NUDGE_MS` regardless of how
    // far off-view the actual time was, so the cursor pops back into view.
    $: tw = $trimWindow;
    $: startOffLeft = !!tw && tw.currentStart < tw.viewStart;
    $: endOffRight  = !!tw && tw.currentEnd   > tw.viewEnd;
    $: startBackDisabled = !tw || startOffLeft || tw.currentStart <= tw.windowStart;
    $: startFwdDisabled  = !tw || tw.currentStart >= tw.currentEnd - EDIT_MIN_DURATION_MS;
    $: endBackDisabled   = !tw || tw.currentEnd <= tw.currentStart + EDIT_MIN_DURATION_MS;
    $: endFwdDisabled    = !tw || endOffRight || tw.currentEnd >= tw.windowEnd;

    function nudgeStartBack(): void { nudgeTrimBoundary('start', -EDIT_NUDGE_MS); }
    function nudgeStartFwd():  void { nudgeTrimBoundary('start',  EDIT_NUDGE_MS); }
    function nudgeEndBack():   void { nudgeTrimBoundary('end',   -EDIT_NUDGE_MS); }
    function nudgeEndFwd():    void { nudgeTrimBoundary('end',    EDIT_NUDGE_MS); }
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        <button class="btn btn-sm seg-trim-step seg-trim-step-start"
            title="Move start back {EDIT_NUDGE_MS} ms"
            disabled={startBackDisabled}
            on:click={nudgeStartBack}>&lt;</button>
        <button class="btn btn-sm seg-trim-step seg-trim-step-start"
            title="Move start forward {EDIT_NUDGE_MS} ms"
            disabled={startFwdDisabled}
            on:click={nudgeStartFwd}>&gt;</button>
        <button class="btn btn-sm seg-card-play-btn" title="Play / pause trim preview"
            on:click={() => previewTrimAudio(canvas)}>{previewGlyph}</button>
        <button class="btn btn-sm seg-trim-step seg-trim-step-end"
            title="Move end back {EDIT_NUDGE_MS} ms"
            disabled={endBackDisabled}
            on:click={nudgeEndBack}>&lt;</button>
        <button class="btn btn-sm seg-trim-step seg-trim-step-end"
            title="Move end forward {EDIT_NUDGE_MS} ms"
            disabled={endFwdDisabled}
            on:click={nudgeEndFwd}>&gt;</button>
        <button class="btn btn-sm btn-confirm" on:click={() => confirmTrim(seg, canvas)}>Apply</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
