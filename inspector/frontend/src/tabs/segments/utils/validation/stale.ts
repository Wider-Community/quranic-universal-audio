/**
 * Stale-issue filter for the validation panel.
 *
 * After a structural edit (split, merge, delete), issues whose
 * `segment_uid` no longer appears in the live segment state are
 * considered stale and must not be rendered. Issues that carry no
 * `segment_uid` (legacy seg_index path) are kept so the fallback
 * resolution path in `resolve-issue.ts` can still handle them.
 */

import type { SegValAnyItem } from '../../../../lib/types/api';

/**
 * Return only the issues that are still live.
 *
 * - Items with a `segment_uid` that is absent from `liveUids` are dropped.
 * - Items with `segment_uid: null` or no `segment_uid` field are kept.
 *
 * @param issues  Flat list of validation items (any category).
 * @param liveUids  Set of segment_uid strings currently in the store.
 */
export function filterStaleIssues(
    issues: SegValAnyItem[],
    liveUids: Set<string>,
): SegValAnyItem[] {
    return issues.filter((issue) => {
        const uid = (issue as { segment_uid?: string | null }).segment_uid;
        if (uid == null) return true;
        return liveUids.has(uid);
    });
}
