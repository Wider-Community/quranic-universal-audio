<script lang="ts">
    /**
     * SplitPanel — Svelte shell for split-mode edit.
     *
     * Delegates drag + confirm + chain-ref handoff to the imperative
     * helpers in `edit-split.ts` + `edit-common.ts`. Those modules inject
     * inline Cancel / Play Left / Play Right / Split buttons, wire the
     * drag handle, render the split overlay, and run confirmSplit which
     * mints fresh segment UIDs so the {#each} reconciler splices cleanly.
     *
     * This component exists as a Svelte mount point so future refinements
     * (declarative L/R duration span, reactive drag handle) can replace
     * slices without re-threading the entry path. Today it emits no
     * visible DOM.
     */

    /** Audio element ref passed from SegmentsAudioControls — reserved for
     *  future Svelte-native preview controls. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check does not flag
     it as dead; inspectable via devtools. -->
<div hidden data-split-panel-audio-ref={audioElRef ? '1' : '0'}></div>
