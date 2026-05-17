/**
 * Pure waveform drawing helper — no state, no side effects, no imports from
 * tab modules. Shared by all waveform canvas contexts.
 */

import type { PeakBucket } from '../types/domain';
import { WAVEFORM_BG_COLOR, WAVEFORM_FILL_COLOR, WAVEFORM_SILENCE_THRESHOLD, WAVEFORM_STROKE_COLOR } from './constants';

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

    ctx.fillStyle = WAVEFORM_BG_COLOR;
    ctx.fillRect(0, 0, width, height);

    if (!peaks || peaks.length === 0) return;

    // Apply sub-range slicing when all three range params are present.
    //
    // The slice's *actual* time span is wider than [startMs, endMs] by up
    // to one bucket per side because i0/i1 snap to integer indices
    // (floor/ceil). Pre-slim that was a 33 ms error (30 bps); post-slim
    // it's 100 ms per side (10 bps), which is visually obvious — a
    // ~150 ms silence in a 600 ms segment ends up drawn against the wrong
    // pixel column. Fix: drive the canvas-pixel → peak-index mapping from
    // the REQUESTED [startMs, endMs] window using the FULL peaks array's
    // density (peaks.length / totalDurationMs), translating into the
    // slice's local index space afterwards. The slice itself is still
    // cheap to compute because it scopes the maxAmp scan; the change is
    // purely in how pixels map to peak indices.
    let drawPeaks = peaks;
    let pixelToFullIdx: (x: number) => number;
    if (startMs !== undefined && endMs !== undefined && totalDurationMs !== undefined && totalDurationMs > 0) {
        const peaksPerMs = peaks.length / totalDurationMs;
        const i0 = Math.floor(startMs * peaksPerMs);
        const i1 = Math.ceil(endMs * peaksPerMs);
        drawPeaks = peaks.slice(i0, i1);
        // Map canvas x ∈ [0, width-1] linearly across [startMs, endMs] in
        // absolute time, then into a fractional index inside the slice.
        // No bucket snapping — each canvas pixel reads the peak at its
        // true time position.
        pixelToFullIdx = (x) => {
            const tMs = startMs + (x / Math.max(1, width - 1)) * (endMs - startMs);
            return tMs * peaksPerMs - i0;
        };
    } else {
        // Full-array render: legacy linear mapping over the whole peaks
        // array, identical to the pre-fix behaviour for non-sub-ranged
        // callers (chapter overviews etc.).
        pixelToFullIdx = (x) => (x / Math.max(1, width - 1)) * (peaks.length - 1);
    }

    if (drawPeaks.length === 0) return;

    const buckets = width;
    const halfH = height / 2;
    let maxAmp = 0;
    for (const bk of drawPeaks) {
        if (!bk) continue;
        const a = Math.max(Math.abs(bk[1] ?? 0), Math.abs(bk[0] ?? 0));
        if (a > maxAmp) maxAmp = a;
    }
    const scale = maxAmp < WAVEFORM_SILENCE_THRESHOLD ? halfH * 0.9 : halfH / maxAmp;

    function sampleAt(arr: PeakBucket[], idx: number, component: 0 | 1): number {
        const fi = pixelToFullIdx(idx);
        if (fi < 0) return arr[0]?.[component] ?? 0;
        if (fi >= arr.length - 1) return arr[arr.length - 1]?.[component] ?? 0;
        const lo = Math.floor(fi);
        const hi = lo + 1;
        const t = fi - lo;
        return (arr[lo]?.[component] ?? 0) * (1 - t) + (arr[hi]?.[component] ?? 0) * t;
    }

    // Build the closed top+bottom envelope once, then fill AND stroke it so
    // every consumer (playback, accordion, history, timestamps, edit modes)
    // gets the same look: translucent fill bordered by a 1px outline on
    // both the upper (max) and lower (min) envelopes.
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
    ctx.fillStyle = WAVEFORM_FILL_COLOR;
    ctx.fill();
    ctx.strokeStyle = WAVEFORM_STROKE_COLOR;
    ctx.lineWidth = 1;
    ctx.stroke();
}
