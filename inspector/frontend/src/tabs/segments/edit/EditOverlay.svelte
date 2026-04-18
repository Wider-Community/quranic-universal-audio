<script lang="ts">
    /**
     * EditOverlay — Svelte-owned backdrop + shell for merge / delete modes.
     *
     * Trim / split panels render inline inside each row's `.seg-left`
     * (SegmentRow.svelte) so the Cancel / Preview / Apply chrome lives
     * next to the row it is acting on. Reference editing is also inline
     * — SegmentRow swaps the `.seg-text-ref` span for a ReferenceEditor
     * input when the row is the current ref-edit target. Only the
     * viewport-scoping `.seg-edit-overlay` backdrop for the persistent
     * drag modes (trim + split) remains here, along with the Merge /
     * Delete confirmation shells.
     */

    import { editMode } from '../../../lib/stores/segments/edit';

    import DeletePanel from './DeletePanel.svelte';
    import MergePanel from './MergePanel.svelte';

    /** The audio element owned by SegmentsAudioControls (bind:audioEl).
     *  Passed into MergePanel / DeletePanel so they don't need
     *  `document.getElementById('seg-audio-player')`. */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

{#if $editMode !== null}
    <!-- Backdrop only for trim/split (persistent drag modes). Merge/delete
         are one-shot operations and reference editing is inline — showing
         a viewport-scoping overlay for those would be a UX regression. -->
    {#if $editMode === 'trim' || $editMode === 'split'}
        <div class="seg-edit-overlay"></div>
    {/if}
    {#if $editMode === 'merge'}
        <MergePanel {audioElRef} />
    {:else if $editMode === 'delete'}
        <DeletePanel {audioElRef} />
    {/if}
{/if}
