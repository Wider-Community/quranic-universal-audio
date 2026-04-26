/**
 * Live segment resolution for a validation item.
 *
 * Shared between `GenericIssueCard` (card body + ignore state) and
 * `ValidationPanel` (pill labels + tooltips) so both read from the same
 * source of truth — avoids the class of bugs where a pill renders a
 * stale server-snapshot field while the card body renders live state.
 *
 * --- The four "ref" fields hazard ---
 *
 * There are FOUR similar-named ref/text fields in this codebase; use them
 * deliberately. Displaying the wrong one is the mechanism behind the
 * cross-verse split "ref stays original" class of bugs:
 *
 *   1. `seg.matched_ref` — ground-truth live ref on the segment object.
 *       Updated by split / ref-edit / merge. This is what any ref DISPLAY
 *       should read.
 *   2. `seg.matched_text` / `seg.display_text` — text body. Updated together
 *       with `matched_ref` by `resolve_ref`. Display body reads these.
 *   3. `item.ref` — server snapshot frozen at `/api/seg/validate` response
 *       time. NEVER rewritten client-side. Safe for KEYING / navigation
 *       (jumpToSegment uses seg_index, not ref) — NEVER safe for display
 *       after any mutation that might change `matched_ref`.
 *   4. `SegValRepetitionItem.display_ref` — derived server-side for
 *       repetition labels. Same staleness rules as `item.ref`.
 *
 * Rule of thumb: for DISPLAY, resolve via this helper and read
 * `resolvedSeg.matched_ref`. For KEYING / jumping, `item.seg_index` +
 * `item.chapter` are fine.
 */

import { get } from 'svelte/store';

import type { SegValAnyItem } from '../../../../lib/types/api';
import type { Segment } from '../../../../lib/types/domain';
import { getChapterSegments, getSegByChapterIndex, selectedChapter } from '../../stores/chapter';

/**
 * Look up a segment by uid. Returns the segment if found, null otherwise.
 * A null return means the uid is stale — the segment was deleted or
 * consumed by a merge after the issue was last fetched from the server.
 */
export function resolveByUidStrict(uid: string, chapter: number): Segment | null {
    const seg = getChapterSegments(chapter).find((s) => s.segment_uid === uid);
    return seg ?? null;
}

/**
 * Resolve a validation item to its live segment.
 *
 * Preference order:
 *   1. `boundUid` lookup — the card pins to the first resolution's UID
 *      so subsequent resolutions stay on the same logical segment across
 *      split / merge reindexes. Returns null on UID miss (seg deleted or
 *      consumed by merge — card body should hide).
 *   2. `item.segment_uid` uid-first lookup — present on server-emitted
 *      items after Phase 6. Returns null on UID miss (stale issue).
 *   3. `(chapter, seg_index)` lookup — legacy fallback for items that
 *      predate uid emission (no `segment_uid` field).
 *   4. `structural_errors` category special-case: match by verse-key prefix.
 *
 * Does NOT fall back to `matched_ref === item.ref` (the legacy
 * ref-fallback heuristic). That fallback could re-point resolution to
 * an unrelated seg that happened to hold the pre-edit ref.
 */
export function resolveIssueSeg(
    item: SegValAnyItem,
    category: string,
    boundUid: string | null = null,
): Segment | null {
    const anyItem = item as { seg_index?: number; chapter: number; ref?: string; verse_key?: string; segment_uid?: string | null };
    const chapter = anyItem.chapter ?? parseInt(get(selectedChapter));

    if (boundUid) {
        const seg = getChapterSegments(chapter).find((s) => s.segment_uid === boundUid);
        return seg ?? null;
    }

    // Uid-first: when the issue carries a segment_uid, use it exclusively.
    // A miss means the segment is stale (deleted or merged); do not fall back
    // to seg_index — that could silently re-point to the wrong segment.
    if (anyItem.segment_uid != null) {
        return resolveByUidStrict(anyItem.segment_uid, chapter);
    }

    if (anyItem.seg_index != null && anyItem.seg_index < 0) return null;

    if (category === 'structural_errors') {
        const vk = anyItem.verse_key || '';
        const parts = vk.split(':');
        const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : vk;
        const chSegs = getChapterSegments(chapter);
        return chSegs.find((s) => s.matched_ref && s.matched_ref.startsWith(prefix)) ?? chSegs[0] ?? null;
    }

    if (anyItem.seg_index == null) return null;
    return getSegByChapterIndex(chapter, anyItem.seg_index) ?? null;
}

/**
 * Format-ready live ref for a validation item. Prefers the resolved seg's
 * `matched_ref`; falls back to `item.ref` (stale snapshot) only when the
 * seg can't be resolved.
 */
export function liveRefForItem(item: SegValAnyItem, category: string): string {
    const seg = resolveIssueSeg(item, category, null);
    if (seg?.matched_ref) return seg.matched_ref;
    return (item as { ref?: string }).ref ?? '';
}
