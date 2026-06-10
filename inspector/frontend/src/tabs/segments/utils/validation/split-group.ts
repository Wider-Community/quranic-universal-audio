/**
 * Split-group membership — transitive closure of split descendants.
 *
 * Backend supplies the committed-history closure on every validation issue
 * item (`split_group_uids`); this function seeds the group from that set
 * and runs a fixpoint over the FE-local op log only (uncommitted edits
 * which can chain further splits before the next save). Returns the
 * matching chapter segments sorted by `time_start`.
 *
 * Empty result means "no split has touched this seg in committed history
 * AND no uncommitted split touches it" — caller falls back to rendering
 * the single resolvedSeg.
 */

import type { EditOp, Segment } from '../../../../lib/types/view-models';
import { SPLIT_GROUP_MAX_PASSES } from '../constants';

interface SnapWithUid {
    segment_uid?: string;
}

export function getSplitGroupMembers(
    rootUid: string | null,
    chapterSegs: Segment[],
    committedSplitGroupUids: readonly string[] | undefined,
    opLog: readonly EditOp[],
): Segment[] {
    if (rootUid === null) return [];

    const groupUids = new Set<string>([rootUid]);
    if (committedSplitGroupUids) {
        for (const uid of committedSplitGroupUids) groupUids.add(uid);
    }

    // Filter the FE op log to split ops once so the fixpoint walks a small
    // list. Backend has already closed the committed-history side.
    const localSplitOps = opLog.filter((op) => op.op_type === 'split_segment');
    for (let pass = 0; pass < SPLIT_GROUP_MAX_PASSES; pass++) {
        let grew = false;
        for (const op of localSplitOps) {
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

    const members = chapterSegs.filter(
        (s) => s.segment_uid != null && groupUids.has(s.segment_uid),
    );
    members.sort((a, b) => a.time_start - b.time_start);
    return members;
}
