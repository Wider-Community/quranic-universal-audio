/**
 * Auto-fix dispatcher for the missing-words card.
 *
 * Wraps `applyCommand({type: 'autoFixMissingWord', ...})` and the live-store
 * glue. Derives the new ref's matched_text locally via `dkTextForRef`,
 * dispatches the command, applies the mutation to the live segment, marks
 * dirty, and finalizes the EditOp through `dirty.ts`.
 *
 * The card-level Undo flow keeps its existing per-field state capture so
 * the Undo button can revert without going through the (Phase 5) inverse
 * patch path.
 */

import { get } from 'svelte/store';

import { quranRefs } from '../../../../lib/refs/quran-refs';
import type { Segment } from '../../../../lib/types/view-models';
import { applyCommand } from '../../domain/apply-command';
import {
    refreshSegInStore,
    selectedChapter,
} from '../../stores/chapter';
import {
    markDirty,
    setPendingOp,
} from '../../stores/dirty';
import { segValidation } from '../../stores/validation';
import { dkTextForRef, getVerseWordCounts } from '../data/references';
import { finalizeEdit } from './common';

export interface AutoFixResult {
    /** EditOp `op_id` so the card can wire its Undo to the right log entry. */
    opId: string;
    /** Pre-mutation state of the touched fields, captured for the card's Undo. */
    before: {
        matched_ref: string;
        matched_text: string;
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
export function autoFixMissingWord(
    seg: Segment,
    newRef: string,
): AutoFixResult | null {
    const uid = seg.segment_uid;
    if (!uid) return null;
    const segChapter = seg.chapter ?? parseInt(get(selectedChapter));

    const before: AutoFixResult['before'] = {
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        confidence: seg.confidence,
        ignored_categories: seg.ignored_categories ? [...seg.ignored_categories] : null,
    };

    const dk = get(quranRefs)?.dk_words;
    const resolvedText = dkTextForRef(newRef, dk, getVerseWordCounts()) || '(invalid ref)';

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
            contextCategory: 'missing_words',
        },
    );
    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.matched_ref = updated.matched_ref;
        seg.matched_text = updated.matched_text;
        seg.confidence = updated.confidence;
        if (updated.ignored_categories) {
            seg.ignored_categories = [...updated.ignored_categories];
        }
        delete (seg as Segment & { _derived?: unknown })._derived;
    }
    markDirty(segChapter, seg.index);
    refreshSegInStore(seg);

    setPendingOp(null);
    // Match commitRefEdit's wiring: finalizeEdit attaches the forward patch,
    // updates `targets_after`, and triggers applyVerseFilterAndRender so the
    // SegmentRow body picks up the new matched_ref/matched_text right away.
    finalizeEdit(result.operation, segChapter, [seg], { patch: result.patch });

    // Clear the auto-fix availability flags on the local validation item so
    // the green Auto-Fill button turns grey immediately without waiting for
    // the post-save validation refresh. The next refreshValidation() call
    // will reconcile authoritatively.
    segValidation.update((v) => {
        if (!v?.missing_words) return v;
        const next = v.missing_words.map((it) => {
            const items = it.seg_indices ?? [];
            if (!items.includes(seg.index)) return it;
            const stripped = { ...it };
            delete (stripped as { auto_fix?: unknown }).auto_fix;
            delete (stripped as { auto_fix_up?: unknown }).auto_fix_up;
            delete (stripped as { auto_fix_down?: unknown }).auto_fix_down;
            return stripped;
        });
        return { ...v, missing_words: next };
    });
    return { opId: result.operation.op_id, before };
}
