<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Two layouts driven by `splitState.currentSplits.length`:
     *
     * - N=1 (binary split, today's default) → ``Cancel | (L) | < | > | (R)
     *   | Split``. The L/R toggle is a SELECTION radio — pressing it picks
     *   which side the footer play button loops. Steppers nudge via
     *   `nudgeSplitBoundary`.
     * - N≥2 (multi-cursor, repetition auto-split) → ``Cancel | [1] [2] …
     *   [N+1] | Split``. Each ``[i]`` selects region i (0-indexed); footer
     *   play loops that region. No steppers — there's no obvious "the
     *   cursor" to step in multi mode; users drag the cursor lines
     *   directly. Click-to-seek on the canvas is also disabled in this
     *   mode (see split.ts `onMouseup`).
     *
     * The footer's single play/pause is the universal preview play surface;
     * this panel never spawns its own play button.
     */

    import { get } from 'svelte/store';

    import type { Segment } from '../../../../lib/types/domain';
    import {
        editingMountId,
        editStatusText,
        setSplitPreviewSelection,
        splitPreviewSelection,
        splitState,
    } from '../../stores/edit';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import {
        confirmSplit,
        nudgeSplitBoundary,
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

    // Preview selection — drives the footer play button's loop target.
    $: sel = $splitPreviewSelection;
    $: selLeftActive = isBinary && sel.kind === 'left';
    $: selRightActive = isBinary && sel.kind === 'right';
    function selRegion(i: number): boolean {
        return !isBinary && sel.kind === 'region' && sel.index === i;
    }

    // Clamp the selection if the cursor count changed and the previously
    // selected region no longer exists (e.g. user deleted a cursor).
    $: if (!isBinary && sel.kind === 'region' && sel.index >= regionCount) {
        setSplitPreviewSelection({ kind: 'region', index: Math.max(0, regionCount - 1) });
    }
    // Mode swap (binary ↔ multi): coerce the selection into a valid shape.
    $: if (isBinary && sel.kind === 'region') {
        setSplitPreviewSelection({ kind: sel.index === 0 ? 'left' : 'right' });
    }
    $: if (!isBinary && sel.kind !== 'region') {
        setSplitPreviewSelection({ kind: 'region', index: sel.kind === 'left' ? 0 : regionCount - 1 });
    }

    function pickLeft(): void { setSplitPreviewSelection({ kind: 'left' }); }
    function pickRight(): void { setSplitPreviewSelection({ kind: 'right' }); }
    function pickRegion(i: number): void { setSplitPreviewSelection({ kind: 'region', index: i }); }
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>
        {#if isBinary}
            <button
                class="btn btn-sm seg-split-pick"
                class:active={selLeftActive}
                aria-pressed={selLeftActive}
                title="Preview the LEFT half — press the footer play to loop"
                on:click={pickLeft}
            >L</button>
            <button class="btn btn-sm seg-split-step"
                title="Move split back {EDIT_NUDGE_MS} ms"
                disabled={splitBackDisabled}
                on:click={nudgeSplitBack}>&lt;</button>
            <button class="btn btn-sm seg-split-step"
                title="Move split forward {EDIT_NUDGE_MS} ms"
                disabled={splitFwdDisabled}
                on:click={nudgeSplitFwd}>&gt;</button>
            <button
                class="btn btn-sm seg-split-pick"
                class:active={selRightActive}
                aria-pressed={selRightActive}
                title="Preview the RIGHT half — press the footer play to loop"
                on:click={pickRight}
            >R</button>
        {:else}
            {#each regions as i}
                <button
                    class="btn btn-sm seg-split-pick seg-split-region"
                    class:active={selRegion(i)}
                    aria-pressed={selRegion(i)}
                    title="Preview region {i + 1} — press the footer play to loop"
                    on:click={() => pickRegion(i)}
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
    .seg-split-pick.active {
        background-color: var(--accent, #4a90e2);
        color: white;
    }
</style>
