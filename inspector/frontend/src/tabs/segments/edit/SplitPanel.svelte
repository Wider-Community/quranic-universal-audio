<script lang="ts">
    /**
     * SplitPanel — Svelte shell for split-mode edit.
     *
     * Wave 7a.2 migration strategy (per user #migration-strictness pref):
     * delegates split-mode drag + confirm + chain-ref handoff to the
     * existing imperative helpers in `segments/edit/split.ts` +
     * `segments/edit/common.ts`. Those modules already:
     *
     *  - inject inline buttons (Cancel / Play Left / Play Right / Split)
     *    into `.seg-left` via `enterSplitMode` (split.ts lines 50-73)
     *  - wire single-handle drag on the canvas (`setupSplitDragHandle`,
     *    split.ts lines 194-259)
     *  - render the split overlay (yellow line + right-tint,
     *    `drawSplitWaveform`, split.ts lines 151-188)
     *  - run confirmSplit which mints fresh `segment_uid` for each half
     *    (crypto.randomUUID) so the {#each} reconciler splices cleanly
     *    (validated Wave 7a.1 §2.1 advisor review)
     *  - trigger the chain-ref flow via `startRefEdit(firstRow)` in
     *    split.ts:374 — the `state._splitChainUid` mechanism for finding
     *    the new first-half row still works because Svelte writes
     *    `data-seg-uid` on every row (SegmentRow.svelte line 131)
     *
     * This component exists as a Svelte mount point so Wave 7b / Wave 11
     * can migrate slices (declarative L/R duration span, reactive drag
     * handle position) without re-threading the entry path. Today it's
     * a no-visual-output passthrough.
     *
     * audioElRef prop (S2-D33): reserved for future reactive preview
     * controls. Today `_playRange` in common.ts reaches through
     * `dom.segAudioEl`.
     */

    /** Audio element ref from SegmentsAudioControls — reserved for future
     *  Svelte-native preview controls. See TrimPanel for rationale.
     *
     *  `export const` rather than `export let` — flips back to `let`
     *  when Wave 7b / Wave 11 lands reactive preview controls. */
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    export const audioElRef: HTMLAudioElement | null = null;
</script>
