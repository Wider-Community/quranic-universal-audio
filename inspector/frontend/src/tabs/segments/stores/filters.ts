/**
 * Segments tab — active filter rows + derived displayed segments.
 *
 * The `displayedSegments` derived store reads both the filters store AND the
 * chapter store (selectedChapter/selectedVerse/segAllData) — derivation lives
 * here but is fed by `lib/stores/segments/chapter.ts` inputs.
 *
 * When `activeFilters` is empty AND no chapter is selected AND no verse filter
 * is active, `displayedSegments` falls back to an empty array (with a
 * placeholder message rendered by SegmentsList). When a chapter is selected
 * OR filters/verses are active, segments are computed normally.
 */

import { derived, get, writable } from 'svelte/store';

import type { Segment } from '../../../lib/types/domain';
import { SEG_FILTER_FIELDS } from '../utils/data/filter-fields';
import { countSegWords, parseSegRef } from '../utils/data/references';
import {
    segAllData,
    selectedChapter,
    selectedVerse,
} from './chapter';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** One active filter row — field + comparator + literal value. */
export interface SegActiveFilter {
    field: string;
    op: string;
    value: number | null;
}

/** Derived per-segment numeric properties exposed to the filter predicate. */
export interface SegDerivedProps {
    duration_s: number;
    num_words: number;
    num_verses: number;
    confidence_pct: number;
    /** `null` when no "next" segment in the same entry — meaning "unknown". */
    silence_after_ms: number | null | undefined;
    [k: string]: number | null | undefined;
}

/** `Segment` with the cached derived-props field used by the filter. */
interface SegWithDerived extends Segment {
    _derived?: SegDerivedProps;
}

// ---------------------------------------------------------------------------
// Writable store
// ---------------------------------------------------------------------------

/** List of active filter rows. Empty = "no filters". */
export const activeFilters = writable<SegActiveFilter[]>([]);

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function segDerivedProps(seg: SegWithDerived): SegDerivedProps {
    if (seg._derived) return seg._derived;
    const duration_s = (seg.time_end - seg.time_start) / 1000;
    const vwc = get(segAllData)?.verse_word_counts;
    const num_words = countSegWords(seg.matched_ref, vwc);
    const p = parseSegRef(seg.matched_ref);
    const num_verses = p ? p.ayah_to - p.ayah_from + 1 : 0;
    const confidence_pct = (seg.confidence || 0) * 100;
    const silence_after_ms = seg.silence_after_ms;
    seg._derived = { duration_s, num_words, num_verses, confidence_pct, silence_after_ms };
    return seg._derived;
}

function _compareFilter(actual: number | null | undefined, op: string, value: number): boolean {
    if (actual == null) return false;
    switch (op) {
        case '>':  return actual >  value;
        case '>=': return actual >= value;
        case '<':  return actual <  value;
        case '<=': return actual <= value;
        case '=':  return actual === value;
        default:   return true;
    }
}

/** Mutate `segAllData.segments` in-place with silence-after-ms fields.
 *  Runs once after `segAllData` is set in the chapter store. */
export function computeSilenceAfter(): void {
    const all = get(segAllData);
    if (!all) return;
    const pad = all.pad_ms ?? 0;
    const segs = all.segments;
    for (let i = 0; i < segs.length; i++) {
        const cur = segs[i];
        if (!cur) continue;
        const next = segs[i + 1];
        const sameEntry = !!next && cur.audio_url === next.audio_url
                               && cur.entry_idx === next.entry_idx;
        if (sameEntry && next) {
            cur.silence_after_ms = (next.time_start - cur.time_end) + 2 * pad;
            cur.silence_after_raw_ms = next.time_start - cur.time_end;
        } else {
            cur.silence_after_ms = null;
            cur.silence_after_raw_ms = null;
        }
    }
}

/**
 * Targeted silence recompute for a small edited window — O(k) not O(n).
 *
 * Updates silence_after_ms/silence_after_raw_ms for the affected segments and
 * their immediate outer neighbours (prev of first, next of last). The caller
 * passes the post-mutation result segments; this function locates them in
 * `segAllData.segments` by identity and expands the window by ±1 to cover
 * neighbour relationships that changed due to the edit.
 *
 * Falls back to the full `computeSilenceAfter()` when `affectedSegs` is empty
 * (delete path) or when none of the segments can be found in the global array.
 */
export function recomputeSilenceForRange(affectedSegs: Segment[]): void {
    const all = get(segAllData);
    if (!all) return;
    const segs = all.segments;
    if (affectedSegs.length === 0) {
        // Delete removed the segment; the gap between its neighbours changed —
        // full scan is the safe fallback for this uncommon op.
        computeSilenceAfter();
        return;
    }

    // Find global indices of the first and last affected segment by identity.
    let firstGlobal = segs.indexOf(affectedSegs[0]!);
    let lastGlobal  = segs.indexOf(affectedSegs[affectedSegs.length - 1]!);
    if (firstGlobal === -1 || lastGlobal === -1) {
        // Segments not found (shouldn't happen, but be safe).
        computeSilenceAfter();
        return;
    }

    // Expand window by 1 on each side to capture neighbour relationships.
    const lo = Math.max(0, firstGlobal - 1);
    const hi = Math.min(segs.length - 1, lastGlobal + 1);

    const pad = all.pad_ms ?? 0;
    for (let i = lo; i <= hi; i++) {
        const cur = segs[i];
        if (!cur) continue;
        const next = segs[i + 1];
        const sameEntry = !!next && cur.audio_url === next.audio_url
                               && cur.entry_idx === next.entry_idx;
        if (sameEntry && next) {
            cur.silence_after_ms = (next.time_start - cur.time_end) + 2 * pad;
            cur.silence_after_raw_ms = next.time_start - cur.time_end;
        } else {
            cur.silence_after_ms = null;
            cur.silence_after_raw_ms = null;
        }
    }
}

