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
    /** Next occasion's ref ("surah:ayah") when THIS occasion's last segment
     *  continues into it without a stop (cross-verse waṣl); `null` otherwise.
     *  A cross-verse waṣl is, by construction, an occasion's last segment
     *  bridging into the next occasion (occasions split on ref change). */
    bridgesOutTo: string | null;
    /** True when this occasion bridges out AND the same ordered verse pair
     *  (`ref`→`bridgesOutTo`) is ALSO crossed as a STOP elsewhere in the chapter
     *  — i.e. the boundary is take-dependent (the rare "bridges in one take,
     *  stops in another" case). Drives the filmstrip's animated join/break vs a
     *  permanently-merged mega-cell. `false` when not bridging. */
    bridgesDynamic: boolean;
}

/**
 * Split a chapter's segments into occasions, in audio order. Segments are sorted
 * by start; a new occasion begins whenever the verse ref differs from the
 * previous segment — so consecutive same-ref segments group together and a
 * foreign verse between two takes of one verse splits them.
 *
 * Two cheap post-passes annotate the cross-verse waṣl structure: `bridgesOutTo`
 * (back-stamped when a finished occasion's last segment carries `wasl`) and
 * `bridgesDynamic` (whether that same ordered boundary is also crossed as a stop
 * somewhere in the chapter).
 */
export function chapterOccasions(segments: SegmentEntry[]): ChapterOccasion[] {
    const ordered = [...segments].filter((s) => s.ref).sort((a, b) => a.t[0] - b.t[0]);
    const occasions: ChapterOccasion[] = [];
    let cur: ChapterOccasion | null = null;
    for (const seg of ordered) {
        if (cur && cur.ref === seg.ref) {
            cur.segments.push(seg);
        } else {
            // A finished occasion bridges out iff its last segment carries `wasl`
            // (it continues into this new, different-ref occasion).
            if (cur && cur.segments[cur.segments.length - 1]?.wasl) cur.bridgesOutTo = seg.ref;
            cur = { ref: seg.ref, segments: [seg], firstStartMs: seg.t[0], bridgesOutTo: null, bridgesDynamic: false };
            occasions.push(cur);
        }
    }
    // The final occasion has no following occasion → never bridges out (left null).

    // Tally every adjacent-occasion crossing as waṣl-or-stop, keyed by the
    // ordered verse pair, then flag bridging occasions whose pair also stops.
    const cross = new Map<string, { wasl: number; stop: number }>();
    for (let i = 0; i < occasions.length - 1; i++) {
        const a = occasions[i]!;
        const key = `${a.ref}→${occasions[i + 1]!.ref}`;
        const s = cross.get(key) ?? { wasl: 0, stop: 0 };
        if (a.bridgesOutTo) s.wasl++;
        else s.stop++;
        cross.set(key, s);
    }
    for (const occ of occasions) {
        if (!occ.bridgesOutTo) continue;
        occ.bridgesDynamic = (cross.get(`${occ.ref}→${occ.bridgesOutTo}`)?.stop ?? 0) > 0;
    }
    return occasions;
}
