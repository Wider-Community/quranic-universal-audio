/**
 * Pure "next segment" list-traversal helpers — shared between `range-spec`
 * (autoplay's `resolveSegNextRange`) and `warmup` (look-ahead audio warming).
 *
 * Lives in its own module to break the import cycle: `range-spec` produces
 * AudioRange specs and consumes a "next" resolver; `warmup` warms the next
 * segment keyed off the same resolvers and consumes the VBR-clip-URL builder
 * from `range-spec`. Splitting the resolvers out lets both import from a leaf.
 */

import type { Segment } from '../../../../lib/types/domain';

/**
 * Find the next displayed segment after the given index.
 *
 * Used by chapter-mode autoplay (`resolveSegNextRange`) and chapter-mode
 * warmup — matches by `Segment.index` and steps to the slice's next
 * element. Returns null if the index is not found or is the last segment.
 */
export function nextDisplayedSeg(
    displayedSegments: Segment[] | null,
    afterIndex: number,
): Segment | null {
    if (!displayedSegments) return null;
    const pos = displayedSegments.findIndex(s => s.index === afterIndex);
    if (pos >= 0 && pos < displayedSegments.length - 1) {
        return displayedSegments[pos + 1] ?? null;
    }
    return null;
}

/**
 * Find the next accordion sibling by list position (not by `Segment.index`).
 *
 * Accordion cards may render rows from non-consecutive segments (e.g. a
 * context window: prev, target, next) or from different chapters
 * (MissingVersesCard with chapter=null). The card's render order *is* the
 * "next" order — match the current row by (chapter, index) and step
 * forward one position.
 */
export function nextSiblingSeg(
    siblings: Segment[] | null,
    currentChapter: number,
    currentIndex: number,
): Segment | null {
    if (!siblings) return null;
    const pos = siblings.findIndex(
        s => s.index === currentIndex && (s.chapter ?? 0) === currentChapter,
    );
    if (pos >= 0 && pos < siblings.length - 1) {
        return siblings[pos + 1] ?? null;
    }
    return null;
}
