<script lang="ts">
    /**
     * TrimPanel — Svelte shell for trim-mode edit.
     *
     * Delegates drag + confirm + preview to the imperative helpers in
     * `edit-trim.ts` + `edit-common.ts`. Those modules inject inline
     * Cancel / Preview / Apply buttons into `.seg-left`, wire drag
     * handlers on the canvas, render the trim overlay, and run confirm /
     * exit cleanups that play well with the {#each} row reconciliation.
     *
     * This component exists as a Svelte mount point so future refinements
     * can migrate slices (declarative buttons, reactive duration span)
     * without re-threading the entry path. Today it emits no visible DOM.
     */

    /** Audio element ref passed from SegmentsAudioControls — reserved for
     *  future Svelte-native preview controls. `export let` (not `const`)
     *  so Svelte wires the parent-supplied value; the data-attribute below
     *  consumes it to silence unused-export lint. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check does not flag
     it as dead; inspectable via devtools. -->
<div hidden data-trim-panel-audio-ref={audioElRef ? '1' : '0'}></div>
