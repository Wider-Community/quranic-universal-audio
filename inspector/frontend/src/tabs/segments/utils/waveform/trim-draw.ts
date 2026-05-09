/**
 * Canvas drawing functions for trim mode — the waveform base cache,
 * dimmed regions, and drag handles.
 *
 * Reads `segConfig.trimDimAlpha` for the dimming overlay alpha.
 */

import { get } from 'svelte/store';

import { segConfig } from '../../stores/config';
import type { SegCanvas } from '../../types/segments-waveform';
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
    // ImageData via `_trimBaseCache = null`. drawEditPeakBase paints the
    // shared bg + fill + top/bottom outline; we just snapshot it.
    if (!drawEditPeakBase(canvas, tw.audioUrl || '', tw.viewStart, tw.viewEnd)) return false;

    canvas._trimBaseCache = ctx.getImageData(0, 0, canvas.width, canvas.height);
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
