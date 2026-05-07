<script lang="ts">
    /**
     * MergePanel — Svelte shell for merge-mode.
     *
     * Merge is a one-shot async operation (`mergeAdjacent`) — no persistent
     * drag UI. EditOverlay delegates to this panel via the `$editMode ===
     * 'merge'` branch; the imperative `mergeAdjacent` runs to completion and
     * calls `clearEdit()` itself. The panel exists as a Svelte mount point
     * so future refinements (e.g. "Resolving merged ref…" progress text)
     * can be added without re-threading the entry path.
     */

    /** Audio element ref passed from SegmentsAudioControls — reserved for
     *  future reactive status display. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check does not flag
     it as dead; inspectable via devtools. -->
<div hidden data-merge-panel-audio-ref={audioElRef ? '1' : '0'}></div>
