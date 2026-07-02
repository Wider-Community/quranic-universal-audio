<script lang="ts">
    /**
     * TrimPanel — Svelte-rendered inline chrome for trim-mode edit.
     *
     * Layout: ``Cancel    <  >    [↻]    <  >    Apply``.
     * The two `< >` pairs are bare caret buttons separated by spacing,
     * each pair sitting above a 2px coloured underline that mirrors the
     * canvas trim-handle (green for start, red for end). Spatial position
     * carries the meaning — start nudgers on the left, end on the right —
     * so the panel doesn't need text labels or bordered groups for what's
     * a seven-element toolbar.
     *
     * Between the two stepper pairs sits a playhead-pink replay button.
     * Clicking it cold-starts a fresh loop from the live `currentStart`
     * → `currentEnd`, regardless of the current pause / play state. The
     * footer ▶ remains the pause/resume; this button is the only path
     * to restart-from-start.
     *
     * Preview play/pause is owned entirely by the footer ▶ and the Space
     * shortcut (centralised through `onSegPlayClick`). This panel never
     * spawns its own pause/resume button.
     */

    import Icon from '../../../../lib/icons/Icon.svelte';
    import { localeStore, tr } from '../../../../lib/i18n/locale-store';
    import * as m from '../../../../lib/paraglide/messages';
    import type { Segment } from '../../../../lib/types/view-models';
    import { activeTrimBoundary, editStatusText, trimWindow } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import { confirmTrim, nudgeTrimBoundary, previewTrimAudio } from '../../utils/edit/trim';

    export let seg: Segment;
    export let canvas: SegCanvas;

    // Stepper-disable gates. Two failure modes:
    //   1. Standard: cursor is on-view but `actual ± step` would clamp
    //      against windowStart/End or the opposing handle's EDIT_MIN_DURATION_MS.
    //   2. Off-view "away" press: cursor visually clipped at one canvas
    //      edge (start always strict-clips LEFT, end RIGHT). Pressing
    //      further off-screen would step `actual` with no visible feedback
    //      so we disable that direction.
    $: tw = $trimWindow;
    $: startOffLeft = !!tw && tw.currentStart < tw.viewStart;
    $: endOffRight  = !!tw && tw.currentEnd   > tw.viewEnd;
    $: startBackDisabled = !tw || startOffLeft || tw.currentStart <= tw.windowStart;
    $: startFwdDisabled  = !tw || tw.currentStart >= tw.currentEnd - EDIT_MIN_DURATION_MS;
    $: endBackDisabled   = !tw || tw.currentEnd <= tw.currentStart + EDIT_MIN_DURATION_MS;
    $: endFwdDisabled    = !tw || endOffRight || tw.currentEnd >= tw.windowEnd;
    // Replay cold-starts a loop from the LIVE currentStart/currentEnd via
    // `previewTrimAudio`. Disabled when the window collapses below the
    // same min-duration the nudgers already use.
    $: replayDisabled = !tw || (tw.currentEnd - tw.currentStart) < EDIT_MIN_DURATION_MS;

    function nudgeStartBack(): void { nudgeTrimBoundary('start', -EDIT_NUDGE_MS); }
    function nudgeStartFwd():  void { nudgeTrimBoundary('start',  EDIT_NUDGE_MS); }
    function nudgeEndBack():   void { nudgeTrimBoundary('end',   -EDIT_NUDGE_MS); }
    function nudgeEndFwd():    void { nudgeTrimBoundary('end',    EDIT_NUDGE_MS); }

    $: startGroupAriaLabel = tr($localeStore, m.segments_trim_start_group_aria_label());
    $: startBackTitle = tr($localeStore, m.segments_trim_start_back_title({ ms: EDIT_NUDGE_MS }));
    $: startFwdTitle = tr($localeStore, m.segments_trim_start_fwd_title({ ms: EDIT_NUDGE_MS }));
    $: replayTitle = tr($localeStore, m.segments_trim_replay_title());
    $: replayAriaLabel = tr($localeStore, m.segments_trim_replay_aria_label());
    $: endGroupAriaLabel = tr($localeStore, m.segments_trim_end_group_aria_label());
    $: endBackTitle = tr($localeStore, m.segments_trim_end_back_title({ ms: EDIT_NUDGE_MS }));
    $: endFwdTitle = tr($localeStore, m.segments_trim_end_fwd_title({ ms: EDIT_NUDGE_MS }));
    $: applyLabel = tr($localeStore, m.segments_trim_apply_button());
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>

        <div class="seg-nudge-pair seg-nudge-start" class:kb-active={$activeTrimBoundary === 'start'} role="group" aria-label={startGroupAriaLabel}>
            <button class="seg-nudge"
                title={startBackTitle}
                disabled={startBackDisabled}
                on:click={nudgeStartBack}>&lsaquo;</button>
            <button class="seg-nudge"
                title={startFwdTitle}
                disabled={startFwdDisabled}
                on:click={nudgeStartFwd}>&rsaquo;</button>
        </div>

        <button class="seg-replay"
            title={replayTitle}
            aria-label={replayAriaLabel}
            disabled={replayDisabled}
            on:click={() => previewTrimAudio(canvas, { mode: 'cold' })}
        >
            <Icon name="replay" size={14} />
        </button>

        <div class="seg-nudge-pair seg-nudge-end" class:kb-active={$activeTrimBoundary === 'end'} role="group" aria-label={endGroupAriaLabel}>
            <button class="seg-nudge"
                title={endBackTitle}
                disabled={endBackDisabled}
                on:click={nudgeEndBack}>&lsaquo;</button>
            <button class="seg-nudge"
                title={endFwdTitle}
                disabled={endFwdDisabled}
                on:click={nudgeEndFwd}>&rsaquo;</button>
        </div>

        <button class="btn btn-sm btn-confirm" on:click={() => confirmTrim(seg, canvas)}>{applyLabel}</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>

<style>
    /* Ring the stepper pair the keyboard ←/→ + Tab currently drives, so the
       active handle is visible when trimming without the mouse. */
    .seg-nudge-pair.kb-active {
        outline: 1.5px solid var(--accent);
        outline-offset: 2px;
        border-radius: var(--r-1);
    }
</style>
