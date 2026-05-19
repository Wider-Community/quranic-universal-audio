/**
 * setIsWasl dispatcher.
 *
 * Wraps ``applyCommand({type: 'setIsWasl', ...})`` and the live-store glue:
 * mutates the seg's ``is_wasl`` flag, marks the chapter dirty, refreshes
 * the seg in the chapter store, and finalises the op so it flows through
 * the normal save batch (no immediate-save).
 *
 * Wasl is a boundary annotation between two adjacent segments; the flag
 * lives on the LEFT seg. Callers should only invoke this when the seg
 * has a right neighbour in the same chapter — the inter-row WaslGap
 * affordance already enforces that gate.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { applyCommand } from '../../domain/apply-command';
import { refreshSegInStore, selectedChapter } from '../../stores/chapter';
import {
    finalizeOp,
    markDirty,
    setPendingOp,
} from '../../stores/dirty';

/**
 * Set ``is_wasl`` on ``seg`` by dispatching a ``setIsWasl`` command, then
 * commit the resulting op to the dirty store and refresh ``seg``.
 *
 * Returns false when the requested value already matches (no-op guard) or
 * when the segment lacks a UID (legacy fixtures only).
 */
export function setIsWaslOnSegment(seg: Segment, value: boolean): boolean {
    const current = seg.is_wasl === true;
    if (current === value) return false;

    const segChapter = seg.chapter ?? parseInt(get(selectedChapter));
    const uid = seg.segment_uid;
    if (!uid) return false;

    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [segChapter]: [uid] },
            selectedChapter: segChapter,
        },
        { type: 'setIsWasl', segmentUid: uid, is_wasl: value },
    );

    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.is_wasl = updated.is_wasl;
        delete (seg as Segment & { _derived?: unknown })._derived;
    }
    markDirty(segChapter, seg.index);
    refreshSegInStore(seg);

    setPendingOp(null);
    if (result.patch) result.operation.patch = result.patch;
    finalizeOp(segChapter, result.operation);
    return true;
}
