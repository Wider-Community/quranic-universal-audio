/**
 * Waveform canvas ad-hoc extension types for the Segments tab.
 *
 * The segments subsystem attaches edit/cache/highlight fields directly to
 * `HTMLCanvasElement` instances rather than maintaining a separate canvas→state
 * Map.  This file documents the expected surface so consumers can use a single
 * typed alias (`SegCanvas`) rather than casting to `any`.
 *
 * Keep this type-only — no logic belongs here.
 */

import type { Segment } from '../../../lib/types/domain';

/** Highlight descriptor for a trim-history card (red for removed, green for kept). */
export interface TrimHighlight {
    color: 'red' | 'green';
    otherStart: number;
    otherEnd: number;
}

/**
 * Highlight descriptor for a split-history after-card.
 *
 * `wfStart` / `wfEnd` are the waveform bounds (always set). `hlStart` / `hlEnd`
 * are the green highlight sub-range — optional because some canvas-scrub
 * callers only need the `wf*` bounds for seek-to-canvas routing.
 */
export interface SplitHighlight {
    wfStart: number;
    wfEnd: number;
    hlStart?: number;
    hlEnd?: number;
}

/** Highlight descriptor for a merge-history result card. */
export interface MergeHighlight {
    hlStart: number;
    hlEnd: number;
}

/** Edit-mode trim window snapshot (currentStart/End are mutable as user drags).
 *
 *  - `windowStart/windowEnd` — hard CLAMP bounds (from neighbors + trim padding).
 *    Cursors can never have an actual time outside this range.
 *  - `viewStart/viewEnd` — currently VISIBLE time range on the canvas (mouse-wheel
 *    zoom narrows this within `[windowStart, windowEnd]`). Drives all pixel↔time
 *    math (drag-mapping, hit-detection, peak slice, cursor + playhead x). When
 *    not zoomed: `viewStart === windowStart && viewEnd === windowEnd`.
 *    Reset on every `enterTrimMode` (not preserved across edit sessions).
 *  - When a cursor's actual time falls outside `[viewStart, viewEnd]`, it is
 *    visually clamped — strict per side: start to LEFT edge, end to RIGHT edge.
 */
export interface TrimWindow {
    windowStart: number;
    windowEnd: number;
    viewStart: number;
    viewEnd: number;
    currentStart: number;
    currentEnd: number;
    audioUrl: string;
}

/** Edit-mode split data.
 *
 *  - `seg.time_start`/`seg.time_end` are the absolute clamp bounds (cursor
 *    cannot leave the segment).
 *  - `viewStart/viewEnd` — currently VISIBLE time range on the canvas (mouse-
 *    wheel zoom narrows this within `[seg.time_start, seg.time_end]`). Drives
 *    pixel↔time math (drag, hit-detection, peak slice, cursor x). When not
 *    zoomed: `viewStart === seg.time_start && viewEnd === seg.time_end`.
 *    Reset on every `enterSplitMode` (not preserved across edit sessions).
 *  - When the split cursor's actual time falls outside `[viewStart, viewEnd]`,
 *    it is visually clamped to the canvas MIDDLE (not an edge — single cursor
 *    has no "side", and middle keeps both step directions productive: into-
 *    view from middle still lands on-canvas going either way).
 */
export interface SplitData {
    seg: Segment;
    currentSplit: number;
    viewStart: number;
    viewEnd: number;
    audioUrl: string;
}

// ---------------------------------------------------------------------------
// Edit-mode function signatures
// ---------------------------------------------------------------------------

export type EnterTrimModeFn = (seg: Segment, row: HTMLElement) => void;
export type EnterSplitModeFn = (
    seg: Segment,
    row: HTMLElement,
    prePausePlayMs?: number | null,
) => void;

/** Canvas-specific draw helpers re-invoked from the shared play-range loop. */
export type DrawWaveformFn = (canvas: SegCanvas) => void;

/** `HTMLCanvasElement` with the ad-hoc fields the segments waveform subsystem attaches. */
export interface SegCanvas extends HTMLCanvasElement {
    _wfCache?: ImageData | null;
    _wfCacheKey?: string;
    _trimHL?: TrimHighlight;
    _splitHL?: SplitHighlight;
    _mergeHL?: MergeHighlight;
    _trimWindow?: TrimWindow;
    _splitData?: SplitData;
    _trimBaseCache?: ImageData | null;
    _splitBaseCache?: ImageData | null;
    _editCleanup?: () => void;
}
