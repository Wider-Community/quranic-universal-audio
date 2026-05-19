<script lang="ts">
    /**
     * TrimPanel — Svelte-rendered inline chrome for trim-mode edit.
     *
     * Mounted by SegmentRow inside `.seg-left` when that row is the active
     * edit target. Layout: ``Cancel | [< START >] | [< END >] | Apply``.
     * Each `< >` pair is wrapped in a `.seg-stepper` segmented group with
     * a green (start) or red (end) theme — the carets share a border so
     * the pair reads as ONE control rather than two loose chips. A tiny
     * `START` / `END` micro-label sits between the carets and replaces
     * the old floating divider line.
     *
     * Trim PREVIEW play/pause is driven entirely by the footer ▶ (and the
     * Space shortcut), centralised through `onSegPlayClick`. This panel
     * never spawns its own play button.
     *
     * Steppers nudge by `EDIT_NUDGE_MS` via `nudgeTrimBoundary`, the same
     * code path drag + typed commits use — so the trim handles, the row
     * time-display, and the panel state stay in lock-step. Buttons
     * disable when the next press would no-op against the trim window or
     * the opposing handle's EDIT_MIN_DURATION_MS gap.
     */

    import type { Segment } from '../../../../lib/types/domain';
    import { editStatusText, trimWindow } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import { confirmTrim, nudgeTrimBoundary } from '../../utils/edit/trim';

    export let seg: Segment;
    export let canvas: SegCanvas;

    // Stepper-disable gates. A stepper disables when the next press would be
    // a no-op. Two cases:
    //   1. Standard: cursor is on-view, but `actual ± step` would be clamped
    //      back to actual (already at windowStart/End or pinned against
    //      opposing handle + EDIT_MIN_DURATION_MS).
    //   2. Off-view "away" press: cursor is visually clamped at one canvas
    //      edge (start always strict-clips LEFT, end always RIGHT). Pressing
    //      in the direction further off-screen would step the actual time
    //      with no visible feedback — disable that direction.
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

        <div class="seg-stepper seg-stepper-start" role="group" aria-label="Trim start">
            <button class="seg-step"
                title="Move start back {EDIT_NUDGE_MS} ms"
                disabled={startBackDisabled}
                on:click={nudgeStartBack}>&lt;</button>
            <span class="seg-stepper-label" aria-hidden="true">START</span>
            <button class="seg-step"
                title="Move start forward {EDIT_NUDGE_MS} ms"
                disabled={startFwdDisabled}
                on:click={nudgeStartFwd}>&gt;</button>
        </div>

        <div class="seg-stepper seg-stepper-end" role="group" aria-label="Trim end">
            <button class="seg-step"
                title="Move end back {EDIT_NUDGE_MS} ms"
                disabled={endBackDisabled}
                on:click={nudgeEndBack}>&lt;</button>
            <span class="seg-stepper-label" aria-hidden="true">END</span>
            <button class="seg-step"
                title="Move end forward {EDIT_NUDGE_MS} ms"
                disabled={endFwdDisabled}
                on:click={nudgeEndFwd}>&gt;</button>
        </div>

        <button class="btn btn-sm btn-confirm" on:click={() => confirmTrim(seg, canvas)}>Apply</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
