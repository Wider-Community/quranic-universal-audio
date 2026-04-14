<script lang="ts">
    /**
     * SavePreview — shell component for the save-preview panel.
     *
     * Extracts #seg-save-preview from SegmentsTab.svelte's inline HTML.
     * All IDs are preserved so mustGet() in segments/state.ts continues to
     * resolve the DOM refs (DomRefs.segSavePreview, etc.).
     *
     * Visibility is driven by the $savePreviewVisible store; the imperative
     * segments/save.ts calls showPreview()/hidePreview() to toggle it.
     * Inner content (stats, batches) is still rendered imperatively by
     * segments/history/rendering.ts into #seg-save-preview-stats /
     * #seg-save-preview-batches — Wave 10 will migrate that.
     *
     * Wave 9 (2026-04-14): shell-delegation — store owns visibility,
     * imperative code owns content.
     */
    import { savePreviewVisible } from '../../../lib/stores/segments/save';
</script>

<div id="seg-save-preview" class="seg-history-view" hidden={!$savePreviewVisible}>
    <div class="seg-history-toolbar seg-save-preview-toolbar">
        <button id="seg-save-preview-cancel" class="btn">&larr; Cancel</button>
        <span class="seg-history-title">Review Changes</span>
        <button id="seg-save-preview-confirm" class="btn btn-save">Confirm Save</button>
    </div>
    <div id="seg-save-preview-stats" class="seg-history-stats"></div>
    <div id="seg-save-preview-batches" class="seg-history-batches"></div>
</div>
