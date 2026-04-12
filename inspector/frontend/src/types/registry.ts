/**
 * Registration-pattern signatures for the segments tab.
 *
 * The segments tab breaks circular dependencies between event-delegation /
 * keyboard / edit-common and the concrete edit/save/undo/error-card modules
 * by having the concrete modules `register*(…)` their entry points at
 * import time. These types document the contract of what gets registered.
 *
 * Phase 6 convention: type-only — no runtime redesign, matching the existing
 * "Phase 2 registration pattern". Stage 2 (Svelte) will re-evaluate.
 */

import type { Segment } from './domain';
import type { SegCanvas } from '../segments/waveform/types';

// ---------------------------------------------------------------------------
// event-delegation.ts — clicks on segment rows / canvas / buttons
// ---------------------------------------------------------------------------

/** `playErrorCardAudio(seg, playBtn, seekToMs?)`. */
export type PlayErrorCardAudioFn = (
    seg: Segment,
    playBtn: HTMLElement,
    seekToMs?: number,
) => void;

/** `startRefEdit(refSpan, seg, row, contextCategory?)`. */
export type StartRefEditFn = (
    refSpan: HTMLElement,
    seg: Segment,
    row: HTMLElement,
    contextCategory?: string | null,
) => void;

/** `enterEditWithBuffer(seg, row, mode, contextCategory?)`. */
export type EnterEditWithBufferFn = (
    seg: Segment,
    row: HTMLElement,
    mode: 'trim' | 'split',
    contextCategory?: string | null,
) => void;

/** `mergeAdjacent(seg, direction, contextCategory?)`. */
export type MergeAdjacentFn = (
    seg: Segment,
    direction: 'prev' | 'next',
    contextCategory?: string | null,
) => void | Promise<void>;

/** `deleteSegment(seg, row, contextCategory?)`. */
export type DeleteSegmentFn = (
    seg: Segment,
    row: HTMLElement,
    contextCategory?: string | null,
) => void;

/** Shape of the event-delegation registry keyed by handler name. */
export interface SegEventHandlerRegistry {
    playErrorCardAudio?: PlayErrorCardAudioFn;
    startRefEdit?: StartRefEditFn;
    enterEditWithBuffer?: EnterEditWithBufferFn;
    mergeAdjacent?: MergeAdjacentFn;
    deleteSegment?: DeleteSegmentFn;
    /** Accordion "context shown" helpers — registered from segments/index.ts
     *  for symmetry with the other accordion/edit entry points. Currently
     *  unused by the event-delegation module itself but read by validation
     *  error-cards via the registry — keep the slot wired. */
    ensureContextShown?: (row: Element) => void;
    _isWrapperContextShown?: (wrapper: Element | null | undefined) => boolean;
}

/** Union of valid handler names. */
export type SegEventHandlerName = keyof SegEventHandlerRegistry;

// ---------------------------------------------------------------------------
// keyboard.ts — Ctrl+S save, Escape exit, Enter confirm
// ---------------------------------------------------------------------------

export type OnSegSaveClickFn = () => void;
export type HideSavePreviewFn = () => void;
export type ConfirmSaveFromPreviewFn = () => void;
export type ExitEditModeFn = () => void;
export type ConfirmTrimFn = (seg: Segment) => void;
export type ConfirmSplitFn = (seg: Segment) => void | Promise<void>;

export interface SegKeyboardHandlerRegistry {
    onSegSaveClick?: OnSegSaveClickFn;
    hideSavePreview?: HideSavePreviewFn;
    confirmSaveFromPreview?: ConfirmSaveFromPreviewFn;
    exitEditMode?: ExitEditModeFn;
    confirmTrim?: ConfirmTrimFn;
    confirmSplit?: ConfirmSplitFn;
    startRefEdit?: StartRefEditFn;
}

export type SegKeyboardHandlerName = keyof SegKeyboardHandlerRegistry;

// ---------------------------------------------------------------------------
// edit/common.ts — trim/split mode entry + waveform redraw
// ---------------------------------------------------------------------------

export type EnterTrimModeFn = (seg: Segment, row: HTMLElement) => void;
export type EnterSplitModeFn = (
    seg: Segment,
    row: HTMLElement,
    prePausePlayMs?: number | null,
) => void;

/** Canvas-specific draw helpers re-invoked from the shared play-range loop.
 *  Narrowed to `SegCanvas` because every producer + consumer attaches/reads
 *  the `_trimWindow` / `_splitData` / `_*HL` fields — a plain
 *  `HTMLCanvasElement` without those fields would silently compile but
 *  fail at runtime. */
export type DrawWaveformFn = (canvas: SegCanvas) => void;
