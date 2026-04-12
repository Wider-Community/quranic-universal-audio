/**
 * Ad-hoc canvas extensions used by the segments waveform subsystem.
 *
 * The codebase attaches a handful of edit/cache/highlight fields directly to
 * `HTMLCanvasElement` instances instead of maintaining a separate canvas→state
 * Map. This file documents the expected surface so consumers can use a single
 * typed alias (`SegCanvas`) rather than casting or reaching for `any`.
 *
 * Keep this type-only — no logic belongs here.
 */

import type { Segment } from '../../types/domain';

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
 * are the green highlight sub-range — optional because error-card-audio only
 * cares about `wf*` for seek-to-canvas routing.
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

/** Edit-mode trim window snapshot (currentStart/End are mutable as user drags). */
export interface TrimWindow {
    windowStart: number;
    windowEnd: number;
    currentStart: number;
    currentEnd: number;
    audioUrl: string;
}

/** Edit-mode split data. */
export interface SplitData {
    seg: Segment;
    currentSplit: number;
    audioUrl: string;
}

/** DOM-ref holder attached to an active trim-mode canvas. */
export interface TrimEls {
    durationSpan: HTMLElement;
    statusSpan: HTMLElement;
}

/** DOM-ref holder attached to an active split-mode canvas. */
export interface SplitEls {
    infoSpan: HTMLElement;
}

/** `HTMLCanvasElement` with the ad-hoc fields this subsystem attaches. */
export interface SegCanvas extends HTMLCanvasElement {
    _wfCache?: ImageData | null;
    _wfCacheKey?: string;
    _trimHL?: TrimHighlight;
    _splitHL?: SplitHighlight;
    _mergeHL?: MergeHighlight;
    _trimWindow?: TrimWindow;
    _splitData?: SplitData;
    _trimEls?: TrimEls;
    _splitEls?: SplitEls;
    _trimBaseCache?: ImageData | null;
    _splitBaseCache?: ImageData | null;
    _editCleanup?: () => void;
}
