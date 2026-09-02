/**
 * setWordTimings dispatcher: commits a realigned word list on a segment
 * through the normal command → dirty-store → save batch path, so the edit
 * lands in history and undo like any other patch op.
 */

import { get } from 'svelte/store';

import type { SegWordTiming } from '../../../../lib/types/generated/schemas';
import type { Segment } from '../../../../lib/types/view-models';
import { applyCommand } from '../../domain/apply-command';
import { refreshSegInStore, selectedChapter } from '../../stores/chapter';
import { finalizeOp, markDirty, setPendingOp } from '../../stores/dirty';

export function setWordTimingsOnSegment(seg: Segment, wordTimings: SegWordTiming[] | null): boolean {
    const uid = seg.segment_uid;
    if (!uid) return false;
    const segChapter = seg.chapter ?? parseInt(get(selectedChapter));

    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [segChapter]: [uid] },
            selectedChapter: segChapter,
        },
        { type: 'setWordTimings', segmentUid: uid, word_timings: wordTimings },
    );

    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.word_timings = updated.word_timings;
        delete (seg as Segment & { _derived?: unknown })._derived;
    }
    markDirty(segChapter, seg.index);
    refreshSegInStore(seg);

    setPendingOp(null);
    if (result.patch) result.operation.patch = result.patch;
    finalizeOp(segChapter, result.operation);
    return true;
}
