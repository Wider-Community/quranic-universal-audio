/**
 * Stale-issue filter for the validation panel.
 *
 * After a structural edit (split, merge, delete), issues whose
 * `segment_uid` no longer appears in the live segment state are
 * considered stale and must not be rendered. Issues that carry no
 * `segment_uid` (legacy seg_index path) are kept so the fallback
 * resolution path in `resolve-issue.ts` can still handle them.
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
        // Defense-in-depth: an empty-string uid is treated like a missing
        // one. Production payloads never carry it (the backend canonicalizes
        // ``""`` → ``None`` on serialize), so this branch is unreachable
        // today; the explicit guard avoids a silent drop if a future loader
        // ships through a stray empty string.
        if (uid == null || uid === '') return true;
        return liveUids.has(uid);
    });
}
