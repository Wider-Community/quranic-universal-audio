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
     *   - Multi (N≥2) → ``Cancel  [1] ‹› [2] ‹› … [N+1]  Split``.
     *     Region pills behave like L/R in binary mode. A `‹ ›` nudge pair
     *     sits between every adjacent pill, stepping the cursor at that
     *     boundary. All pairs are always rendered (stable layout), but only
     *     the two flanking the SELECTED region are interactable — the rest
     *     are dimmed + disabled. Each pair carries the same yellow
     *     split-line underline as binary mode. Covers both auto-split kinds
     *     (cross-verse across 3+ verses, and repetitions).
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
    import type { SegCanvas } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS, EDIT_NUDGE_MS } from '../../utils/constants';
    import { exitEditMode } from '../../utils/edit/common';
    import {
        confirmSplit,
        nudgeSplitBoundary,
        nudgeSplitCursor,
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

    $: sel = $splitPreviewSelection;
    $: selLeftActive = isBinary && sel.kind === 'left';
    $: selRightActive = isBinary && sel.kind === 'right';
    function selRegion(i: number): boolean {
        return !isBinary && sel.kind === 'region' && sel.index === i;
    }

    // Multi-cursor nudge helpers. Boundary `c` is the cursor between region
    // `c` and region `c+1` (there are cursorCount of them). A boundary is
    // interactable only while it flanks the selected region — i.e. it's that
    // region's right edge (sel.index === c) or left edge (sel.index === c+1).
    function boundaryActive(c: number): boolean {
        return sel.kind === 'region' && (sel.index === c || sel.index === c + 1);
    }
    function cursorBackDisabled(c: number): boolean {
        const cs = ss?.currentSplits;
        if (!ss || !cs || cs[c] === undefined) return true;
        const lo = (c > 0 ? cs[c - 1]! : ss.seg.time_start) + EDIT_MIN_DURATION_MS;
        return cs[c]! <= lo;
    }
    function cursorFwdDisabled(c: number): boolean {
        const cs = ss?.currentSplits;
        if (!ss || !cs || cs[c] === undefined) return true;
        const hi = (c < cs.length - 1 ? cs[c + 1]! : ss.seg.time_end) - EDIT_MIN_DURATION_MS;
        return cs[c]! >= hi;
    }
    function nudgeCursor(c: number, deltaMs: number): void { nudgeSplitCursor(c, deltaMs); }

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

    /** Set selection AND cold-start a looping preview of that range —
     *  the legacy "Play Left / Play Right" behavior. Footer ▶ + Space
     *  remain the universal pause/resume; clicking the SAME side again
     *  while it's playing just restarts that side from the loop start.
     *  `mode: 'cold'` bypasses the entry-time warm-attach so an explicit
     *  pill click always seeks-and-plays from the region's start. */
    function pickAndMaybeSwitch(nextKind: 'left' | 'right'): void {
        setSplitPreviewSelection({ kind: nextKind });
        previewSplitAudio(nextKind, canvas, { mode: 'cold' });
    }
    function pickRegionAndMaybeSwitch(i: number): void {
        setSplitPreviewSelection({ kind: 'region', index: i });
        previewSplitRegion(i, canvas, { mode: 'cold' });
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
                    {#if i < cursorCount}
                        <div class="seg-nudge-pair seg-nudge-split"
                            class:inactive={!boundaryActive(i)}
                            role="group"
                            aria-label="Adjust split between region {i + 1} and {i + 2}">
                            <button class="seg-nudge"
                                title="Move this split back {EDIT_NUDGE_MS} ms"
                                disabled={!boundaryActive(i) || cursorBackDisabled(i)}
                                on:click={() => nudgeCursor(i, -EDIT_NUDGE_MS)}>&lsaquo;</button>
                            <button class="seg-nudge"
                                title="Move this split forward {EDIT_NUDGE_MS} ms"
                                disabled={!boundaryActive(i) || cursorFwdDisabled(i)}
                                on:click={() => nudgeCursor(i, EDIT_NUDGE_MS)}>&rsaquo;</button>
                        </div>
                    {/if}
                {/each}
            </div>
        {/if}

        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
