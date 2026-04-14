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

/** Edit modes supported by the Segments tab. Extended in Wave 7b with
 *  'merge' | 'delete' | 'reference' once those panels land. */
export type SegEditMode = 'trim' | 'split' | null;

/** Active edit mode for the segments tab. `null` = no edit in progress. */
export const editMode = writable<SegEditMode>(null);

/** UID of the segment currently being edited. `null` = no edit in progress.
 *  Stored as the segment's UID rather than its index so split-induced
 *  reindexing doesn't lose track of the row mid-flow. */
export const editingSegUid = writable<string | null>(null);

/** Reset the edit store to the "no edit in progress" baseline. Called by
 *  exitEditMode() / cancel paths. */
export function clearEdit(): void {
    editMode.set(null);
    editingSegUid.set(null);
}

/** Convenience setter — call when entering trim or split mode. */
export function setEdit(mode: Exclude<SegEditMode, null>, segUid: string | null): void {
    editMode.set(mode);
    editingSegUid.set(segUid);
}
