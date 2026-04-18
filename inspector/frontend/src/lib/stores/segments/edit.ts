/**
 * Segments tab — edit mode store.
 *
 * Tracks the currently-active edit mode (trim or split) and the segment
 * being edited (by uid). Drag state stays component-local (per Wave 4 pattern
 * note #3 — transient UI state via plain `let`); per-frame canvas overlay
 * state lives on the SegCanvas extension fields (per pattern note #4 — no
 * DOM-element caches in stores).
 *
 * The store is intentionally thin: trim/split panels write `mode` +
 * `editingSegUid` here so the SegmentsList `{#each}` can reactively style
 * the active row (e.g. `class:seg-edit-target` slot) without imperative
 * `classList` pokes. Today the actual `seg-edit-target` class is still
 * applied imperatively by `enterTrimMode`/`enterSplitMode` for parity with
 * Stage-1; future Wave-7 refinements can drop that imperative line once
 * the panels render exclusively via the store.
 *
 * Wave 7a.2 status (2026-04-14): wired from enterTrimMode / enterSplitMode
 * (setEdit) and exitEditMode / clearSegDisplay / clearPerReciterState
 * (clearEdit). EditOverlay.svelte subscribes to `editMode`.
 *
 * Wave 7b status (2026-04-14): union extended to 'merge' | 'delete' |
 * 'reference'. setEdit wired in mergeAdjacent / deleteSegment /
 * startRefEdit + commitRefEdit cleanup paths. MergePanel / DeletePanel /
 * ReferenceEditor shells landed; EditOverlay extended with new branches.
 * Merge/delete are one-shot (instant) operations — backdrop omitted for
 * those modes. Reference editing is inline — backdrop also omitted.
 *
 * Wave 7b shape sufficiency: merge / delete / reference-edit each operate
 * on at most one primary segment resolvable by UID. Merge's target-adjacent
 * is derived at call time from segment index + direction ('prev' | 'next');
 * delete and reference take a single UID. The existing `editingSegUid:
 * string | null` shape covers all three — no `editingSegs: Segment[]`
 * extension needed. If Wave 7b surfaces a multi-select edit operation
 * (e.g. bulk ignore / bulk confidence-set), extend then.
 *
 * Provisional shape per S2-D11 (store granularity may evolve through Wave 9).
 */

import { writable } from 'svelte/store';

import type { AccordionOpCtx } from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';

/** Edit modes supported by the Segments tab. Wave 7b added 'merge' |
 *  'delete' | 'reference'. Note: merge + delete are one-shot (no backdrop);
 *  reference editing is inline (no backdrop). Only trim + split show the
 *  `.seg-edit-overlay` backdrop in EditOverlay.svelte. */
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

/** Reset the edit store to the "no edit in progress" baseline. Called by
 *  exitEditMode() / cancel paths. `editCanvas` is cleared separately by the
 *  row publishing it (reactive) — or proactively here as a safety net so a
 *  stale canvas ref never lingers after an exit. */
export function clearEdit(): void {
    editMode.set(null);
    editingSegUid.set(null);
    editingSegIndex.set(-1);
    editCanvas.set(null);
}

/** Convenience setter — call when entering any edit mode. */
export function setEdit(mode: Exclude<SegEditMode, null>, segUid: string | null): void {
    editMode.set(mode);
    editingSegUid.set(segUid);
}
