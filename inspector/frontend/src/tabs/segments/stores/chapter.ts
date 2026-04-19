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

/** Refresh a segment in segAllData.segments by replacing its object ref,
 *  triggering Svelte reactivity for all SegmentRow instances rendering
 *  this seg. */
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
    all._byChapter = null;
    all._byChapterIndex = null;
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
    const updated = cur.segments.map((s) => {
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
    all._byChapter = null;
    all._byChapterIndex = null;
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
