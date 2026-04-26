/**
 * Normalized segment state store (IS-7).
 *
 * ``SegmentState`` holds all loaded segments indexed by uid and ordered by
 * chapter, replacing the flat ``segments: Segment[]`` denormalized view.
 * Compat selectors (``getChapterSegments``, ``getSegByChapterIndex``,
 * ``getAdjacentSegments``, ``findByUid``) derive from this shape so that
 * the ~50 existing subscriber call sites need no changes.
 *
 * Write path: dispatchers call ``segmentsStore.update(...)`` after applying
 * a ``CommandResult.nextState`` slice.  The store never mutates segments
 * directly — it receives already-mutated clones from ``applyCommand``.
 */

import { writable } from 'svelte/store';

import type { Segment } from '../../../lib/types/domain';

// ---------------------------------------------------------------------------
// State shape
// ---------------------------------------------------------------------------

export interface SegmentState {
    /** All segments keyed by ``segment_uid``. */
    byId: Record<string, Segment>;
    /** Ordered uid lists per chapter (preserves render order). */
    idsByChapter: Record<number, string[]>;
    /** Currently selected chapter number; ``null`` when none is selected. */
    selectedChapter: number | null;
}

const _emptyState: SegmentState = {
    byId: {},
    idsByChapter: {},
    selectedChapter: null,
};

export const segmentsStore = writable<SegmentState>({ ..._emptyState });

// ---------------------------------------------------------------------------
// Pure selectors (operate on a SegmentState value, not the store itself)
// ---------------------------------------------------------------------------

/** Return the ordered segment list for *chapter* resolved against ``byId``. */
export function getChapterSegments(state: SegmentState, chapter: number): Segment[] {
    const ids = state.idsByChapter[chapter];
    if (!ids) return [];
    return ids.map((id) => state.byId[id]).filter((s): s is Segment => s !== undefined);
}

/** Return the segment at *index* within *chapter*, or ``null``.
 *
 *  Resolution order:
 *  1. Find a segment where ``s.index === index`` (preferred: index is set).
 *  2. Fall back to positional lookup — the segment at position *index* in
 *     the ordered ``idsByChapter[chapter]`` list (for test fixtures that
 *     omit the ``index`` field). */
export function getSegByChapterIndex(
    state: SegmentState,
    chapter: number,
    index: number,
): Segment | null {
    const segs = getChapterSegments(state, chapter);
    const byField = segs.find((s) => s.index === index);
    if (byField !== undefined) return byField;
    return segs[index] ?? null;
}

export interface AdjacentSegments {
    prev: Segment | null;
    next: Segment | null;
}

/** Return the previous and next segments relative to *index* in *chapter*.
 *
 *  Finds the segment position by ``s.index`` field first; falls back to
 *  treating *index* as the positional offset in the ordered list. */
export function getAdjacentSegments(
    state: SegmentState,
    chapter: number,
    index: number,
): AdjacentSegments {
    const segs = getChapterSegments(state, chapter);
    let pos = segs.findIndex((s) => s.index === index);
    if (pos === -1) pos = index;
    return {
        prev: pos > 0 ? (segs[pos - 1] ?? null) : null,
        next: pos >= 0 && pos < segs.length - 1 ? (segs[pos + 1] ?? null) : null,
    };
}

/** Return the segment with the given uid, or ``null`` if not present. */
export function findByUid(state: SegmentState, uid: string): Segment | null {
    return state.byId[uid] ?? null;
}

// ---------------------------------------------------------------------------
// State mutators — apply a CommandNextState slice
// ---------------------------------------------------------------------------

import type { CommandNextState } from '../domain/command';

/** Apply a ``CommandNextState`` slice to the given ``SegmentState`` and return
 *  the next state.  Does not mutate the input. */
export function applyNextState(
    current: SegmentState,
    nextState: CommandNextState,
): SegmentState {
    const newById = { ...current.byId, ...nextState.byId };

    // Remove deleted segments
    if (nextState.removedSegmentUids?.length) {
        for (const uid of nextState.removedSegmentUids) {
            delete newById[uid];
        }
    }

    // If the command provided an updated idsByChapter mapping, use it;
    // otherwise rebuild only the affected chapter from newById.
    let newIdsByChapter: Record<number, string[]>;
    if (nextState.idsByChapter) {
        newIdsByChapter = { ...current.idsByChapter, ...nextState.idsByChapter };
    } else {
        newIdsByChapter = { ...current.idsByChapter };
        const ch = nextState.affectedChapter;
        const existing = current.idsByChapter[ch] ?? [];
        // Remove deleted uids; add newly inserted uids
        const removed = new Set(nextState.removedSegmentUids ?? []);
        const inserted = nextState.insertedSegmentUids ?? [];
        let chIds = existing.filter((u) => !removed.has(u) && newById[u] !== undefined);
        for (const uid of inserted) {
            if (!chIds.includes(uid)) {
                // Insert after the predecessor (the first key in nextState.byId
                // that is not itself an inserted uid)
                const predecessorUid = Object.keys(nextState.byId).find(
                    (u) => !inserted.includes(u),
                );
                if (predecessorUid) {
                    const ix = chIds.indexOf(predecessorUid);
                    if (ix !== -1) {
                        chIds.splice(ix + 1, 0, uid);
                    } else {
                        chIds.push(uid);
                    }
                } else {
                    chIds.push(uid);
                }
            }
        }
        // Re-sort by segment index in byId
        chIds = chIds.sort((a, b) => {
            const sa = newById[a];
            const sb = newById[b];
            return (sa?.index ?? 0) - (sb?.index ?? 0);
        });
        newIdsByChapter[ch] = chIds;
    }

    return {
        byId: newById,
        idsByChapter: newIdsByChapter,
        selectedChapter: current.selectedChapter,
    };
}