// ---------------------------------------------------------------------------
// Derived: displayedSegments + _segIndexMap
// ---------------------------------------------------------------------------

interface DisplayedResult {
    segments: Segment[];
    total: number;
    indexMap: Map<string, Segment>;
}

// Memo for the expensive neighbour-grouping + sort pass (O(n) + O(g log g)).
// The sort order is fully determined by the pre-filter segs array identity and
// all active filter values, so we can skip the pass when both are unchanged.
interface NeighbourMemo {
    segsRef: Segment[];         // identity of the chapter/verse-filtered segs array
    filtersKey: string;         // JSON of all activeValid {field,op,value} triples
    result: Segment[];
    neighbourSet: Set<Segment>; // segments marked _isNeighbour, for re-stamping on cache hit
}
let _neighbourMemo: NeighbourMemo | null = null;

/** Core filter computation. */
export function computeDisplayed(
    all: { segments: Segment[] } | null,
    chapterStr: string,
    verseStr: string,
    filters: SegActiveFilter[],
): DisplayedResult {
    if (!all) return { segments: [], total: 0, indexMap: new Map() };

    const activeValid = filters.filter((f) => f.value !== null) as Array<
        { field: string; op: string; value: number }
    >;

    if (!chapterStr && activeValid.length === 0) {
        return { segments: [], total: 0, indexMap: new Map() };
    }

    let segs: Segment[] = all.segments;
    const chapter = chapterStr ? parseInt(chapterStr) : null;
    if (chapter) {
        segs = segs.filter((s) => s.chapter === chapter);
    }
    if (verseStr && chapter) {
        const prefix = `${chapter}:${verseStr}:`;
        segs = segs.filter((s) => s.matched_ref && s.matched_ref.startsWith(prefix));
    }

    // Clear stale neighbour tags (mutates segAllData — full re-index rebuild
    // at save/undo time drops these anyway).
    all.segments.forEach((s) => { delete s._isNeighbour; });

    if (activeValid.length > 0) {
        const matched = segs.filter((seg) =>
            activeValid.every((f) => {
                const actual = segDerivedProps(seg as SegWithDerived)[f.field];
                return _compareFilter(actual, f.op, f.value);
            }),
        );

        const hasNeighbourFilter = activeValid.some((f) =>
            SEG_FILTER_FIELDS.find((fd) => fd.value === f.field)?.neighbour,
        );

        if (hasNeighbourFilter) {
            // Key by (pre-result segs identity, all active filter values).
            // `segs` here is the chapter/verse-filtered array — a new reference
            // whenever all.segments or the chapter/verse selection changes.
            // We include ALL activeValid filters (not just neighbour ones) because
            // non-neighbour filters control which segments are in `matched`, which
            // in turn determines which neighbours get included in the output.
            const preFilterSegs = segs;
            const neighbourFiltersKey = JSON.stringify(activeValid);
            if (
                _neighbourMemo !== null &&
                _neighbourMemo.segsRef === preFilterSegs &&
                _neighbourMemo.filtersKey === neighbourFiltersKey
            ) {
                // Re-stamp _isNeighbour (cleared above) from the cached set.
                _neighbourMemo.neighbourSet.forEach((s) => { s._isNeighbour = true; });
                segs = _neighbourMemo.result;
            } else {
                const posMap = new Map<Segment, number>(segs.map((s, i) => [s, i]));
                const resultSet = new Set<Segment>(matched);
                const neighbourSet = new Set<Segment>();
                matched.forEach((seg) => {
                    const idx = posMap.get(seg);
                    if (idx === undefined) return;
                    const next = segs[idx + 1];
                    if (next && next.audio_url === seg.audio_url) {
                        next._isNeighbour = true;
                        neighbourSet.add(next);
                        resultSet.add(next);
                    }
                });
                segs = segs.filter((seg) => resultSet.has(seg));

                const groups: Segment[][] = [];
                for (let i = 0; i < segs.length; i++) {
                    const seg = segs[i];
                    if (!seg) continue;
                    if (!seg._isNeighbour) {
                        const group: Segment[] = [seg];
                        const nxt = segs[i + 1];
                        if (nxt && nxt._isNeighbour) {
                            group.push(nxt);
                            i++;
                        }
                        groups.push(group);
                    }
                }
                groups.sort((a, b) =>
                    ((a[0]?.silence_after_ms ?? Infinity) - (b[0]?.silence_after_ms ?? Infinity)),
                );
                segs = groups.flat();
                _neighbourMemo = { segsRef: preFilterSegs, filtersKey: neighbourFiltersKey, result: segs, neighbourSet };
            }
        } else {
            segs = matched;
        }
    }

    const total = chapter
        ? all.segments.filter((s) => s.chapter === chapter).length
        : all.segments.length;
    const indexMap = new Map<string, Segment>(
        segs.map((s) => [`${s.chapter}:${s.index}`, s]),
    );
    return { segments: segs, total, indexMap };
}

/** Derived store: segments to render, given current chapter/verse/filters. */
export const displayedResult = derived(
    [segAllData, selectedChapter, selectedVerse, activeFilters],
    ([$all, $chapter, $verse, $filters]) =>
        computeDisplayed($all, $chapter, $verse, $filters),
);

/** Just the segment list for `{#each}` in SegmentsList. */
export const displayedSegments = derived(displayedResult, ($r) => $r.segments);

/** (chapter:index) → Segment map used by the waveform IntersectionObserver
 *  callback to resolve segments from `.seg-row` dataset attributes. */
export const segIndexMap = derived(displayedResult, ($r) => $r.indexMap);
