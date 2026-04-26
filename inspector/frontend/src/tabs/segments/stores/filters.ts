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
// Derived timing values — silence_after_ms per segment (IS-7 derivation)
// ---------------------------------------------------------------------------

interface SegmentTiming {
    silence_after_ms: number | null;
    silence_after_raw_ms: number | null;
}

/** Per-uid silence timing derived from segment adjacency within each entry.
 *  Maps ``segment_uid`` → ``{ silence_after_ms, silence_after_raw_ms }``.
 *  Single source of truth for the silence computation; render-path consumers
 *  read from this map via the store, and filter logic reads from it via
 *  ``segDerivedProps``. */
export const derivedTimings = derived(segAllData, ($all) => {
    const timings = new Map<string, SegmentTiming>();
    if (!$all) return timings;
    const segs = $all.segments;
    const pad = $all.pad_ms ?? 0;
    for (let i = 0; i < segs.length; i++) {
        const cur = segs[i];
        if (!cur || !cur.segment_uid) continue;
        const next = segs[i + 1];
        const sameEntry = !!next && cur.audio_url === next.audio_url
                               && cur.entry_idx === next.entry_idx;
        const t: SegmentTiming = sameEntry && next
            ? {
                silence_after_ms: (next.time_start - cur.time_end) + 2 * pad,
                silence_after_raw_ms: next.time_start - cur.time_end,
            }
            : { silence_after_ms: null, silence_after_raw_ms: null };
        timings.set(cur.segment_uid, t);
    }
    return timings;
});

/** Read the current silence-after timing for the segment with the given uid.
 *  Returns ``null`` when the uid is not in the derived map (segment not
 *  loaded, or has no ``segment_uid``). */
export function getTimingForUid(uid: string): SegmentTiming | null {
    return get(derivedTimings).get(uid) ?? null;
}

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
    const silence_after_ms = seg.segment_uid
        ? get(derivedTimings).get(seg.segment_uid)?.silence_after_ms ?? null
        : null;
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
                const timings = get(derivedTimings);
                const _silenceFor = (s: Segment | undefined): number =>
                    (s?.segment_uid && timings.get(s.segment_uid)?.silence_after_ms) ?? Infinity;
                groups.sort((a, b) => _silenceFor(a[0]) - _silenceFor(b[0]));
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
