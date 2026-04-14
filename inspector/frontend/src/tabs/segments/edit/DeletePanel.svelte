<script lang="ts">
    /**
     * DeletePanel — Svelte shell for delete-mode.
     *
     * Delete is a one-shot synchronous operation (`deleteSegment`) — it uses
     * the browser's native `confirm()` dialog before mutating state. No
     * persistent drag UI. The panel exists as a Svelte mount point so:
     *  1. EditOverlay can delegate via `{:else if $editMode === 'delete'}`.
     *  2. Future waves can replace the `confirm()` call with a Svelte-native
     *     confirmation UI (inline banner or modal) without re-threading the
     *     entry path.
     *
     * Note: `setEdit('delete', uid)` is called AFTER the confirm() dialog
     * passes (see `segments/edit/delete.ts`) — so the store only transitions
     * to 'delete' for the brief instant between confirm and clearEdit(). The
     * panel may mount and immediately unmount in the same tick; that's fine.
     *
     * No backdrop: delete is instant and uses a native dialog. EditOverlay
     * omits `.seg-edit-overlay` for delete (see EditOverlay.svelte backdrop
     * condition).
     *
     * audioElRef prop (S2-D33): reserved for future Svelte-native confirm UI.
     * See TrimPanel.svelte for rationale on `export let` vs `export const`.
     */

    /** Audio element ref from SegmentsAudioControls — reserved for future
     *  Svelte-native delete confirmation UI. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

<!-- Invisible marker: consumes audioElRef so svelte-check doesn't flag
     it as dead; inspectable via devtools to confirm prop threading. -->
<div hidden data-delete-panel-audio-ref={audioElRef ? '1' : '0'}></div>
