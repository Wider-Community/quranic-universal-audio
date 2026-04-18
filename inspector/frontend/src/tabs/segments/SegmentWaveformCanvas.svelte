<script lang="ts">
    /**
     * SegmentWaveformCanvas — per-segment-row waveform primitive for the Segments tab.
     *
     * Wraps the shared <WaveformCanvas> component with segment-specific concerns:
     *   - Resolves peaks from the chapter-wide peaks payload via startMs/endMs sub-ranging
     *     (S2-D32 — WaveformCanvas already accepts these props).
     *   - Exposes overlay hooks (trim/split/merge highlight descriptors, playhead position)
     *     so imperative edit-mode code can draw on the underlying canvas without re-fetching.
     *
     * ## Usage (Wave 7+)
     * ```svelte
     * <SegmentWaveformCanvas
     *   {seg}
     *   chapterPeaks={$chapterPeaks}
     *   startMs={seg.time_start}
     *   endMs={seg.time_end}
     *   totalDurationMs={chapterDurationMs}
     * />
     * ```
     *
     * ## Wave 6b status
     * INTENTIONALLY UNUSED during Wave 6b. SegmentRow.svelte still uses the
     * imperative renderSegList() bridge that creates <canvas> nodes directly.
     * Wave 7 (SegmentRow {#each} adoption) will mount this component inside
     * SegmentRow.svelte. The component is built-and-typechecked here so Wave 7
     * starts from a working surface.
     *
     * ## Overlay model (hybrid — pattern #8)
     * The playback cursor and highlight descriptors (trim/split/merge) are
     * applied imperatively through getCanvas() + the SegCanvas extension type
     * — they are written at 60fps by the animation loop and must not trigger
     * Svelte reactive re-renders. The component exposes getCanvas() for that
     * purpose. Svelte owns the structural waveform render (peaks change);
     * imperative code owns the overlay draw.
     */

    import { onMount } from 'svelte';
    import WaveformCanvas from '../../lib/components/WaveformCanvas.svelte';
    import type { SegCanvas } from '../../lib/types/segments-waveform';
    import type { AudioPeaks, Segment } from '../../lib/types/domain';

    // ---------------------------------------------------------------------------
    // Props
    // ---------------------------------------------------------------------------

    /** The segment this waveform row represents. */
    export let seg: Segment;

    /**
     * Chapter-wide peaks payload. When provided together with startMs/endMs/
     * totalDurationMs, WaveformCanvas renders just the segment's time slice
     * via S2-D32 sub-ranging. Pass null to show an empty canvas.
     */
    export let chapterPeaks: AudioPeaks | null = null;

    /**
     * Sub-range start in milliseconds — typically seg.time_start.
     * Passed through to WaveformCanvas for sub-ranging (S2-D32).
     */
    export let startMs: number | undefined = undefined;

    /**
     * Sub-range end in milliseconds — typically seg.time_end.
     * Passed through to WaveformCanvas for sub-ranging (S2-D32).
     */
    export let endMs: number | undefined = undefined;

    /**
     * Total duration the chapter peaks array covers, in milliseconds.
     * Required together with startMs/endMs for sub-ranging.
     */
    export let totalDurationMs: number | undefined = undefined;

    /** Canvas display width in pixels. */
    export let width = 300;

    /** Canvas display height in pixels. */
    export let height = 60;

    // ---------------------------------------------------------------------------
    // Internal refs
    // ---------------------------------------------------------------------------

    let waveformCanvas: WaveformCanvas;

    // seg drives data-* attributes on the canvas for IntersectionObserver lookup.
    // The attributes are already placed in the template below; Svelte will update
    // them reactively when seg changes (Wave 7 wires the observer to read them).

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    /**
     * Return the underlying HTMLCanvasElement as SegCanvas so imperative overlay
     * code (playhead draw, trim/split/merge highlight descriptors) can attach
     * ad-hoc fields and draw without triggering Svelte reactivity.
     *
     * Used by: segments/waveform/index.ts IntersectionObserver callbacks,
     *           segments/playback/index.ts drawSegPlayhead calls (Wave 7+).
     */
    export function getCanvas(): SegCanvas {
        return waveformCanvas.getCanvas() as SegCanvas;
    }

    // onMount is a no-op for now; retained as the natural extension point for
    // Wave 7 to wire the IntersectionObserver via getCanvas().
    onMount(() => {
        // Wave 7: attach data-needs-waveform + observe via _ensureWaveformObserver()
    });
</script>

<!--
    data-seg-index / data-seg-chapter are read by the IntersectionObserver in
    segments/waveform/index.ts to look up the segment from the store. Wave 7
    mounts this component inside .seg-row which already carries those attrs;
    we also set them here so a standalone canvas can be observed correctly.
-->
<div
    data-seg-index={seg.index}
    data-seg-chapter={seg.chapter}
    class="seg-waveform-canvas-root"
>
    <WaveformCanvas
        bind:this={waveformCanvas}
        peaks={chapterPeaks?.peaks ?? null}
        {width}
        {height}
        {startMs}
        {endMs}
        {totalDurationMs}
    />
</div>

<style>
    .seg-waveform-canvas-root {
        display: contents;
    }
</style>
