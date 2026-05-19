<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Two layouts driven by `splitState.currentSplits.length`:
     *
     * - N=1 (binary split, today's default) → ``Cancel | (L | < | > | R) |
     *   Split``. L and R are SELECTION pills — clicking one picks which
     *   side the footer ▶ loops. If a loop is already running, clicking
     *   the OTHER side restarts the loop on that side; otherwise it just
     *   updates the selection. < > are CURSOR NUDGERS — they live BETWEEN
     *   L and R inside the same segmented yellow pill so the gadget reads
     *   as "the thing that controls the split."
     * - N≥2 (multi-cursor, repetition auto-split) → ``Cancel | [1][2]…[N+1]
     *   | Split``. Each ``[i]`` selects region i (0-indexed); same
     *   click-while-playing-switches-region semantics as L/R.
     *
     * Active L/R/region uses a 3px yellow top-accent bar plus a 700 weight
     * bump — no clashing colors, no inset rings; reads as a selected tab.
     *
     * The footer's single play/pause is the universal play surface — this
     * panel never spawns its own play button.
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
    import { segPort } from '../../stores/playback';
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import {
        confirmSplit,
        nudgeSplitBoundary,
        previewSplitAudio,
        previewSplitRegion,
    } from '../../utils/edit/split';
    import { getPlayRangeRAF } from '../../utils/playback/play-range';

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

    // Clamp the selection if cursor count changed and the previously-
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

    /** Set selection. If a loop is running (paused or playing), also switch
     *  it to the new range so the user doesn't have to re-press footer ▶. */
    function pickAndMaybeSwitch(nextKind: 'left' | 'right'): void {
        setSplitPreviewSelection({ kind: nextKind });
        if (getPlayRangeRAF() && !segPort.paused) {
            previewSplitAudio(nextKind, canvas);
        }
    }
    function pickRegionAndMaybeSwitch(i: number): void {
        setSplitPreviewSelection({ kind: 'region', index: i });
        if (getPlayRangeRAF() && !segPort.paused) {
            previewSplitRegion(i, canvas);
        }
    }
</script>

<div class="seg-edit-inline">
    <div class="seg-edit-buttons">
        <button class="btn btn-sm btn-cancel" on:click={exitEditMode}>Cancel</button>

        {#if isBinary}
            <div class="seg-split-group" role="group" aria-label="Split preview & cursor">
                <button class="seg-pick"
                    class:active={selLeftActive}
                    aria-pressed={selLeftActive}
                    title="Preview the LEFT half — press footer ▶ to loop"
                    on:click={() => pickAndMaybeSwitch('left')}
                >L</button>
                <button class="seg-step"
                    title="Move split back {EDIT_NUDGE_MS} ms"
                    disabled={splitBackDisabled}
                    on:click={nudgeSplitBack}>&lt;</button>
                <button class="seg-step"
                    title="Move split forward {EDIT_NUDGE_MS} ms"
                    disabled={splitFwdDisabled}
                    on:click={nudgeSplitFwd}>&gt;</button>
                <button class="seg-pick"
                    class:active={selRightActive}
                    aria-pressed={selRightActive}
                    title="Preview the RIGHT half — press footer ▶ to loop"
                    on:click={() => pickAndMaybeSwitch('right')}
                >R</button>
            </div>
        {:else}
            <div class="seg-split-group" role="group" aria-label="Region preview">
                {#each regions as i}
                    <button class="seg-pick seg-pick-region"
                        class:active={selRegion(i)}
                        aria-pressed={selRegion(i)}
                        title="Preview region {i + 1} — press footer ▶ to loop"
                        on:click={() => pickRegionAndMaybeSwitch(i)}
                    >{i + 1}</button>
                {/each}
            </div>
        {/if}

        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
