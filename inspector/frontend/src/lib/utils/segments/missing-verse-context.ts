/**
 * Missing verse boundary context — finds surrounding segments when a verse
 * has zero coverage (used by navigation's jumpToMissingVerseContext).
 */

import type { Segment } from '../../../types/domain';
import { getChapterSegments } from '../../stores/segments/chapter';
import { parseSegRef } from './references';

export interface MissingVerseContext {
    prev: Segment | null;
    next: Segment | null;
    targetVerse: number | null;
    covered: boolean;
}

export function _parseVerseFromKey(verseKey: string | null | undefined): number | null {
    const parts = (verseKey || '').split(':');
    if (parts.length < 2) return null;
    const verse = parseInt(parts[1] ?? '', 10);
    return Number.isFinite(verse) ? verse : null;
}

export function findMissingVerseBoundarySegments(
    chapter: number | string,
    verseKey: string,
): MissingVerseContext {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) return { prev: null, next: null, targetVerse: null, covered: false };

    const segs = getChapterSegments(chapter);
    let prev: Segment | null = null;
    let prevVerse = -Infinity;
    let next: Segment | null = null;
    let nextVerse = Infinity;

    for (const seg of segs) {
        const parsed = parseSegRef(seg.matched_ref);
        if (!parsed) continue;

        if (parsed.ayah_from <= targetVerse && targetVerse <= parsed.ayah_to) {
            return { prev: seg, next: seg, targetVerse, covered: true };
        }

        if (parsed.ayah_to < targetVerse && parsed.ayah_to > prevVerse) {
            prev = seg;
            prevVerse = parsed.ayah_to;
        }
        if (parsed.ayah_from > targetVerse && parsed.ayah_from < nextVerse) {
            next = seg;
            nextVerse = parsed.ayah_from;
        }
    }

    return { prev, next, targetVerse, covered: false };
}
