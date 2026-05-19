<script lang="ts">
    /**
     * SplitPanel — Svelte-rendered inline chrome for split-mode edit.
     *
     * Layout:
     *   - Binary (N=1) → ``Cancel    L   <  >   R    Split``.
     *     L and R are SELECTION pills (bordered, distinct chrome) that
     *     pick which side the footer ▶ loops. The `< >` carets between
     *     them nudge the split cursor — bare buttons with a yellow
     *     underline that mirrors the canvas split-line, so the two roles
     *     are visually distinct without needing a containing pill.
     *   - Multi (N≥2) → ``Cancel    [1] [2] … [N+1]    Split``.
     *     Region pills behave like L/R in binary mode.
     *
     * Clicking the OTHER side / region while a loop is running switches
     * the loop immediately rather than waiting for the user to re-press
     * the footer ▶.
     *
     * Preview play/pause is owned entirely by the footer ▶ + Space
     * shortcut, centralised through `onSegPlayClick`. This panel never
     * spawns its own play button.
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

    $: sel = $splitPreviewSelection;
    $: selLeftActive = isBinary && sel.kind === 'left';
    $: selRightActive = isBinary && sel.kind === 'right';
    function selRegion(i: number): boolean {
        return !isBinary && sel.kind === 'region' && sel.index === i;
    }

    // Clamp the selection if cursor count changed and the previously
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

    /** Update selection. If a loop is running, switch it to the new range
     *  immediately so the user doesn't have to re-press footer ▶. */
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
            <button class="seg-side-pick"
                class:active={selLeftActive}
                aria-pressed={selLeftActive}
                title="Preview the LEFT half — press footer ▶ to loop"
                on:click={() => pickAndMaybeSwitch('left')}
            >L</button>

            <div class="seg-nudge-pair seg-nudge-split" role="group" aria-label="Split cursor">
                <button class="seg-nudge"
                    title="Move split back {EDIT_NUDGE_MS} ms"
                    disabled={splitBackDisabled}
                    on:click={nudgeSplitBack}>&lsaquo;</button>
                <button class="seg-nudge"
                    title="Move split forward {EDIT_NUDGE_MS} ms"
                    disabled={splitFwdDisabled}
                    on:click={nudgeSplitFwd}>&rsaquo;</button>
            </div>

            <button class="seg-side-pick"
                class:active={selRightActive}
                aria-pressed={selRightActive}
                title="Preview the RIGHT half — press footer ▶ to loop"
                on:click={() => pickAndMaybeSwitch('right')}
            >R</button>
        {:else}
            <div class="seg-region-picks" role="group" aria-label="Region preview">
                {#each regions as i}
                    <button class="seg-side-pick"
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
