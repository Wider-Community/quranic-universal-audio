/**
 * Segments tab — chapter/reciter/verse selection + loaded chapter data.
 * Derived stores expose per-chapter segment slices and verse options.
 */

import { derived, get,writable } from 'svelte/store';

import type {
    SegAllResponse,
    SegDataResponse,
} from '../../../lib/types/api';
import type { Segment,SegReciter } from '../../../lib/types/domain';

/** Alias for clarity — `SegDataResponse` may be mutated with a proxy URL. */
export type SegDataState = SegDataResponse;

// ---------------------------------------------------------------------------
// Writable stores
// ---------------------------------------------------------------------------

/** All reciters for the segments tab (eager-loaded from /api/seg/reciters). */
export const segAllReciters = writable<SegReciter[]>([]);

/** Currently selected reciter slug. */
export const selectedReciter = writable<string>('');

/** Currently selected chapter id ("" or "1".."114"). */
export const selectedChapter = writable<string>('');

/** Currently selected verse filter ("" means "All"). */
export const selectedVerse = writable<string>('');

/** Full reciter corpus (segments across all chapters). */
export const segAllData = writable<SegAllResponse | null>(null);

/** Per-chapter loaded data (audio_url, pad_ms, segments). */
export const segData = writable<SegDataState | null>(null);

/** Currently-playing segment index (shared across playback + row/card UI). */
export const segCurrentIdx = writable<number>(-1);

// ---------------------------------------------------------------------------
// Public selectors — preserved compat surface for ~50 subscriber sites
// ---------------------------------------------------------------------------

/** Build the ordered segment list for *chapter* from a flat ``segments``
 *  array.  Allocates a fresh array every call — callers that need stable
 *  identity should subscribe to ``currentChapterSegments`` instead. */
function _sliceChapter(segments: Segment[], chapter: number | string): Segment[] {
    const ch = typeof chapter === 'number' ? chapter : parseInt(chapter);
    if (!Number.isFinite(ch)) return [];
    const slice = segments.filter((s) => s.chapter === ch);
    slice.sort((a, b) => a.index - b.index);
    return slice;
}

/** Lazy per-chapter segment lookup. */
export function getChapterSegments(chapter: number | string): Segment[] {
    const all = get(segAllData);
    if (!all || !all.segments) return [];
    return _sliceChapter(all.segments, chapter);
}

/** Lazy single-segment lookup by (chapter, index). */
export function getSegByChapterIndex(
    chapter: number | string,
    index: number,
): Segment | null {
    const segs = getChapterSegments(chapter);
    return segs.find((s) => s.index === index) ?? null;
}

export interface AdjacentSegments {
    prev: Segment | null;
    next: Segment | null;
}

export function getAdjacentSegments(
    chapter: number | string,
    index: number,
): AdjacentSegments {
    const segs = getChapterSegments(chapter);
    const pos = segs.findIndex((s) => s.index === index);
    return {
        prev: pos > 0 ? (segs[pos - 1] ?? null) : null,
        next: pos >= 0 && pos < segs.length - 1 ? (segs[pos + 1] ?? null) : null,
    };
}

/** No-op shim: kept for API compatibility with ~30 call sites that invoke
 *  it after edits.  The chapter slice is now derived from ``segAllData``
 *  on every read, so explicit invalidation is unnecessary. */
export function invalidateChapterIndex(): void {
    /* intentionally empty */
}

/** No-op shim: kept for API compatibility (see ``invalidateChapterIndex``). */
export function invalidateChapterIndexFor(_chapter: number | string): void {
    /* intentionally empty */
    void _chapter;
}

/** Refresh a segment in ``segAllData.segments`` by replacing its object ref,
 *  triggering Svelte reactivity for all rows rendering this seg. */
export function refreshSegInStore(seg: Segment): void {
    const all = get(segAllData);
    if (!all?.segments) return;
    const uid = seg.segment_uid;
    const idx = all.segments.findIndex((s) =>
        (uid && s.segment_uid === uid) ||
        (s.chapter === seg.chapter && s.index === seg.index),
    );
    if (idx < 0) return;
    all.segments[idx] = { ...seg };
    segAllData.update((d) => d);
}

/**
 * Sync segData.segments (chapter-specific edits) back into segAllData.segments.
 * Reads current chapter from `selectedChapter` to know which chapter block to replace.
 */
export function syncChapterSegsToAll(): void {
    const all = get(segAllData);
    const cur = get(segData);
    const chapterStr = get(selectedChapter);
    const chapter = parseInt(chapterStr);
    if (!all || !cur || !cur.segments || !chapter) return;

    const other = all.segments.filter((s) => s.chapter !== chapter);
    // Cross-chapter guard: if a seg was handed to this cur.segments list with a
    // non-null chapter that doesn't match, do NOT stomp it with the sync
    // chapter — that would corrupt its real chapter pointer. Warn and skip.
    const updated = cur.segments.filter((s) => {
        if (s.chapter != null && s.chapter !== chapter) {
            console.warn('syncChapterSegsToAll: cross-chapter leak', s.segment_uid);
            return false;
        }
        return true;
    }).map((s) => {
        s.chapter = chapter;
        return s;
    });
    const insertIdx = other.findIndex((s) => (s.chapter ?? 0) > chapter);
    if (insertIdx === -1) {
        all.segments = [...other, ...updated];
    } else {
        all.segments = [
            ...other.slice(0, insertIdx),
            ...updated,
            ...other.slice(insertIdx),
        ];
    }
}

/** Read the current chapter's segments from segData or segAllData. */
export function getCurrentChapterSegs(): Segment[] {
    const cur = get(segData);
    if (cur?.segments?.length) return cur.segments;
    const ch = parseInt(get(selectedChapter));
    if (!ch) return [];
    const all = get(segAllData);
    if (!all?.segments) return [];
    return _sliceChapter(all.segments, ch);
}

// ---------------------------------------------------------------------------
// Derived stores
// ---------------------------------------------------------------------------

/** Segments for the currently-selected chapter. Rebuilds when either
 * `segAllData` or `selectedChapter` changes. */
export const currentChapterSegments = derived(
    [segAllData, selectedChapter],
    ([$all, $ch]) => {
        if (!$all || !$ch) return [];
        return _sliceChapter($all.segments, $ch);
    },
);

/** Verse list for the current chapter — numbers extracted from matched_ref. */
export const verseOptions = derived(currentChapterSegments, ($segs) => {
    const verses = new Set<number>();
    for (const s of $segs) {
        if (!s.matched_ref) continue;
        const startParts = s.matched_ref.split('-')[0]?.split(':');
        if (startParts && startParts.length >= 2 && startParts[1] != null) {
            const v = parseInt(startParts[1]);
            if (!isNaN(v)) verses.add(v);
        }
    }
    return [...verses].sort((a, b) => a - b);
});
