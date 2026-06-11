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

    import type { Segment } from '../../../../lib/types/view-models';
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
        selectSplitRegion,
        selectSplitSide,
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

    // Per-region UI descriptors for multi-cursor (auto-split) mode. Rebuilt
    // whenever the split cursors (`ss`) OR the preview selection (`sel`)
    // change — both are passed as args so Svelte tracks them as real reactive
    // deps. The template iterates THIS array rather than calling helper
    // functions inline; a `foo(i)` call in markup hides its ss/sel reads from
    // Svelte's dependency analysis, so the disabled/highlight state wouldn't
    // re-evaluate on a pure selection switch (only after a cursor move).
    //
    // Boundary `i` is the cursor between region `i` and region `i+1` (there
    // are `cursorCount` of them; the last region has none). A boundary is
    // interactable only while it flanks the selected region — its right edge
    // (sel.index === i) or its left edge (sel.index === i+1).
    type RegionCtl = {
        i: number;
        selected: boolean;
        boundary: null | { active: boolean; backDisabled: boolean; fwdDisabled: boolean };
    };
    $: regionCtls = buildRegionCtls(ss, sel);

    function buildRegionCtls(s: typeof ss, selection: typeof sel): RegionCtl[] {
        const cs = s?.currentSplits;
        if (!s || !cs) return [];
        const selIdx = selection.kind === 'region' ? selection.index : -1;
        const minDur = EDIT_MIN_DURATION_MS;
        return Array.from({ length: cs.length + 1 }, (_, i): RegionCtl => {
            if (i >= cs.length) return { i, selected: selIdx === i, boundary: null };
            const cur = cs[i]!;
            const lo = (i > 0 ? cs[i - 1]! : s.seg.time_start) + minDur;
            const hi = (i < cs.length - 1 ? cs[i + 1]! : s.seg.time_end) - minDur;
            return {
                i,
                selected: selIdx === i,
                boundary: {
                    active: selIdx === i || selIdx === i + 1,
                    backDisabled: cur <= lo,
                    fwdDisabled: cur >= hi,
                },
            };
        });
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
        selectSplitSide(nextKind, canvas);
    }
    function pickRegionAndMaybeSwitch(i: number): void {
        selectSplitRegion(i, canvas);
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
                {#each regionCtls as r (r.i)}
                    <button class="seg-side-pick"
                        class:active={r.selected}
                        aria-pressed={r.selected}
                        title="Preview region {r.i + 1} — press footer ▶ to loop"
                        on:click={() => pickRegionAndMaybeSwitch(r.i)}
                    >{r.i + 1}</button>
                    {#if r.boundary}
                        <div class="seg-nudge-pair seg-nudge-split"
                            class:inactive={!r.boundary.active}
                            role="group"
                            aria-label="Adjust split between region {r.i + 1} and {r.i + 2}">
                            <button class="seg-nudge"
                                title="Move this split back {EDIT_NUDGE_MS} ms"
                                disabled={!r.boundary.active || r.boundary.backDisabled}
                                on:click={() => nudgeCursor(r.i, -EDIT_NUDGE_MS)}>&lsaquo;</button>
                            <button class="seg-nudge"
                                title="Move this split forward {EDIT_NUDGE_MS} ms"
                                disabled={!r.boundary.active || r.boundary.fwdDisabled}
                                on:click={() => nudgeCursor(r.i, EDIT_NUDGE_MS)}>&rsaquo;</button>
                        </div>
                    {/if}
                {/each}
            </div>
        {/if}

        <button class="btn btn-sm btn-confirm" on:click={onConfirm}>Split</button>
        <span class="seg-edit-status">{$editStatusText}</span>
    </div>
</div>
