/**
 * Resolve the "lead seg" of a validation card — the seg the reviewer is
 * most likely to play first when they engage with that card.
 *
 * NOT the same as `siblings[0]` (which is the prev-context seg for
 * MissingVerses / GenericIssue). The lead seg is what makes the warmup
 * worthwhile: warming it ahead of card-transition means the user's first
 * click in the new card hits a warm byte range, even when the new card
 * lives in a different chapter from the one they were just on.
 *
 * Per card type:
 *   - missing_verses → the `prev` boundary seg (the one right before the
 *     missing verses, which the user typically plays to hear the context
 *     before the gap). Falls back to `next` boundary if `prev` is missing.
 *   - missing_words → the first seg in `item.seg_indices`, resolved via
 *     `(chapter, index)`. That's the first seg the card renders inline.
 *   - everything else (GenericIssueCard family) → `resolveIssueSeg(item, kind, uid)`
 *     which returns the issue seg itself.
 */

import type { SegValAnyItem, SegValMissingVerseItem, SegValMissingWordsItem } from '../../../../lib/types/generated/schemas';
import type { Segment } from '../../../../lib/types/view-models';
import { getSegByChapterIndex } from '../../stores/chapter';
import { findMissingVerseBoundarySegments } from './missing-verse-context';
import { resolveIssueSeg } from './resolve-issue';

export function resolveCardLeadSeg(item: SegValAnyItem, kind: string): Segment | null {
    if (kind === 'missing_verses') {
        const mv = item as SegValMissingVerseItem;
        const b = findMissingVerseBoundarySegments(mv.chapter, mv.verse_key);
        return b.prev ?? b.next ?? null;
    }
    if (kind === 'missing_words') {
        const mw = item as SegValMissingWordsItem;
        const firstIdx = mw.seg_indices?.[0];
        if (firstIdx == null) return null;
        return getSegByChapterIndex(mw.chapter, firstIdx);
    }
    // GenericIssueCard family — uid-first lookup so split/merge survivors
    // still resolve correctly.
    const it = item as { segment_uid?: string | null };
    return resolveIssueSeg(item, kind, it.segment_uid ?? null);
}
