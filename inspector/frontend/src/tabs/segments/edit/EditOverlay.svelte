<script lang="ts">
    /**
     * EditOverlay — Svelte-owned backdrop + shell for merge / delete /
     * reference edit modes.
     *
     * Trim / split panels used to mount here; as of Ph6f-2 they render
     * inline inside each row's `.seg-left` (SegmentRow.svelte) so the
     * Cancel / Preview / Apply chrome lives next to the row it is acting
     * on. Only the viewport-scoping `.seg-edit-overlay` backdrop for the
     * persistent drag modes (trim + split) remains here.
     */

    import { editMode } from '../../../lib/stores/segments/edit';

    import DeletePanel from './DeletePanel.svelte';
    import MergePanel from './MergePanel.svelte';
    import ReferenceEditor from './ReferenceEditor.svelte';

    /** The audio element owned by SegmentsAudioControls (bind:audioEl).
     *  Passed into MergePanel / DeletePanel / ReferenceEditor so they
     *  don't need `document.getElementById('seg-audio-player')`. */
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
    {:else if $editMode === 'reference'}
        <ReferenceEditor {audioElRef} />
    {/if}
{/if}
