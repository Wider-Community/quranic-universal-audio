/**
 * Reference editing: beginRefEdit (store setter) + commitRefEdit (apply).
 *
 * The inline `<input>` is owned by `tabs/segments/edit/ReferenceEditor.svelte`,
 * which is conditionally mounted by SegmentRow in place of the `.seg-text-ref`
 * span when the row is the current reference-edit target. This module only
 * owns the store/pending-op transitions and the async commit path.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegResolveRefResponse } from '../../../../lib/types/api';
import type { EditOp, Segment } from '../../../../lib/types/domain';
import {
    refreshSegInStore,
    selectedChapter,
} from '../../stores/chapter';
import {
    createOp,
    getPendingOp,
    markDirty,
    setPendingOp,
    snapshotSeg,
} from '../../stores/dirty';
import { clearEdit, setEdit } from '../../stores/edit';
import {
    continuousPlay,
    segAudioElement,
} from '../../stores/playback';
import { _normalizeRef as _normalizeRefLib, getVerseWordCounts } from '../data/references';
import { stopSegAnimation } from '../playback/playback';
import { finalizeEdit } from './common';

function _normalizeRef(ref: Parameters<typeof _normalizeRefLib>[0]): ReturnType<typeof _normalizeRefLib> {
    return _normalizeRefLib(ref, getVerseWordCounts());
}

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

/**
 * Shared tail for both commitRefEdit branches: append the op-context category
 * to ignored_categories (except muqattaat which tracks confidence instead),
 * clear derived cache, mark dirty, re-publish the seg to the store, and
 * finalize the pending op.
 */
function _applyRefChange(seg: Segment, pending: EditOp | null, chapter: number): void {
    const ctxCat = pending?.op_context_category;
    if (ctxCat && ctxCat !== 'muqattaat') {
        if (!seg.ignored_categories) seg.ignored_categories = [];
        if (!seg.ignored_categories.includes(ctxCat))
            seg.ignored_categories.push(ctxCat);
    }
    delete seg._derived;
    markDirty(chapter, seg.index);
    refreshSegInStore(seg);
    if (pending) {
        finalizeEdit(pending, chapter, [seg], '', {
            skipSilence: true,
            skipFilterRender: true,
            skipAccordion: true,
            skipStatus: true,
        });
    }
}

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
            _applyRefChange(seg, pending, chapter);
        } else {
            setPendingOp(null);
        }
        clearEdit();
        return;
    }

    seg.matched_ref = newRef;
    seg.confidence = 1.0;
    const pending = getPendingOp();

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

    _applyRefChange(seg, pending, chapter);
    clearEdit();
}
