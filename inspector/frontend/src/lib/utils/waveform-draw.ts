/**
 * Pure waveform drawing helper — no state, no side effects, no imports from
 * tab modules. Used by both the legacy segments/waveform/draw.ts (Stage 1)
 * and the new lib/components/WaveformCanvas.svelte (Stage 2 Wave 3+).
 */

import type { PeakBucket } from '../../types/domain';

/**
 * Draw a peak-based waveform onto the given canvas context.
 *
 * @param ctx    - 2D canvas rendering context (canvas must be sized already)
 * @param peaks  - Array of [min, max] amplitude buckets (values in [-1, 1])
 * @param width  - Canvas width in pixels
 * @param height - Canvas height in pixels
 */
export function drawWaveformPeaks(
    ctx: CanvasRenderingContext2D,
    peaks: PeakBucket[],
    width: number,
    height: number,
): void {
    const centerY = height / 2;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    if (!peaks || peaks.length === 0) return;

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
        const maxVal = sampleAt(peaks, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const x = (i / buckets) * width;
        const minVal = sampleAt(peaks, i, 0);
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
        const maxVal = sampleAt(peaks, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
}
