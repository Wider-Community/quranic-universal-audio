/**
 * Canvas drawing functions for trim mode — the waveform base cache,
 * dimmed regions, and drag handles.
 *
 * Extracted from segments/edit/trim.ts (Ph4a). Reads `state.TRIM_DIM_ALPHA`
 * for the dimming overlay alpha.
 */

import { state } from '../../../segments/state';
import { _slicePeaks } from '../../../segments/waveform/draw';
import type { SegCanvas } from '../../types/segments-waveform';

// ---------------------------------------------------------------------------
// _ensureTrimBaseCache
// ---------------------------------------------------------------------------

export function _ensureTrimBaseCache(canvas: SegCanvas): boolean {
    if (canvas._trimBaseCache) return true;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const tw = canvas._trimWindow;
    if (!tw) return false;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    const audioUrl = tw.audioUrl || '';
    const data = _slicePeaks(audioUrl, tw.windowStart, tw.windowEnd, width);
    if (!data) return false;

    const scale = height / 2 * 0.9;

    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - (data.maxVals[i] ?? 0) * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - (data.minVals[i] ?? 0) * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.stroke();

    canvas._trimBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

// ---------------------------------------------------------------------------
// drawTrimWaveform
// ---------------------------------------------------------------------------

export function drawTrimWaveform(canvas: SegCanvas): void {
    const c = canvas;
    if (!_ensureTrimBaseCache(c)) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const width = c.width;
    const height = c.height;
    const tw = c._trimWindow;
    if (!tw || !c._trimBaseCache) return;

    ctx.putImageData(c._trimBaseCache, 0, 0);

    const startX = ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;
    const endX = ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;

    ctx.fillStyle = `rgba(0, 0, 0, ${state.TRIM_DIM_ALPHA})`;
    ctx.fillRect(0, 0, startX, height);
    ctx.fillRect(endX, 0, width - endX, height);

    ctx.strokeStyle = '#4caf50';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();
    ctx.fillStyle = '#4caf50';
    ctx.fillRect(startX - 4, height / 2 - 10, 8, 20);

    ctx.strokeStyle = '#f44336';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(endX, 0);
    ctx.lineTo(endX, height);
    ctx.stroke();
    ctx.fillStyle = '#f44336';
    ctx.fillRect(endX - 4, height / 2 - 10, 8, 20);
}
