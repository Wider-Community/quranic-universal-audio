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

/** Shape of segAllData — no internal cache fields exposed. */
export type SegAllDataState = SegAllResponse;

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
export const segAllData = writable<SegAllDataState | null>(null);

/** Per-chapter loaded data (audio_url, pad_ms, segments). */
export const segData = writable<SegDataState | null>(null);

/** Currently-playing segment index (shared across playback + row/card UI). */
export const segCurrentIdx = writable<number>(-1);

// ---------------------------------------------------------------------------
// Module-level index caches — keyed by SegAllDataState identity
// ---------------------------------------------------------------------------

let _cachedRef: SegAllDataState | null = null;
let _byChapter: Record<string, Segment[]> = {};
let _byChapterIndex: Map<string, Segment> = new Map();

function _resetCache(): void {
    _cachedRef = null;
    _byChapter = {};
    _byChapterIndex = new Map();
}

function _buildIndex(all: SegAllDataState): void {
    if (_cachedRef === all) return;
    const byChapter: Record<string, Segment[]> = {};
    const byIndex = new Map<string, Segment>();
    for (const s of all.segments) {
        const ch = s.chapter;
        if (ch == null) continue;
        const key = String(ch);
        if (!byChapter[key]) byChapter[key] = [];
        byChapter[key]!.push(s);
        byIndex.set(`${ch}:${s.index}`, s);
    }
    for (const ch of Object.keys(byChapter)) {
        const list = byChapter[ch];
        if (list) list.sort((a, b) => a.index - b.index);
    }
    _byChapter = byChapter;
    _byChapterIndex = byIndex;
    _cachedRef = all;
}

// ---------------------------------------------------------------------------
// Public selectors — preserved compat surface for ~50 subscriber sites
// ---------------------------------------------------------------------------

/** Lazy per-chapter segment lookup. */
export function getChapterSegments(chapter: number | string): Segment[] {
    const all = get(segAllData);
    if (!all || !all.segments) return [];
    _buildIndex(all);
    return _byChapter[String(chapter)] ?? [];
}

/** Lazy single-segment lookup by (chapter, index). */
export function getSegByChapterIndex(
    chapter: number | string,
    index: number,
): Segment | null {
    const all = get(segAllData);
    if (!all || !all.segments) return null;
    _buildIndex(all);
    return _byChapterIndex.get(`${chapter}:${index}`) ?? null;
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

/** Drop the chapter index so the next call to `getChapterSegments` rebuilds it. */
export function invalidateChapterIndex(): void {
    _resetCache();
}

/** Surgical re-cache: drop the given chapter's entries and repopulate
 *  from the current `all.segments` so subsequent `getChapterSegments(chapter)`
 *  reads return the post-edit slice.
 *
 *  Leaves other chapters' cached slices + index rows untouched. Used after
 *  structural edits (split/merge/delete/trim) which reindex a single chapter
 *  in place. */
export function invalidateChapterIndexFor(chapter: number | string): void {
    const all = get(segAllData);
    if (!all) return;
    const ch = typeof chapter === 'number' ? chapter : parseInt(chapter);
    if (!ch) {
        _resetCache();
        return;
    }
    // Evict just this chapter's rows from the index map
    const prefix = `${ch}:`;
    for (const key of _byChapterIndex.keys()) {
        if (key.startsWith(prefix)) _byChapterIndex.delete(key);
    }
    // Rebuild this chapter's slice from the source array
    const slice = all.segments.filter((s) => s.chapter === ch);
    slice.sort((a, b) => a.index - b.index);
    _byChapter[String(ch)] = slice;
    for (const s of slice) _byChapterIndex.set(`${ch}:${s.index}`, s);
}

/** Refresh a segment in segAllData.segments by replacing its object ref,
 *  triggering Svelte reactivity for all SegmentRow instances rendering
 *  this seg.
 *
 *  Surgical cache patch: the common non-structural case (trim / ref-edit /
 *  confidence bump) only mutates one entry — we replace the per-chapter
 *  slice entry and the `"chapter:index"` index entry in place instead of
 *  nulling both caches. */
export function refreshSegInStore(seg: Segment): void {
    const all = get(segAllData);
    if (!all?.segments) return;
    const uid = seg.segment_uid;
    const idx = all.segments.findIndex((s) =>
        (uid && s.segment_uid === uid) ||
        (s.chapter === seg.chapter && s.index === seg.index),
    );
    if (idx < 0) return;
    const fresh = { ...seg };
    all.segments[idx] = fresh;

    // Surgical patch: update just this entry in the module-level caches.
    if (fresh.chapter != null && _cachedRef === all) {
        const chKey = String(fresh.chapter);
        const list = _byChapter[chKey];
        if (list) {
            const localIdx = list.findIndex((s) =>
                (uid && s.segment_uid === uid) ||
                (s.chapter === fresh.chapter && s.index === fresh.index),
            );
            if (localIdx >= 0) list[localIdx] = fresh;
            else {
                // Edge case: seg added to this chapter after cache build.
                delete _byChapter[chKey];
            }
        }
        _byChapterIndex.set(`${fresh.chapter}:${fresh.index}`, fresh);
    }
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
    // Structural reindex changed THIS chapter only — drop just its entries.
    if (_cachedRef === all) {
        const prefix = `${chapter}:`;
        for (const key of _byChapterIndex.keys()) {
            if (key.startsWith(prefix)) _byChapterIndex.delete(key);
        }
        const sorted = [...updated].sort((a, b) => a.index - b.index);
        _byChapter[String(chapter)] = sorted;
        for (const s of updated) {
            if (s.chapter != null) _byChapterIndex.set(`${s.chapter}:${s.index}`, s);
        }
    } else {
        _resetCache();
    }
}

/** Read the current chapter's segments from segData or segAllData. */
export function getCurrentChapterSegs(): Segment[] {
    const cur = get(segData);
    if (cur?.segments?.length) return cur.segments;
    const ch = parseInt(get(selectedChapter));
    if (!ch) return [];
    const all = get(segAllData);
    return all?.segments.filter((s) => s.chapter === ch) ?? [];
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
        _buildIndex($all);
        return _byChapter[$ch] ?? [];
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
