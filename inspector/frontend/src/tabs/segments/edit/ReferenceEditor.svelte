<script lang="ts">
    /**
     * ReferenceEditor — Svelte shell for reference-edit mode.
     *
     * Reference editing is an inline operation managed by `startRefEdit` /
     * `commitRefEdit` in `segments/edit/reference.ts`. The imperative flow:
     *
     *  1. `startRefEdit` replaces a `.seg-text-ref` span's text with a
     *     `<input type="text">` element inline on the segment card.
     *  2. The user types a Quran ref (e.g. "2:255") and presses Enter or
     *     clicks away (blur → commit).
     *  3. `commitRefEdit` resolves the ref via `/api/seg/resolve_ref`,
     *     updates seg.matched_ref + seg.matched_text + seg.confidence,
     *     and calls `clearEdit()`.
     *  4. The split-chain path: after a split, `_chainSplitRefEdit`
     *     auto-chains to a second `startRefEdit` 100 ms later via
     *     setTimeout — the clearEdit/setEdit round-trip is correct
     *     because the timeout fires after clearEdit.
     *
     * The autocomplete logic is entirely in `reference.ts` and is not
     * Svelte-ified this wave (deferred to Wave 8 per Wave 7a.2 §8.2 —
     * the autocomplete is DOM-building / imperative and Svelte-ification
     * would be pure relocation without a behaviour unlock).
     *
     * No backdrop: reference editing is inline on the segment card row.
     * EditOverlay omits `.seg-edit-overlay` for reference mode.
     *
     * audioElRef prop (S2-D33): reserved for future reactive ref-input UI.
     * See TrimPanel.svelte for rationale on `export let` vs `export const`.
     */

    /** Audio element ref from SegmentsAudioControls — reserved for future
     *  Svelte-native reference input UI. Currently the imperative layer uses
     *  `dom.segAudioEl` in `startRefEdit` to pause playback on entry. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check doesn't flag
     it as dead; inspectable via devtools to confirm prop threading. -->
<div hidden data-reference-editor-audio-ref={audioElRef ? '1' : '0'}></div>
