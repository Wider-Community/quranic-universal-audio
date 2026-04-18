/**
 * Segments tab — edit mode store.
 *
 * Tracks the currently-active edit mode and the segment being edited (by
 * UID). Drag state stays component-local (transient UI state via plain
 * `let`); per-frame canvas overlay state lives on the SegCanvas extension
 * fields (no DOM-element caches in stores).
 *
 * Modes:
 *   - 'trim'      — persistent drag (boundary handles); backdrop shown.
 *   - 'split'     — persistent drag (split handle); backdrop shown.
 *   - 'merge'     — one-shot async; no backdrop.
 *   - 'delete'    — one-shot async; no backdrop.
 *   - 'reference' — inline input on the row; no backdrop.
 *
 * The `.seg-edit-target` class is driven by SegmentRow reactively from
 * `editingSegUid === seg.segment_uid`; edit utilities never touch
 * `classList` directly.
 */

import { writable } from 'svelte/store';

import type { AccordionOpCtx } from '../../types/segments';
import type { SegCanvas, SplitData, TrimWindow } from '../../types/segments-waveform';

/** Edit modes supported by the Segments tab. Only trim + split show the
 *  `.seg-edit-overlay` backdrop in EditOverlay.svelte — merge/delete are
 *  one-shot and reference editing is inline on the row. */
export type SegEditMode = 'trim' | 'split' | 'merge' | 'delete' | 'reference' | null;

/** Active edit mode for the segments tab. `null` = no edit in progress. */
export const editMode = writable<SegEditMode>(null);

/** UID of the segment currently being edited. `null` = no edit in progress.
 *  Stored as the segment's UID rather than its index so split-induced
 *  reindexing doesn't lose track of the row mid-flow. */
export const editingSegUid = writable<string | null>(null);

/** Primary index (position in the displayed list) of the segment currently
 *  being edited. Written alongside `editingSegUid` in enter-edit flows. */
export const editingSegIndex = writable<number>(-1);

/** Active split chain UID — the parent segment UID a split chain points back
 *  to. Cleared when split completes / chain collapses. */
export const splitChainUid = writable<string | null>(null);

/** Active split chain category — error category context carried from the
 *  triggering error card. */
export const splitChainCategory = writable<string | null>(null);

/** Context captured at the row / prev / next button click site (error card
 *  accordion edit trigger). */
export const accordionOpCtx = writable<AccordionOpCtx | null>(null);

/** Canvas element of the segment row currently in edit mode. Published by
 *  SegmentRow.svelte when `$editingSegUid === seg.segment_uid`, cleared when
 *  the row stops being the edit target. Replaces the legacy `_getEditCanvas`
 *  DOM query (`document.querySelector('.seg-row.seg-edit-target canvas')`).
 *  Edit utilities (trim/split/play-range) read this to locate the canvas
 *  without a document-wide lookup. */
export const editCanvas = writable<SegCanvas | null>(null);

/** Trim-mode window state — mirror of `canvas._trimWindow` so TrimPanel.svelte
 *  can render the duration/handles reactively. Drag handlers write to both the
 *  canvas field (for the draw pipeline) and this store (for Svelte). `null` =
 *  not in trim mode. */
export const trimWindow = writable<TrimWindow | null>(null);

/** Split-mode state — mirror of `canvas._splitData` so SplitPanel.svelte can
 *  render the L/R duration reactively. `null` = not in split mode. */
export const splitState = writable<SplitData | null>(null);

/** Short status text shown in trim/split panels (e.g. 'Invalid time range',
 *  'Start overlaps with previous segment'). Cleared on panel mount. */
export const trimStatusText = writable<string>('');

/** Reset the edit store to the "no edit in progress" baseline. Called by
 *  exitEditMode() / cancel paths. `editCanvas` is cleared separately by the
 *  row publishing it (reactive) — or proactively here as a safety net so a
 *  stale canvas ref never lingers after an exit. */
export function clearEdit(): void {
    editMode.set(null);
    editingSegUid.set(null);
    editingSegIndex.set(-1);
    editCanvas.set(null);
    trimWindow.set(null);
    splitState.set(null);
    trimStatusText.set('');
}

/** Convenience setter — call when entering any edit mode. */
export function setEdit(mode: Exclude<SegEditMode, null>, segUid: string | null): void {
    editMode.set(mode);
    editingSegUid.set(segUid);
}
