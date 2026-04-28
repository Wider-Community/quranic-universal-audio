/**
 * Mouse-wheel zoom for the split-mode canvas.
 *
 * Narrows / widens `_splitData.viewStart..viewEnd` (the visible time range)
 * within the absolute `[seg.time_start, seg.time_end]` clamp, centered on the
 * time currently under the mouse cursor (standard zoom-to-cursor: the time at
 * the mouse stays under the mouse after zoom).
 *
 * Bounds:
 *   - lower: TRIM_MIN_VIEW_MS (shared with trim — same UX rationale).
 *   - upper: seg.time_end - seg.time_start.
 *
 * Side effects per call:
 *   1. Mutates `canvas._splitData.viewStart` / `viewEnd` in place.
 *   2. Invalidates the peak-base ImageData cache so the next draw re-slices
 *      peaks for the new visible range.
 *   3. Mirrors `viewStart/End` into the `splitState` Svelte store so any
 *      view-aware reactive consumers see the change.
 *   4. Calls `drawSplitWaveform(canvas)` to repaint immediately.
 *
 * Drag-suppression is the caller's job — `setupSplitDragHandle` gates the
 * wheel listener with its local `dragging` flag so wheel events fired mid-
 * drag are silently dropped.
 *
 * Cursor visual clamping (when `currentSplit` falls outside the new visible
 * window) is handled by `drawSplitWaveform` — split clamps to MIDDLE rather
 * than an edge so both stepper directions remain useful (mid + delta lands
 * in-view going either way).
 */

import { updateSplitState } from '../../stores/edit';
import type { SegCanvas } from '../../types/segments-waveform';
import { TRIM_MIN_VIEW_MS, TRIM_WHEEL_ZOOM_FACTOR } from '../constants';
import { drawSplitWaveform } from '../waveform/split-draw';

export function applySplitWheelZoom(
    canvas: SegCanvas,
    mouseClientX: number,
    deltaY: number,
): void {
    const sd = canvas._splitData;
    if (!sd) return;

    const rect = canvas.getBoundingClientRect();
    const w = canvas.width;
    const mouseX = (mouseClientX - rect.left) * (w / rect.width);

    const absStart = sd.seg.time_start;
    const absEnd   = sd.seg.time_end;
    const totalRange = absEnd - absStart;
    const curRange = sd.viewEnd - sd.viewStart;
    const factor = deltaY < 0 ? TRIM_WHEEL_ZOOM_FACTOR : 1 / TRIM_WHEEL_ZOOM_FACTOR;
    let newRange = curRange * factor;
    newRange = Math.max(TRIM_MIN_VIEW_MS, Math.min(newRange, totalRange));
    if (newRange === curRange) return;

    const ratio = mouseX / w;
    const tAtMouse = sd.viewStart + ratio * curRange;
    let newViewStart = tAtMouse - ratio * newRange;
    let newViewEnd = newViewStart + newRange;

    if (newViewStart < absStart) {
        newViewStart = absStart;
        newViewEnd = newViewStart + newRange;
    }
    if (newViewEnd > absEnd) {
        newViewEnd = absEnd;
        newViewStart = newViewEnd - newRange;
    }

    sd.viewStart = newViewStart;
    sd.viewEnd = newViewEnd;
    canvas._splitBaseCache = null;
    updateSplitState((s) => s ? { ...s, viewStart: newViewStart, viewEnd: newViewEnd } : s);
    drawSplitWaveform(canvas);
}
