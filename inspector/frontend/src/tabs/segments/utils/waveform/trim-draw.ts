/**
 * Canvas drawing functions for trim mode — the waveform base cache,
 * dimmed regions, and drag handles.
 *
 * Reads `segConfig.trimDimAlpha` for the dimming overlay alpha.
 */

import { get } from 'svelte/store';

import { segConfig } from '../../stores/config';
import type { SegCanvas } from '../../types/segments-waveform';
import { WAVEFORM_STROKE_COLOR } from '../../../../lib/utils/constants';
import { drawEditPeakBase } from './draw-seg';

// ---------------------------------------------------------------------------
// _ensureTrimBaseCache
// ---------------------------------------------------------------------------

export function _ensureTrimBaseCache(canvas: SegCanvas): boolean {
    if (canvas._trimBaseCache) return true;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const tw = canvas._trimWindow;
    if (!tw) return false;

    // Slice peaks for the VISIBLE window (viewStart/End), not the absolute
    // clamp window — wheel zoom rebuilds this cache after dropping the prior
    // ImageData via `_trimBaseCache = null`.
    const data = drawEditPeakBase(canvas, tw.audioUrl || '', tw.viewStart, tw.viewEnd);
    if (!data) return false;

    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const scale = (height / 2) * 0.9;

    // Trim strokes the full max+min outline (top and bottom) for a closed look.
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - (data.maxVals[i] ?? 0) * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - (data.minVals[i] ?? 0) * scale);
    }
    ctx.closePath();
    ctx.strokeStyle = WAVEFORM_STROKE_COLOR;
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

    // Pixel positions of the cursors in the VISIBLE window. Two flavors:
    //   - Raw  (sxRaw, exRaw): unclamped — can be < 0 or > width when the
    //     cursor's actual time is outside the visible window. Used for the
    //     dim regions so off-view trim ranges still produce correct dimming
    //     (e.g. trim-range entirely off-view → whole canvas dimmed).
    //   - Strict-clamped (startX, endX): start clips to LEFT edge (x=0),
    //     end clips to RIGHT edge (x=width). Used for the cursor lines so
    //     the user can grab + drag a clamped handle right at the canvas
    //     edge, regardless of which side of the view it actually fell off.
    const span = tw.viewEnd - tw.viewStart;
    const sxRaw = ((tw.currentStart - tw.viewStart) / span) * width;
    const exRaw = ((tw.currentEnd - tw.viewStart) / span) * width;
    const startOff = tw.currentStart < tw.viewStart || tw.currentStart > tw.viewEnd;
    const endOff   = tw.currentEnd   < tw.viewStart || tw.currentEnd   > tw.viewEnd;
    const startX = startOff ? 0     : sxRaw;
    const endX   = endOff   ? width : exRaw;

    const leftDimEnd    = Math.max(0, Math.min(width, sxRaw));
    const rightDimStart = Math.max(0, Math.min(width, exRaw));

    ctx.fillStyle = `rgba(0, 0, 0, ${get(segConfig).trimDimAlpha})`;
    ctx.fillRect(0, 0, leftDimEnd, height);
    ctx.fillRect(rightDimStart, 0, width - rightDimStart, height);

    ctx.strokeStyle = '#4caf50';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();

    ctx.strokeStyle = '#f44336';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(endX, 0);
    ctx.lineTo(endX, height);
    ctx.stroke();
}
