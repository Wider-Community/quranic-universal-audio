/**
 * Occasion splitting for temporal segment-array shards.
 *
 * The bucket stores every recited segment raw, in recitation order — a verse may
 * recur across several entries (loopbacks, re-dos). An OCCASION is a maximal run
 * of consecutive same-verse segments in audio order: a foreign verse between two
 * takes of the same verse breaks the run, a silence between them does not. So a
 * false start, a restart, or a within-verse pause all stay inside one occasion,
 * while a full-verse loopback splits into separate occasions.
 *
 * The Timestamps tab focuses one occasion at a time (waveform + analysis), and
 * the chapter player flattens every occasion's words — no dedup, so every recited
 * word (incl. repeats) stays seekable. See `ts-source.ts` (assembly) and
 * `recitation-animation/chapter-words.ts` (chapter-absolute units).
 */

import type { SegmentEntry } from '../types/ts-client';

/** One contiguous recitation of a single verse — its segments in audio order. */
export interface ChapterOccasion {
    /** "surah:ayah". */
    ref: string;
    /** The occasion's segments, in recitation order. */
    segments: SegmentEntry[];
    /** Chapter-absolute start (ms) of the occasion's first segment. */
    firstStartMs: number;
}

/**
 * Split a chapter's segments into occasions, in audio order. Segments are sorted
 * by start; a new occasion begins whenever the verse ref differs from the
 * previous segment — so consecutive same-ref segments group together and a
 * foreign verse between two takes of one verse splits them.
 */
export function chapterOccasions(segments: SegmentEntry[]): ChapterOccasion[] {
    const ordered = [...segments].filter((s) => s.ref).sort((a, b) => a.t[0] - b.t[0]);
    const occasions: ChapterOccasion[] = [];
    let cur: ChapterOccasion | null = null;
    for (const seg of ordered) {
        if (cur && cur.ref === seg.ref) {
            cur.segments.push(seg);
        } else {
            cur = { ref: seg.ref, segments: [seg], firstStartMs: seg.t[0] };
            occasions.push(cur);
        }
    }
    return occasions;
}
