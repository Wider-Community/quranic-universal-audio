<script lang="ts">
    /**
     * TrimPanel — Svelte shell for trim-mode edit.
     *
     * Wave 7a.2 migration strategy (per user #migration-strictness pref):
     * delegates trim-mode drag + confirm + preview to the existing
     * imperative helpers in `segments/edit/trim.ts` + `segments/edit/
     * common.ts`. Those modules already:
     *
     *  - inject inline buttons (Cancel / Preview / Apply) into `.seg-left`
     *    via `enterTrimMode` (trim.ts lines 37-62)
     *  - wire drag handlers on the canvas (`setupTrimDragHandles`, trim.ts
     *    lines 175-252)
     *  - render the trim overlay (green/red handles + dim regions,
     *    `drawTrimWaveform`, trim.ts lines 133-169)
     *  - run confirmTrim / exitEditMode which play well with the {#each}
     *    row reconciliation (validated in Wave 7a.1, §2.1 advisor review)
     *
     * This component exists as a Svelte mount point so future waves can
     * migrate slices (e.g. render the Cancel/Apply buttons declaratively,
     * bind the duration span reactively) without re-threading the entry
     * path. Today it's a no-visual-output passthrough — the imperative
     * DOM injection remains the source of truth and renders inside the
     * seg-row that 7a.1's {#each} reconciles.
     *
     * audioElRef prop (S2-D33): future refinements that need the audio
     * element inside TrimPanel (e.g. a reactive preview-playback button
     * rendered from here) use this rather than `document.getElementById`.
     * Today `_playRange` in common.ts reaches through `dom.segAudioEl`.
     */

    /** Audio element ref from SegmentsAudioControls — reserved for future
     *  Svelte-native preview controls. Currently unused in the template;
     *  panels rely on the imperative `dom.segAudioEl` registered by
     *  SegmentsAudioControls. Kept in the signature (S2-D33) so Wave 7b /
     *  Wave 11 can drop in reactive controls without plumbing changes.
     *
     *  `export const` rather than `export let` — the parent still passes
     *  the ref through (`<TrimPanel audioElRef={segAudioEl} />`) but
     *  Svelte's unused-prop warning prefers `const` for slots the
     *  component reads but never reassigns. Once Wave 11 wires a
     *  reactive preview button this will flip back to `export let`. */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    export const audioElRef: HTMLAudioElement | null = null;
</script>
