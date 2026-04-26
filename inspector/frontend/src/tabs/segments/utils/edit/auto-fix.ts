/**
 * Auto-fix dispatcher for the missing-words card.
 *
 * Wraps `applyCommand({type: 'autoFixMissingWord', ...})` and the live-store
 * glue. Resolves the new ref's matched_text via `/api/seg/resolve_ref`,
 * dispatches the command, applies the mutation to the live segment, marks
 * dirty, and finalizes the EditOp through `dirty.ts`.
 *
 * The card-level Undo flow keeps its existing per-field state capture so
 * the Undo button can revert without going through the (Phase 5) inverse
 * patch path.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegResolveRefResponse } from '../../../../lib/types/api';
import type { Segment } from '../../../../lib/types/domain';
import { refreshSegInStore, selectedChapter } from '../../stores/chapter';
import {
    finalizeOp,
    markDirty,
    setPendingOp,
} from '../../stores/dirty';
import { applyCommand } from '../../domain/apply-command';

export interface AutoFixResult {
    /** EditOp `op_id` so the card can wire its Undo to the right log entry. */
    opId: string;
    /** Pre-mutation state of the touched fields, captured for the card's Undo. */
    before: {
        matched_ref: string;
        matched_text: string;
        display_text: string;
        confidence: number;
        ignored_categories: string[] | null;
    };
}

/**
 * Apply the missing-words auto-fix to `seg`. Resolves the new ref text and
 * dispatches an `autoFixMissingWord` command. Returns a result record the
 * caller (`MissingWordsCard.handleAutoFix`) uses to hand its Undo button
 * the right snapshot to revert to.
 *
 * Returns `null` if the seg lacks a `segment_uid` — auto-fix without a
 * stable identity is not supported (Phase 4 backfills uids on load, so
 * this is a defensive guard for legacy fixtures).
 */
export async function autoFixMissingWord(
    seg: Segment,
    newRef: string,
): Promise<AutoFixResult | null> {
    const uid = seg.segment_uid;
    if (!uid) return null;
    const segChapter = seg.chapter ?? parseInt(get(selectedChapter));

    const before: AutoFixResult['before'] = {
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        display_text: seg.display_text || '',
        confidence: seg.confidence,
        ignored_categories: seg.ignored_categories ? [...seg.ignored_categories] : null,
    };

    let resolvedText = '';
    let resolvedDisplay = '';
    try {
        const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
            `/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`,
        );
        if (data.text) {
            resolvedText = data.text;
            resolvedDisplay = data.display_text || data.text;
        } else if (data.error) {
            console.warn('auto-fix resolve_ref error:', data.error);
            resolvedText = '(invalid ref)';
        }
    } catch (e) {
        console.error('auto-fix resolve_ref failed:', e);
        resolvedText = '(resolve failed)';
    }

    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [segChapter]: [uid] },
            selectedChapter: segChapter,
        },
        {
            type: 'autoFixMissingWord',
            segmentUid: uid,
            matched_ref: newRef,
            matched_text: resolvedText,
            display_text: resolvedDisplay,
            contextCategory: 'missing_words',
        },
    );
    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.matched_ref = updated.matched_ref;
        seg.matched_text = updated.matched_text;
        seg.display_text = updated.display_text;
        seg.confidence = updated.confidence;
        if (updated.ignored_categories) {
            seg.ignored_categories = [...updated.ignored_categories];
        }
        delete (seg as Segment & { _derived?: unknown })._derived;
    }
    markDirty(segChapter, seg.index);
    refreshSegInStore(seg);

    setPendingOp(null);
    finalizeOp(segChapter, result.operation);
    return { opId: result.operation.op_id, before };
}
