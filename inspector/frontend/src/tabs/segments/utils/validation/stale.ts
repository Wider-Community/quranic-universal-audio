/**
 * Stale-issue filter for the validation panel.
 *
 * After a structural edit (split, merge, delete), issues whose
 * `segment_uid` no longer appears in the live segment state are
 * considered stale and must not be rendered. Issues that carry no
 * `segment_uid` (legacy seg_index path) are kept so the fallback
 * resolution path in `resolve-issue.ts` can still handle them.
 *
 * Merge-awareness: when a merge consumes a segment, the consumed UID is
 * removed from the live set. Rather than dropping the issue (which causes
 * accordion cards to disappear), we check the merge redirect map. If the
 * consumed UID redirects to a surviving segment in the live set, we keep
 * the issue and update its `segment_uid` to point to the survivor, so the
 * card resolves to the merged segment and the user can continue working.
 *
 * Mid-load race: validation responses are fetched in parallel with
 * ``segAllData`` (see ``reciter-actions.ts:reloadCurrentReciter``).
 * In the brief window where validation has resolved but ``segAllData``
 * has not, ``liveUids`` is empty and every uid-bearing issue is dropped.
 * Today both fetches share the same `await Promise.allSettled` boundary
 * so the panel never renders during the gap; if lazy chapter loading
 * (per-chapter ``segAllData`` instead of full corpus) is added later,
 * this filter would need to wait for the relevant chapter's uids
 * before deciding. Tracked as B-5 in ``.refactor/bug-log.md``.
 */

import type { SegValAnyItem } from '../../../../lib/types/api';
import { resolveMergeRedirect, hasMergeRedirect } from '../../stores/merge-redirect';

/**
 * Return only the issues that are still live.
 *
 * - Items with a `segment_uid` that is absent from `liveUids` are dropped,
 *   UNLESS the uid has a merge redirect to a live segment (in which case
 *   the item's `segment_uid` is updated in place to the surviving uid).
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
        const item = issue as { segment_uid?: string | null };
        const uid = item.segment_uid;
        // Defense-in-depth: an empty-string uid is treated like a missing
        // one. Production payloads never carry it (the backend canonicalizes
        // ``""`` → ``None`` on serialize), so this branch is unreachable
        // today; the explicit guard avoids a silent drop if a future loader
        // ships through a stray empty string.
        if (uid == null || uid === '') return true;
        if (liveUids.has(uid)) return true;

        // The uid is not live — check whether it was consumed by a merge.
        // If the redirect target is live, update the item's segment_uid so
        // downstream resolvers (resolveIssueSeg, GenericIssueCard._boundUid)
        // can find the surviving segment.
        if (hasMergeRedirect(uid)) {
            const redirected = resolveMergeRedirect(uid);
            if (liveUids.has(redirected)) {
                item.segment_uid = redirected;
                return true;
            }
        }
        return false;
    });
}


