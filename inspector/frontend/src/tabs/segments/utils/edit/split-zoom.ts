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
import { segPort } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import {
    SPLIT_ZOOM_ANIMATE_MAX_MS,
    SPLIT_ZOOM_ANIMATE_MIN_MS,
    SPLIT_ZOOM_ANIMATE_MS_PER_SEC,
    SPLIT_ZOOM_PAD_FRACTION,
    TRIM_MIN_VIEW_MS,
    TRIM_WHEEL_ZOOM_FACTOR,
} from '../constants';
import { drawSplitWaveform } from '../waveform/split-draw';

export function applySplitWheelZoom(
    canvas: SegCanvas,
    mouseClientX: number,
    deltaY: number,
): void {
    const sd = canvas._splitData;
    if (!sd) return;
    // Manual wheel zoom wins — kill any in-flight region auto-zoom so the two
    // don't fight over `viewStart/viewEnd`.
    cancelSplitZoom();

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

// ---------------------------------------------------------------------------
// Region auto-zoom — animated pan/zoom to frame the selected split region
// ---------------------------------------------------------------------------
//
// Mirrors the timestamps-tab loop zoom: selecting a region pill (multi-cursor
// auto-split only) sweeps the view window to frame that region with padding.
// Unlike the TS tab (which animates a reactive `tsZoom` store feeding a
// WaveformCanvas), split mode mutates `_splitData.viewStart/viewEnd` in place
// and the preview-loop rAF (`animatePlayhead`) already re-reads those bounds +
// redraws every frame — so the tween only has to update state + null the peak
// cache, and rendering comes for free while a preview is playing.

interface ViewWindow { viewStart: number; viewEnd: number; }

/** Ease-in-out-quad — accelerate then decelerate (mirrors the timestamps
 *  tab's `_easeInOutQuad`). Gives a "reel through the waveform" sweep rather
 *  than a front-loaded teleport. */
function easeInOutQuad(x: number): number {
    return x < 0.5 ? 2 * x * x : 1 - ((-2 * x + 2) ** 2) / 2;
}

/**
 * Pure: the view window that frames region `[regionStart, regionEnd]` with
 * `SPLIT_ZOOM_PAD_FRACTION` of the region's duration as padding on each side,
 * each side clamped INDEPENDENTLY to `[segStart, segEnd]` (an edge region
 * keeps the full padding on its non-clamped side). If the padded + clamped
 * window would span (nearly) the whole segment, returns the full segment
 * window — selecting such a region animates back to fully-zoomed-out instead
 * of a no-op zoom.
 */
export function computeRegionView(
    regionStart: number,
    regionEnd: number,
    segStart: number,
    segEnd: number,
): ViewWindow {
    const full: ViewWindow = { viewStart: segStart, viewEnd: segEnd };
    if (segEnd <= segStart || regionEnd <= regionStart) return full;
    const pad = (regionEnd - regionStart) * SPLIT_ZOOM_PAD_FRACTION;
    const viewStart = Math.max(segStart, regionStart - pad);
    const viewEnd = Math.min(segEnd, regionEnd + pad);
    if (viewEnd <= viewStart) return full;
    if (viewEnd - viewStart >= (segEnd - segStart) - 1) return full;
    return { viewStart, viewEnd };
}

/** Duration (ms) for the sweep between two view windows — scales linearly with
 *  center-to-center travel and clamps to [MIN, MAX]. */
export function computeSweepDurationMs(from: ViewWindow, to: ViewWindow): number {
    const fromCenter = (from.viewStart + from.viewEnd) / 2;
    const toCenter = (to.viewStart + to.viewEnd) / 2;
    const distSec = Math.abs(toCenter - fromCenter) / 1000;
    const scaled = SPLIT_ZOOM_ANIMATE_MIN_MS + distSec * SPLIT_ZOOM_ANIMATE_MS_PER_SEC;
    return Math.min(SPLIT_ZOOM_ANIMATE_MAX_MS, Math.max(SPLIT_ZOOM_ANIMATE_MIN_MS, scaled));
}

let _zoomRAF: number | null = null;

/** Cancel any in-flight region zoom animation. Called when the user takes
 *  manual control (wheel zoom), starts a new region zoom, or exits edit mode. */
export function cancelSplitZoom(): void {
    if (_zoomRAF !== null) { cancelAnimationFrame(_zoomRAF); _zoomRAF = null; }
}

/** Commit a view window to `_splitData` + invalidate the peak cache. Draws
 *  ONLY when playback is paused — while a preview loop runs, its rAF
 *  (`animatePlayhead`) redraws every frame reading these bounds live, so a
 *  second draw here would erase + re-paint the playhead (flicker). When paused
 *  (incl. the brief post-seek gap) the playback loop early-returns without
 *  drawing, so the tween must draw the frame itself. */
function _commitView(canvas: SegCanvas, viewStart: number, viewEnd: number): void {
    const sd = canvas._splitData;
    if (!sd) return;
    sd.viewStart = viewStart;
    sd.viewEnd = viewEnd;
    canvas._splitBaseCache = null;
    if (segPort.paused) drawSplitWaveform(canvas);
}

/**
 * Animate the split view window from its current bounds to `target` over
 * `durationMs`, easing both edges (combined pan + zoom). Mutates
 * `_splitData.viewStart/viewEnd` + nulls `_splitBaseCache` each frame; the
 * running preview-loop rAF renders the interpolation (or `_commitView` draws
 * directly when paused). Syncs the `splitState` store once on completion.
 * A zero/sub-threshold move (e.g. replaying the already-framed region)
 * snaps to the exact target with no animation.
 */
export function animateSplitZoomTo(canvas: SegCanvas, target: ViewWindow, durationMs: number): void {
    cancelSplitZoom();
    const sd = canvas._splitData;
    if (!sd) return;
    const fromStart = sd.viewStart;
    const fromEnd = sd.viewEnd;
    const { viewStart: toStart, viewEnd: toEnd } = target;

    const finalize = (): void => {
        _commitView(canvas, toStart, toEnd);
        updateSplitState((s) => s ? { ...s, viewStart: toStart, viewEnd: toEnd } : s);
        _zoomRAF = null;
    };

    const EPS = 0.5; // ms — sub-frame moves aren't worth animating.
    if (durationMs <= 0
        || (Math.abs(fromStart - toStart) < EPS && Math.abs(fromEnd - toEnd) < EPS)) {
        finalize();
        return;
    }

    const startTs = performance.now();
    const step = (now: number): void => {
        const t = Math.min(1, (now - startTs) / durationMs);
        if (t >= 1) { finalize(); return; }
        const e = easeInOutQuad(t);
        _commitView(canvas, fromStart + (toStart - fromStart) * e, fromEnd + (toEnd - fromEnd) * e);
        _zoomRAF = requestAnimationFrame(step);
    };
    _zoomRAF = requestAnimationFrame(step);
}
