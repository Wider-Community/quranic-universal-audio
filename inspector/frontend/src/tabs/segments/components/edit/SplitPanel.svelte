<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Two layouts driven by `splitState.currentSplits.length`:
     *
     * - N=1 (binary split, today's default) → ``Cancel | Play Left | < | >
     *   | Play Right | Split``. Steppers nudge via `nudgeSplitBoundary`.
     * - N≥2 (multi-cursor, repetition auto-split) → ``Cancel | [1] [2] …
     *   [N+1] | Split``. Each ``[i]`` loops region i (0-indexed) via
     *   `previewSplitRegion`. No steppers — there's no obvious "the
     *   cursor" to step in multi mode; users drag the cursor lines
     *   directly. Click-to-seek on the canvas is also disabled in this
     *   mode (see split.ts `onMouseup`).
     */

    import { get } from 'svelte/store';

    import type { Segment } from '../../../../lib/types/domain';
    import { editingMountId, editStatusText,splitState } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import {
        confirmSplit,
        nudgeSplitBoundary,
        previewSplitAudio,
        previewSplitRegion,
    } from '../../utils/edit/split';

    export let seg: Segment;
    export let canvas: SegCanvas;

    function onConfirm(): void {
        const mountId = get(editingMountId);
        confirmSplit(seg, canvas, mountId);
    }

    $: ss = $splitState;
    $: cursorCount = ss?.currentSplits.length ?? 0;
    $: isBinary = cursorCount === 1;
    $: regionCount = cursorCount + 1;
    $: regions = Array.from({ length: regionCount }, (_, i) => i);

    // Stepper-disable gates apply in binary mode only.
    $: firstSplit = ss?.currentSplits[0];
    $: splitBackDisabled = !isBinary || !ss || firstSplit === undefined
        || firstSplit <= ss.seg.time_start + EDIT_MIN_DURATION_MS;
    $: splitFwdDisabled = !isBinary || !ss || firstSplit === undefined
        || firstSplit >= ss.seg.time_end - EDIT_MIN_DURATION_MS;

    function nudgeSplitBack(): void { nudgeSplitBoundary(-EDIT_NUDGE_MS); }
    function nudgeSplitFwd():  void { nudgeSplitBoundary( EDIT_NUDGE_MS); }
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        {#if isBinary}
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
        {:else}
            {#each regions as i}
                <button
                    class="btn btn-sm btn-preview seg-split-region"
                    title="Play region {i + 1} on loop"
                    on:click={() => previewSplitRegion(i, canvas)}
                >{i + 1}</button>
            {/each}
        {/if}
        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>

<style>
    .seg-split-region {
        min-width: 1.6em;
        padding: 0 0.4em;
    }
</style>
