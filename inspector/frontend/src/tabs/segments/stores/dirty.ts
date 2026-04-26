/**
 * Segments tab — dirty state + operation log store.
 *
 * Tracks which chapters have unsaved edits (`segDirtyMap`), the per-chapter
 * operation log (`segOpLog`), and the current in-progress operation
 * (`pendingOp`). Provides helper functions for creating, snapshotting,
 * finalizing ops and marking/querying dirty state.
 *
 * Map keys are always `number` (never string-cast).
 *
 * `snapshotSeg` calls `_classifySegCategories` from
 * `lib/utils/segments/classify.ts`.
 */

import { derived, writable } from 'svelte/store';

import type { EditOp, Segment } from '../../../lib/types/domain';
import { _classifySegCategories } from '../utils/validation/classify';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Dirty-map entry — edited indices plus structural-change flag. */
export interface DirtyEntry {
    indices: Set<number>;
    structural: boolean;
}

/** Snapshot of a segment captured at op-start / op-end. Shape mirrors `Segment`
 *  with a few client-added flags (`index_at_save`, `categories`). Loose-typed
 *  so downstream history rendering doesn't have to cast every read. */
export type SegSnapshot = Record<string, unknown>;

export interface CreateOpOptions {
    contextCategory?: string | null;
    fixKind?: string;
}

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

/** Tracks which chapters have unsaved edits. Keys are ALWAYS `number`. */
const _dirtyMap = new Map<number, DirtyEntry>();

/** Per-chapter operation log. Keys are ALWAYS `number`. */
const _opLog = new Map<number, EditOp[]>();

/** Current in-progress operation (between createOp and finalizeOp). */
let _pendingOp: EditOp | null = null;

/** Reactive tick that bumps on every dirty-state mutation so Svelte
 *  components can derive reactive views (e.g. save-button enabled,
 *  per-row .dirty class). Subscribing components will re-run reactive
 *  blocks that read the dirty map after any mutation. */
export const dirtyTick = writable<number>(0);
function _bump(): void {
    dirtyTick.update((n) => n + 1);
}

/** Derived store: true while any chapter has unsaved edits. */
export const isDirtyStore = derived(dirtyTick, () => _dirtyMap.size > 0);

// ---------------------------------------------------------------------------
// Operation helpers
// ---------------------------------------------------------------------------

export function createOp(opType: string, { contextCategory = null, fixKind = 'manual' }: CreateOpOptions = {}): EditOp {
    return {
        op_id: crypto.randomUUID(),
        op_type: opType,
        op_context_category: contextCategory,
        fix_kind: fixKind,
        started_at_utc: new Date().toISOString(),
        applied_at_utc: null,
        ready_at_utc: null,
        targets_before: [],
        targets_after: [],
    };
}

export function snapshotSeg(seg: Segment): SegSnapshot {
    const snap: SegSnapshot = {
        segment_uid: seg.segment_uid || null,
        index_at_save: seg.index,
        audio_url: seg.audio_url || null,
        time_start: seg.time_start,
        time_end: seg.time_end,
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        display_text: seg.display_text || '',
        confidence: seg.confidence ?? 0,
    };
    if (seg.has_repeated_words) snap.has_repeated_words = true;
    if (seg.wrap_word_ranges) snap.wrap_word_ranges = seg.wrap_word_ranges;
    if (seg.phonemes_asr) snap.phonemes_asr = seg.phonemes_asr;
    if (seg.entry_ref) snap.entry_ref = seg.entry_ref;
    if (seg.chapter != null) snap.chapter = seg.chapter;
    if (seg.ignored_categories?.length) snap.ignored_categories = [...seg.ignored_categories];
    snap.categories = _classifySegCategories(seg);
    return snap;
}

export function finalizeOp(chapter: number, op: EditOp): void {
    op.ready_at_utc = new Date().toISOString();
    if (!_opLog.has(chapter)) _opLog.set(chapter, []);
    _opLog.get(chapter)!.push(op);
    _pendingOp = null;
}

// ---------------------------------------------------------------------------
// Dirty-state helpers
// ---------------------------------------------------------------------------

/**
 * Mark a chapter as dirty (has unsaved edits).
 *
 * When `structural=true` the `indices` set becomes advisory only — save takes
 * the full-replace path for that chapter, so specific edited indices stop
 * being load-bearing once any structural op has landed in the batch.
 *
 * @param chapter - chapter number (MUST be number, not string)
 * @param index - optional segment index to mark as edited
 * @param structural - whether this is a structural change (split/merge/delete)
 */
export function markDirty(chapter: number, index?: number, structural = false): void {
    if (!_dirtyMap.has(chapter)) {
        _dirtyMap.set(chapter, { indices: new Set(), structural: false });
    }
    const entry = _dirtyMap.get(chapter)!;
    if (index !== undefined) entry.indices.add(index);
    if (structural) entry.structural = true;
    _bump();
}

export function unmarkDirty(chapter: number, index: number): void {
    const entry = _dirtyMap.get(chapter);
    if (!entry) return;
    entry.indices.delete(index);
    if (entry.indices.size === 0 && !entry.structural) {
        _dirtyMap.delete(chapter);
    }
    _bump();
}

export function isDirty(): boolean {
    return _dirtyMap.size > 0;
}

export function isIndexDirty(chapter: number, index: number): boolean {
    const entry = _dirtyMap.get(chapter);
    return entry ? entry.indices.has(index) : false;
}

/** Whether the given segment (chapter, index) currently has unsaved edits.
 *  Pair with `$dirtyTick` in reactive `$:` blocks so the derivation fires
 *  after mutations. */
export function isSegmentDirty(chapter: number, index: number): boolean {
    return isIndexDirty(chapter, index);
}

/** Readonly snapshot of a chapter's op log for display/inspection callers that
 *  must not mutate the underlying array. Internal writers use getChapterOps. */
export function getChapterOpsSnapshot(chapter: number): readonly EditOp[] {
    return _opLog.get(chapter) ?? [];
}

// ---------------------------------------------------------------------------
// Pending op accessors
// ---------------------------------------------------------------------------

export function getPendingOp(): EditOp | null {
    return _pendingOp;
}

export function setPendingOp(op: EditOp | null): void {
    _pendingOp = op;
}

// ---------------------------------------------------------------------------
// Map accessors (read-only views + mutation)
// ---------------------------------------------------------------------------

/** Read-only reference to the dirty map. Callers should not mutate directly
 *  except via the provided helpers (markDirty/unmarkDirty/clearDirtyMap). */
export function getDirtyMap(): Map<number, DirtyEntry> {
    return _dirtyMap;
}

/** Read-only reference to the op log. */
export function getOpLog(): Map<number, EditOp[]> {
    return _opLog;
}

/** Get ops for a specific chapter. */
export function getChapterOps(chapter: number): EditOp[] {
    return _opLog.get(chapter) || [];
}

/** Delete dirty entry for a chapter. */
export function deleteDirtyEntry(chapter: number): void {
    _dirtyMap.delete(chapter);
    _bump();
}

/** Delete op log for a chapter. */
export function deleteOpLogEntry(chapter: number): void {
    _opLog.delete(chapter);
}

/** Clear all dirty state (after successful save). */
export function clearDirtyMap(): void {
    _dirtyMap.clear();
    _bump();
}

/** Clear all op log entries (after successful save). */
export function clearOpLog(): void {
    _opLog.clear();
}
