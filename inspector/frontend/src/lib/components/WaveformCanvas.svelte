<script lang="ts">
    /**
     * WaveformCanvas — base canvas primitive for waveform display.
     *
     * Renders a peaks-based waveform using drawWaveformPeaks() from
     * lib/utils/waveform-draw.ts. Overlays (trim handles, split line, merge
     * highlight, playhead) are added by extension components in Waves 6+.
     *
     * The legacy segments/waveform/draw.ts continues to use its own copy of
     * the draw algorithm (bound to SegCanvas + state imports) during Stage 2;
     * lib/utils/waveform-draw.ts is the portable pure helper both call.
     */

    import { onMount } from 'svelte';
    import type { PeakBucket } from '../../types/domain';
    import { drawWaveformPeaks } from '../utils/waveform-draw';

    /** Peak data to render. null = show empty (black) canvas. */
    export let peaks: PeakBucket[] | null = null;
    /** Canvas display width in pixels. */
    export let width = 300;
    /** Canvas display height in pixels. */
    export let height = 60;
    /** Optional inline style string forwarded to the <canvas> element. */
    export let style = '';

    let canvas: HTMLCanvasElement;

    $: if (canvas && peaks) redraw(peaks);
    $: if (canvas && !peaks) clearCanvas();

    function redraw(p: PeakBucket[]): void {
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        drawWaveformPeaks(ctx, p, canvas.width, canvas.height);
    }

    function clearCanvas(): void {
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.fillStyle = '#0f0f23';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    onMount(() => {
        if (peaks) redraw(peaks);
        else clearCanvas();
    });

    /** Expose the raw canvas element so extension components can draw overlays. */
    export function getCanvas(): HTMLCanvasElement {
        return canvas;
    }
</script>

<canvas bind:this={canvas} {width} {height} {style}></canvas>

<style>
    canvas {
        display: block;
        background: #0f0f23;
    }
</style>
