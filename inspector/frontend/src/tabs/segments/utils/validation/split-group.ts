/**
 * Split-group membership — transitive closure of split descendants.
 *
 * Walks split ops from both committed edit-history batches and the in-progress
 * op log to build the full set of UIDs reachable from `rootUid`. Returns the
 * matching chapter segments sorted by `time_start`.
 *
 * Empty result means "no split op ever touched this seg" — caller falls back
 * to rendering the single resolvedSeg.
 */

import type { EditOp, HistoryBatch, Segment } from '../../../../lib/types/domain';
import { SPLIT_GROUP_MAX_PASSES } from '../constants';

interface SnapWithUid {
    segment_uid?: string;
}

export function getSplitGroupMembers(
    chapter: number,
    rootUid: string | null,
    chapterSegs: Segment[],
    historyBatches: HistoryBatch[],
    opLog: readonly EditOp[],
): Segment[] {
    if (rootUid === null) return [];

    // Collect every split op from both sources — pre-filter so the fixpoint
    // loop walks a small list even on chapters with heavy edit history.
    const splitOps: EditOp[] = [];
    for (const batch of historyBatches) {
        for (const op of batch.operations) {
            if (op.op_type === 'split_segment') splitOps.push(op);
        }
    }
    for (const op of opLog) {
        if (op.op_type === 'split_segment') splitOps.push(op);
    }

    const groupUids = new Set<string>([rootUid]);
    for (let pass = 0; pass < SPLIT_GROUP_MAX_PASSES; pass++) {
        let grew = false;
        for (const op of splitOps) {
            const parents = (op.targets_before ?? []) as SnapWithUid[];
            const touchesGroup = parents.some((p) => p.segment_uid && groupUids.has(p.segment_uid));
            if (!touchesGroup) continue;
            for (const child of (op.targets_after ?? []) as SnapWithUid[]) {
                if (child.segment_uid && !groupUids.has(child.segment_uid)) {
                    groupUids.add(child.segment_uid);
                    grew = true;
                }
            }
        }
        if (!grew) break;
    }

    void chapter; // callers already scope chapterSegs; kept for signature clarity.
    const members = chapterSegs.filter(
        (s) => s.segment_uid != null && groupUids.has(s.segment_uid),
    );
    members.sort((a, b) => a.time_start - b.time_start);
    return members;
}
