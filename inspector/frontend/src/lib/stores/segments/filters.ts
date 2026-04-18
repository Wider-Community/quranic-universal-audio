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

import type { Segment } from '../../types/domain';
import { SEG_FILTER_FIELDS } from '../../utils/segments/filter-fields';
import { countSegWords, parseSegRef } from '../../utils/segments/references';
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

// ---------------------------------------------------------------------------
// Derived: displayedSegments + _segIndexMap
// ---------------------------------------------------------------------------

interface DisplayedResult {
    segments: Segment[];
    total: number;
    indexMap: Map<string, Segment>;
}

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
            const posMap = new Map<Segment, number>(segs.map((s, i) => [s, i]));
            const resultSet = new Set<Segment>(matched);
            matched.forEach((seg) => {
                const idx = posMap.get(seg);
                if (idx === undefined) return;
                const next = segs[idx + 1];
                if (next && next.audio_url === seg.audio_url) {
                    next._isNeighbour = true;
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
