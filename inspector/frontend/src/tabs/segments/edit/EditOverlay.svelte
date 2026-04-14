<script lang="ts">
    /**
     * EditOverlay — Svelte-owned backdrop + shell that delegates to
     * TrimPanel / SplitPanel based on `$editMode`.
     *
     * Replaces the body-append backdrop in `segments/edit/common.ts::
     * _addEditOverlay()` with a reactive `{#if $editMode}` div.
     *
     * Wave 7a.2 migration strategy (per user #migration-strictness pref,
     * 2026-04-14): keep the existing imperative trim.ts / split.ts drag
     * logic. Those modules already operate on the `{#each}`-rendered rows
     * (validated in 7a.1 reasoning); rewriting the drag/DOM creation into
     * Svelte would be incremental refinement, not a behaviour unlock, and
     * would cost churn. EditOverlay's concrete responsibilities:
     *
     *  1. Own the backdrop div (`.seg-edit-overlay`) reactively via
     *     `{#if $editMode !== null}`. The old
     *     `common.ts::_addEditOverlay()` / `_removeEditOverlay()` helpers
     *     stay as no-ops for now — deleting them touches 3 callers; the
     *     cleanup carries to a later wave.
     *  2. Delegate to `<TrimPanel>` / `<SplitPanel>` via `{#if $editMode ===
     *     'trim'}` / `'split'` so future Wave 7b refinements (or Wave 11
     *     cleanup) can migrate more logic into those components without
     *     touching SegmentsTab.
     *  3. Accept `audioElRef: HTMLAudioElement | null` (S2-D33) and pass
     *     it down — removes the need for panels to use
     *     `document.getElementById('seg-audio-player')`.
     *
     * Escape key: Stage-1 `segments/keyboard.ts` already handles Escape →
     * `_handlers.exitEditMode()` via the registry pattern. We don't add a
     * duplicate keydown listener here.
     *
     * Z-order: .seg-edit-overlay has `z-index` set in styles/segments.css;
     * the imperative body-append placed the overlay as the last child of
     * <body>. Rendering here (inside #segments-panel-inner) preserves the
     * same visual effect because the overlay is `position: fixed; inset: 0;`
     * — it escapes the stacking context and blankets the whole viewport.
     * See styles/segments.css:326-340.
     */

    import { editMode } from '../../../lib/stores/segments/edit';

    import SplitPanel from './SplitPanel.svelte';
    import TrimPanel from './TrimPanel.svelte';

    /** The audio element owned by SegmentsAudioControls (bind:audioEl).
     *  Passed into TrimPanel / SplitPanel so they don't need
     *  `document.getElementById('seg-audio-player')`. Null until
     *  SegmentsAudioControls mounts (onMount runs parent-first in Svelte 4
     *  but the bind:this target resolves before onMount fires). */
    export let audioElRef: HTMLAudioElement | null = null;
</script>

{#if $editMode !== null}
    <div class="seg-edit-overlay"></div>
    {#if $editMode === 'trim'}
        <TrimPanel {audioElRef} />
    {:else if $editMode === 'split'}
        <SplitPanel {audioElRef} />
    {/if}
{/if}
