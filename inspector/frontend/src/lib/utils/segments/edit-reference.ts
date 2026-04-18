/**
 * Reference editing: beginRefEdit (store setter) + commitRefEdit (apply).
 *
 * The inline `<input>` is owned by `tabs/segments/edit/ReferenceEditor.svelte`,
 * which is conditionally mounted by SegmentRow in place of the `.seg-text-ref`
 * span when the row is the current reference-edit target. This module only
 * owns the store/pending-op transitions and the async commit path.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../api';
import {
    refreshSegInStore,
    segAllData,
    segData,
    selectedChapter,
} from '../../stores/segments/chapter';
import {
    createOp,
    finalizeOp,
    getPendingOp,
    markDirty,
    setPendingOp,
    snapshotSeg,
} from '../../stores/segments/dirty';
import { clearEdit, setEdit } from '../../stores/segments/edit';
import {
    continuousPlay,
    segAudioElement,
} from '../../stores/segments/playback';
import type { SegResolveRefResponse } from '../../types/api';
import type { Segment } from '../../types/domain';
import { stopSegAnimation } from './playback';
import { _normalizeRef as _normalizeRefLib } from './references';

function _vwc() {
    return get(segAllData)?.verse_word_counts ?? get(segData)?.verse_word_counts;
}
function _normalizeRef(ref: Parameters<typeof _normalizeRefLib>[0]) { return _normalizeRefLib(ref, _vwc()); }

// ---------------------------------------------------------------------------
// beginRefEdit — enter reference-edit mode for a segment
// ---------------------------------------------------------------------------

/**
 * Enter reference-edit mode for `seg`. Pauses audio, creates the pending op,
 * and flips the edit store. SegmentRow reactively swaps the `.seg-text-ref`
 * span for a `<ReferenceEditor>` input once the store updates.
 */
export function beginRefEdit(seg: Segment, contextCategory: string | null = null): void {
    const audioEl = get(segAudioElement);
    if (audioEl && !audioEl.paused) { audioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    setEdit('reference', seg.segment_uid ?? null);

    const pending = createOp('edit_reference', contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);
}

// ---------------------------------------------------------------------------
// commitRefEdit — resolve reference and apply edit
// ---------------------------------------------------------------------------

export async function commitRefEdit(seg: Segment, newRefIn: string): Promise<void> {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const newRef = _normalizeRef(newRefIn) ?? '';
    if (newRef === oldRef) {
        if ((seg.confidence ?? 0) < 1.0) {
            const pending = getPendingOp();
            if (pending) {
                pending.op_type = 'confirm_reference';
                pending.fix_kind = 'audit';
            }
            seg.confidence = 1.0;
            const ctxCat = pending?.op_context_category;
            if (ctxCat) {
                if (ctxCat !== 'muqattaat') {
                    if (!seg.ignored_categories) seg.ignored_categories = [];
                    if (!seg.ignored_categories.includes(ctxCat))
                        seg.ignored_categories.push(ctxCat);
                }
            }
            delete seg._derived;
            markDirty(chapter, seg.index);
            refreshSegInStore(seg);
            if (pending) {
                pending.applied_at_utc = new Date().toISOString();
                pending.targets_after = [snapshotSeg(seg)];
                finalizeOp(chapter, pending);
            }
        } else {
            setPendingOp(null);
        }
        clearEdit();
        return;
    }

    seg.matched_ref = newRef;
    seg.confidence = 1.0;
    const pending = getPendingOp();
    const ctxCat = pending?.op_context_category;
    if (ctxCat) {
        if (ctxCat !== 'muqattaat') {
            if (!seg.ignored_categories) seg.ignored_categories = [];
            if (!seg.ignored_categories.includes(ctxCat))
                seg.ignored_categories.push(ctxCat);
        }
    }

    if (newRef) {
        try {
            const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`,
            );
            if (data.text) {
                seg.matched_text = data.text;
                seg.display_text = data.display_text || data.text;
            } else if (data.error) {
                console.warn('resolve_ref error:', data.error);
                seg.matched_text = '(invalid ref)';
                seg.display_text = '';
            }
        } catch (e) {
            console.error('Failed to resolve ref:', e);
            seg.matched_text = '(resolve failed)';
            seg.display_text = '';
        }
    } else {
        seg.matched_text = '';
        seg.display_text = '';
    }

    delete seg._derived;
    markDirty(chapter, seg.index);
    refreshSegInStore(seg);

    if (pending) {
        pending.applied_at_utc = new Date().toISOString();
        pending.targets_after = [snapshotSeg(seg)];
        finalizeOp(chapter, pending);
    }

    clearEdit();
}
