/**
 * Pure waveform drawing helper — no state, no side effects, no imports from
 * tab modules. Shared by all waveform canvas contexts.
 */

import type { PeakBucket } from '../types/domain';

/**
 * Options for drawWaveformPeaks().
 *
 * Sub-ranging: when startMs, endMs, and totalDurationMs are all provided,
 * only the corresponding slice of the peaks array is drawn. This lets
 * consumers pass a full chapter-wide peaks array and render just one
 * segment's time range (used by per-row waveforms and history diff thumbnails).
 * When any of the three are absent, the full array is drawn.
 */
export interface DrawWaveformOptions {
    /** Canvas width in pixels. */
    width: number;
    /** Canvas height in pixels. */
    height: number;
    /**
     * Start of the time range to draw, in milliseconds.
     * Must be provided together with endMs and totalDurationMs.
     */
    startMs?: number;
    /**
     * End of the time range to draw, in milliseconds.
     * Must be provided together with startMs and totalDurationMs.
     */
    endMs?: number;
    /**
     * Total audio duration in milliseconds (i.e. the duration the full
     * peaks array covers). Must be provided together with startMs and endMs.
     */
    totalDurationMs?: number;
}

/**
 * Draw a peak-based waveform onto the given canvas context.
 *
 * @param ctx   - 2D canvas rendering context (canvas must already be sized)
 * @param peaks - Array of [min, max] amplitude buckets (values in [-1, 1])
 * @param opts  - Drawing options (see DrawWaveformOptions)
 */
export function drawWaveformPeaks(
    ctx: CanvasRenderingContext2D,
    peaks: PeakBucket[],
    opts: DrawWaveformOptions,
): void {
    const { width, height, startMs, endMs, totalDurationMs } = opts;
    const centerY = height / 2;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    if (!peaks || peaks.length === 0) return;

    // Apply sub-range slicing when all three range params are present.
    let drawPeaks = peaks;
    if (startMs !== undefined && endMs !== undefined && totalDurationMs !== undefined && totalDurationMs > 0) {
        const i0 = Math.floor(peaks.length * startMs / totalDurationMs);
        const i1 = Math.ceil(peaks.length * endMs / totalDurationMs);
        drawPeaks = peaks.slice(i0, i1);
    }

    if (drawPeaks.length === 0) return;

    const buckets = width;
    const scale = (height / 2) * 0.9;

    function sampleAt(arr: PeakBucket[], idx: number, component: 0 | 1): number {
        const fi = (idx / buckets) * (arr.length - 1);
        const lo = Math.floor(fi);
        const hi = Math.min(lo + 1, arr.length - 1);
        const t = fi - lo;
        return (arr[lo]?.[component] ?? 0) * (1 - t) + (arr[hi]?.[component] ?? 0) * t;
    }

    // Filled area (bottom + top envelope)
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(drawPeaks, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const x = (i / buckets) * width;
        const minVal = sampleAt(drawPeaks, i, 0);
        const y = centerY - minVal * scale;
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    // Top-envelope stroke
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(drawPeaks, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
}
