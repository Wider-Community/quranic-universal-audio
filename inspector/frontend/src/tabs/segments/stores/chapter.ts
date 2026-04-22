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

/** `SegAllResponse` + lazily-built per-chapter indices (mutable cache fields). */
export interface SegAllDataState extends SegAllResponse {
    _byChapter?: Record<string, Segment[]> | null;
    _byChapterIndex?: Map<string, Segment> | null;
}

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
// Helpers — lazy per-chapter index building on segAllData
// ---------------------------------------------------------------------------

function ensureChapterIndex(all: SegAllDataState): void {
    if (all._byChapter && all._byChapterIndex) return;
    const byChapter: Record<string, Segment[]> = {};
    const byIndex = new Map<string, Segment>();
    for (const s of all.segments) {
        const ch = s.chapter;
        if (ch == null) continue;
        const key = String(ch);
        if (!byChapter[key]) byChapter[key] = [];
        byChapter[key].push(s);
        byIndex.set(`${ch}:${s.index}`, s);
    }
    for (const ch of Object.keys(byChapter)) {
        const list = byChapter[ch];
        if (list) list.sort((a, b) => a.index - b.index);
    }
    all._byChapter = byChapter;
    all._byChapterIndex = byIndex;
}

/** Lazy per-chapter segment lookup. */
export function getChapterSegments(chapter: number | string): Segment[] {
    const all = get(segAllData);
    if (!all || !all.segments) return [];
    ensureChapterIndex(all);
    return all._byChapter?.[String(chapter)] ?? [];
}

/** Lazy single-segment lookup by (chapter, index). */
export function getSegByChapterIndex(
    chapter: number | string,
    index: number,
): Segment | null {
    const all = get(segAllData);
    if (!all || !all.segments) return null;
    ensureChapterIndex(all);
    return all._byChapterIndex?.get(`${chapter}:${index}`) ?? null;
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

/** Drop lazy indices so next call to `getChapterSegments` rebuilds them. */
export function invalidateChapterIndex(): void {
    const all = get(segAllData);
    if (!all) return;
    all._byChapter = null;
    all._byChapterIndex = null;
}

/** Surgical re-cache: drop the given chapter's cache entries and repopulate
 *  from the current `all.segments` so subsequent `getChapterSegments(chapter)`
 *  reads return the post-edit slice.
 *
 *  Can't rely on `ensureChapterIndex` for lazy rebuild: it early-returns when
 *  `_byChapter` is truthy, so a per-chapter `delete` without immediate rebuild
 *  leaves `_byChapter[ch]` permanently undefined and `getChapterSegments`
 *  returning `[]` forever. That broke accordion cards (resolvedSeg = null
 *  → card body hidden) after any cross-chapter split/merge/trim/delete.
 *
 *  Leaves other chapters' cached slices + index rows untouched. Used after
 *  structural edits (split/merge/delete/trim) which reindex a single chapter
 *  in place. */
export function invalidateChapterIndexFor(chapter: number | string): void {
    const all = get(segAllData);
    if (!all) return;
    const ch = typeof chapter === 'number' ? chapter : parseInt(chapter);
    if (!ch) {
        all._byChapter = null;
        all._byChapterIndex = null;
        return;
    }
    if (all._byChapterIndex) {
        const prefix = `${ch}:`;
        for (const key of all._byChapterIndex.keys()) {
            if (key.startsWith(prefix)) all._byChapterIndex.delete(key);
        }
    }
    if (all._byChapter) {
        const slice = all.segments.filter((s) => s.chapter === ch);
        slice.sort((a, b) => a.index - b.index);
        all._byChapter[String(ch)] = slice;
        if (all._byChapterIndex) {
            for (const s of slice) all._byChapterIndex.set(`${ch}:${s.index}`, s);
        }
    }
}

/** Refresh a segment in segAllData.segments by replacing its object ref,
 *  triggering Svelte reactivity for all SegmentRow instances rendering
 *  this seg.
 *
 *  Surgical cache patch: the common non-structural case (trim / ref-edit /
 *  confidence bump) only mutates one entry — we replace the per-chapter
 *  slice entry and the `"chapter:index"` index entry in place instead of
 *  nulling both caches. Nulling forces the next `getAdjacentSegments` read
 *  to rebuild the entire index for every SegmentRow — N rows × per commit. */
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

    // Surgical patch: update just this entry in both caches. Only safe when
    // chapter/index haven't shifted (non-structural edit) — structural ops
    // (split/merge/delete) go through syncChapterSegsToAll / direct cache
    // invalidation paths that target just the affected chapter.
    if (fresh.chapter != null && all._byChapter && all._byChapterIndex) {
        const chKey = String(fresh.chapter);
        const list = all._byChapter[chKey];
        if (list) {
            const localIdx = list.findIndex((s) =>
                (uid && s.segment_uid === uid) ||
                (s.chapter === fresh.chapter && s.index === fresh.index),
            );
            if (localIdx >= 0) list[localIdx] = fresh;
            else {
                // Edge case: seg added to this chapter after cache build.
                // Drop just this chapter's slice so next read rebuilds it.
                delete all._byChapter[chKey];
            }
        }
        all._byChapterIndex.set(`${fresh.chapter}:${fresh.index}`, fresh);
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
    // Other chapters' slices + index entries remain valid and stay cached so
    // SegmentRows in unaffected chapters don't rebuild on next reactive tick.
    if (all._byChapter) delete all._byChapter[String(chapter)];
    if (all._byChapterIndex) {
        const prefix = `${chapter}:`;
        for (const key of all._byChapterIndex.keys()) {
            if (key.startsWith(prefix)) all._byChapterIndex.delete(key);
        }
        // Re-populate with the fresh `updated` list so subsequent lookups
        // hit without rebuilding. Cheaper than waiting for the next reader
        // to trigger `ensureChapterIndex`, which would re-scan all segments.
        for (const s of updated) {
            if (s.chapter != null) all._byChapterIndex.set(`${s.chapter}:${s.index}`, s);
        }
    }
    if (all._byChapter) {
        const sorted = [...updated].sort((a, b) => a.index - b.index);
        all._byChapter[String(chapter)] = sorted;
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
        ensureChapterIndex($all);
        return $all._byChapter?.[$ch] ?? [];
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
