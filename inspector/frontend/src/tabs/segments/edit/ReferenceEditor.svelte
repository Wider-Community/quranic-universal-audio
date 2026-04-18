<script lang="ts">
    /**
     * ReferenceEditor — Svelte shell for reference-edit mode.
     *
     * Reference editing is an inline operation managed by `startRefEdit` /
     * `commitRefEdit` in `lib/utils/segments/edit-reference.ts`. The flow:
     *   1. `startRefEdit` replaces a `.seg-text-ref` span's text with an
     *      `<input type="text">` element inline on the segment card.
     *   2. The user types a Quran ref (e.g. "2:255") and presses Enter or
     *      clicks away (blur → commit).
     *   3. `commitRefEdit` resolves the ref, updates the segment, and
     *      calls `clearEdit()`.
     *   4. After a split, `_chainSplitRefEdit` auto-chains to a second
     *      `startRefEdit` so the user edits both halves in sequence.
     *
     * The panel renders no visible DOM — reference editing happens inline
     * on the row. EditOverlay omits the backdrop for this mode.
     */

    /** Audio element ref passed from SegmentsAudioControls — reserved for
     *  future Svelte-native reference-input UI. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check does not flag
     it as dead; inspectable via devtools. -->
<div hidden data-reference-editor-audio-ref={audioElRef ? '1' : '0'}></div>
