/**
 * Canvas drawing functions for split mode — the waveform base cache,
 * split line, and right-region tinting.
 */

import type { SegCanvas } from '../../types/segments-waveform';
import { WAVEFORM_STROKE_COLOR } from '../../../../lib/utils/constants';
import { drawEditPeakBase } from './draw-seg';

// ---------------------------------------------------------------------------
// _ensureSplitBaseCache
// ---------------------------------------------------------------------------

export function _ensureSplitBaseCache(canvas: SegCanvas): boolean {
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    if (canvas._splitBaseCache) return true;
    const sd = canvas._splitData;
    if (!sd) return false;
    const width = canvas.width;
    const height = canvas.height;

    // Slice peaks for the VISIBLE window (not the whole segment) — wheel zoom
    // rebuilds this cache after dropping the prior ImageData via
    // `_splitBaseCache = null`.
    const data = drawEditPeakBase(canvas, sd.audioUrl || '', sd.viewStart, sd.viewEnd);
    if (!data) {
        ctx.fillStyle = '#888';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No waveform data', width / 2, height / 2);
        return false;
    }

    const centerY = height / 2;
    const scale = (height / 2) * 0.9;

    // Split strokes only the top (max) outline for a thinner visual.
    ctx.strokeStyle = WAVEFORM_STROKE_COLOR;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - (data.maxVals[i] ?? 0) * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    ctx.stroke();

    canvas._splitBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

// ---------------------------------------------------------------------------
// drawSplitWaveform
// ---------------------------------------------------------------------------

export function drawSplitWaveform(canvas: SegCanvas): void {
    const c = canvas;
    const hasCachedBase = _ensureSplitBaseCache(c);
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const width = c.width;
    const height = c.height;
    const sd = c._splitData;
    if (!sd) return;

    if (hasCachedBase && c._splitBaseCache) ctx.putImageData(c._splitBaseCache, 0, 0);

    // Two flavors of x for the split cursor in the VISIBLE window:
    //   - Raw (sxRaw): can be < 0 or > width if `currentSplit` is outside the
    //     view (zoomed past the cursor). Used to compute the right-side tint
    //     so the orange shading correctly fills the canvas when the entire
    //     view is to the right or left of the actual split.
    //   - Visual (splitX): when the cursor is off-view, clamp to canvas
    //     MIDDLE so the user can still grab + drag it. Single cursor → no
    //     left/right "side" to clamp to like trim, and middle keeps both
    //     stepper directions productive (mid + delta lands in-view either way).
    const span = sd.viewEnd - sd.viewStart;
    const sxRaw = ((sd.currentSplit - sd.viewStart) / span) * width;
    const off = sd.currentSplit < sd.viewStart || sd.currentSplit > sd.viewEnd;
    const splitX = off ? width / 2 : sxRaw;

    // Tint the right-half region. Use raw x clamped to canvas so an off-view
    // split still paints correctly:
    //   - currentSplit > viewEnd  → sxRaw > width → tintStart = width → no tint
    //     (the entire view is BEFORE the split, so it's all left-half).
    //   - currentSplit < viewStart → sxRaw < 0  → tintStart = 0 → full canvas
    //     tinted (the entire view is AFTER the split, so it's all right-half).
    const tintStart = Math.max(0, Math.min(width, sxRaw));
    ctx.fillStyle = 'rgba(255, 152, 0, 0.15)';
    ctx.fillRect(tintStart, 0, width - tintStart, height);

    // Plain vertical line, same shape + thickness as the trim cursors
    // (green/red in trim-draw.ts). Kept yellow here so the single split
    // cursor stays visually distinct from the paired trim boundaries, but
    // the cap triangles were dropped to match the adjust-mode aesthetic.
    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(splitX, 0);
    ctx.lineTo(splitX, height);
    ctx.stroke();
}
