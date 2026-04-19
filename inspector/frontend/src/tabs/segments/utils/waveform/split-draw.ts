/**
 * Canvas drawing functions for split mode — the waveform base cache,
 * split line, and right-region tinting.
 */

import type { SegCanvas } from '../../types/segments-waveform';
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
    const seg = sd.seg;
    const width = canvas.width;
    const height = canvas.height;

    const data = drawEditPeakBase(canvas, sd.audioUrl || '', seg.time_start, seg.time_end);
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
    ctx.strokeStyle = '#4361ee';
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
    const seg = sd.seg;

    if (hasCachedBase && c._splitBaseCache) ctx.putImageData(c._splitBaseCache, 0, 0);

    const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * width;

    ctx.fillStyle = 'rgba(255, 152, 0, 0.15)';
    ctx.fillRect(splitX, 0, width - splitX, height);

    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(splitX, 0);
    ctx.lineTo(splitX, height);
    ctx.stroke();
    ctx.fillStyle = '#ffeb3b';
    ctx.beginPath();
    ctx.moveTo(splitX - 6, 0);
    ctx.lineTo(splitX + 6, 0);
    ctx.lineTo(splitX, 8);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(splitX - 6, height);
    ctx.lineTo(splitX + 6, height);
    ctx.lineTo(splitX, height - 8);
    ctx.closePath();
    ctx.fill();
}
