<script lang="ts">
    /**
     * MergePanel — Svelte shell for merge-mode.
     *
     * Merge is a one-shot async operation (`mergeAdjacent`) — there is no
     * persistent drag UI like trim/split. The panel exists as a Svelte mount
     * point so:
     *  1. EditOverlay can delegate to it via `{:else if $editMode === 'merge'}`.
     *  2. Future waves can render progress state (e.g. "Resolving merged ref…")
     *     without re-threading the entry path.
     *
     * Today it renders only an invisible marker (same pattern as TrimPanel /
     * SplitPanel, per Wave 7a.2 §1.7). The imperative `mergeAdjacent` in
     * `segments/edit/merge.ts` runs to completion synchronously / asynchronously
     * and calls `clearEdit()` itself — no confirm/cancel buttons needed here.
     *
     * No backdrop: merge is instant (the store transitions merge → null before
     * the next render tick). EditOverlay omits `.seg-edit-overlay` for merge
     * (see EditOverlay.svelte backdrop condition).
     *
     * audioElRef prop (S2-D33): reserved for future reactive status display.
     * Today `mergeAdjacent` uses `dom.segAudioEl` from the imperative layer.
     */

    /** Audio element ref from SegmentsAudioControls — reserved for future
     *  reactive merge-status feedback. See TrimPanel.svelte for rationale
     *  on `export let` vs `export const`. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check doesn't flag
     it as dead; inspectable via devtools to confirm prop threading. -->
<div hidden data-merge-panel-audio-ref={audioElRef ? '1' : '0'}></div>
