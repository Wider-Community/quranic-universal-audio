/**
 * Mouse-wheel zoom for the trim-mode canvas.
 *
 * Narrows / widens `_trimWindow.viewStart..viewEnd` (the visible time range)
 * within the hard `[windowStart, windowEnd]` clamp, centered on the time
 * currently under the mouse cursor (standard zoom-to-cursor: the time at
 * the mouse stays under the mouse after zoom).
 *
 * Bounds:
 *   - lower: TRIM_MIN_VIEW_MS — past this, further wheel-in is a no-op.
 *   - upper: windowEnd - windowStart — past this, further wheel-out is a no-op.
 *
 * Side effects per call:
 *   1. Mutates `canvas._trimWindow.viewStart` / `viewEnd` in place.
 *   2. Invalidates the peak-base ImageData cache so the next draw re-slices
 *      peaks for the new visible range.
 *   3. Mirrors `viewStart/End` into the `trimWindow` Svelte store so any
 *      view-aware reactive consumers (e.g. future overlays) see the change.
 *   4. Calls `drawTrimWaveform(canvas)` to repaint immediately.
 *
 * Drag-suppression is the caller's job — `setupTrimDragHandles` gates the
 * wheel listener with its local `dragging` flag so wheel events fired mid-
 * drag are silently dropped (req #8).
 *
 * Cursor visual clamping (when actual `currentStart/End` falls outside the
 * new visible window) is handled by `drawTrimWaveform` — this module only
 * mutates the view window.
 */

import { updateTrimWindow } from '../../stores/edit';
import type { SegCanvas } from '../../types/segments-waveform';
import { TRIM_MIN_VIEW_MS, TRIM_WHEEL_ZOOM_FACTOR } from '../constants';
import { drawTrimWaveform } from '../waveform/trim-draw';

export function applyWheelZoom(
    canvas: SegCanvas,
    mouseClientX: number,
    deltaY: number,
): void {
    const tw = canvas._trimWindow;
    if (!tw) return;

    const rect = canvas.getBoundingClientRect();
    const w = canvas.width;
    // Mouse x in canvas coords (account for CSS scaling).
    const mouseX = (mouseClientX - rect.left) * (w / rect.width);

    const totalRange = tw.windowEnd - tw.windowStart;
    const curRange = tw.viewEnd - tw.viewStart;
    // Negative deltaY = wheel-in (zoom in, narrow view); positive = wheel-out.
    const factor = deltaY < 0 ? TRIM_WHEEL_ZOOM_FACTOR : 1 / TRIM_WHEEL_ZOOM_FACTOR;
    let newRange = curRange * factor;
    newRange = Math.max(TRIM_MIN_VIEW_MS, Math.min(newRange, totalRange));
    if (newRange === curRange) return; // already at limit

    // Time under mouse stays under mouse: solve for newViewStart such that
    //   newViewStart + (mouseX/w) * newRange === currentTimeAtMouse
    const ratio = mouseX / w;
    const tAtMouse = tw.viewStart + ratio * curRange;
    let newViewStart = tAtMouse - ratio * newRange;
    let newViewEnd = newViewStart + newRange;

    // Clamp to absolute clamp window, preserving width — slide rather than
    // squash so center-locked-zoom near an edge still reaches min/max width.
    if (newViewStart < tw.windowStart) {
        newViewStart = tw.windowStart;
        newViewEnd = newViewStart + newRange;
    }
    if (newViewEnd > tw.windowEnd) {
        newViewEnd = tw.windowEnd;
        newViewStart = newViewEnd - newRange;
    }

    tw.viewStart = newViewStart;
    tw.viewEnd = newViewEnd;
    // Peak slice depends on view bounds — drop the cached ImageData so
    // _ensureTrimBaseCache rebuilds from the new range on next draw.
    canvas._trimBaseCache = null;
    updateTrimWindow((w0) => w0 ? { ...w0, viewStart: newViewStart, viewEnd: newViewEnd } : w0);
    drawTrimWaveform(canvas);
}
