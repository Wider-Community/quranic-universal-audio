/**
 * Client-side completion-based occasion dedup for temporal segment-array shards.
 *
 * The bucket stores every recited segment raw, in recitation order (a verse may
 * recur across several entries — loopbacks, re-dos). Consumers reduce a verse's
 * segments to a single canonical take. This is the FE mirror of the backend's
 * `qua_shared/timestamps_dedup.py::project_segment_shard` at the granularity the
 * Timestamps tab needs: it groups by verse, splits into occasions, picks the
 * canonical (completing) occasion, and exposes ALL occasions in recitation order
 * for the (deferred) loopback filmstrip.
 *
 * Among multiple completing occasions both this and the backend pick the
 * EARLIEST (first recited); the canonical clip trims both a leading false-start
 * and trailing post-completion redundancy. Same shape as the backend.
 */

import type { SegmentEntry } from '../types/ts-client';

/** A verse's segments grouped into one recitation occasion. */
export type Occasion = SegmentEntry[];

export interface VerseOccasions {
    ref: string;
    /** Every occasion for the verse, in recitation order. */
    occasions: Occasion[];
    /** The canonical (completing) occasion — the default per-verse clip. */
    canonical: Occasion;
    /** Index into `occasions` of the canonical pick. */
    canonicalIndex: number;
    /** Recitation order of the verse's earliest segment (for chapter ordering). */
    firstStartMs: number;
}

function segWidxSet(seg: SegmentEntry): Set<number> {
    const s = new Set<number>();
    for (const w of seg.words) s.add(w[0]);
    return s;
}

/**
 * Split a verse's time-ordered segments into occasions. An occasion is a
 * maximal run adjacent in the chapter timeline with no other verse interleaved:
 * a foreign segment whose start falls strictly between two consecutive
 * same-verse segment starts breaks the run.
 */
function splitOccasions(verseSegs: SegmentEntry[], foreignStarts: number[]): Occasion[] {
    const occasions: Occasion[] = [];
    let cur: Occasion = [];
    for (const seg of verseSegs) {
        if (cur.length) {
            const prevStart = cur[cur.length - 1]!.t[0];
            const thisStart = seg.t[0];
            if (foreignStarts.some((ft) => prevStart < ft && ft < thisStart)) {
                occasions.push(cur);
                cur = [];
            }
        }
        cur.push(seg);
    }
    if (cur.length) occasions.push(cur);
    return occasions;
}

/** Index of the segment that first reaches full coverage `target`, else null.
 *  Coverage accumulates in time order; within-pass backward loops are retained
 *  verbatim (every segment contributes, none deduped). */
function completesAt(occasion: Occasion, target: Set<number>): number | null {
    const covered = new Set<number>();
    for (let i = 0; i < occasion.length; i++) {
        for (const wi of segWidxSet(occasion[i]!)) covered.add(wi);
        let subset = true;
        for (const t of target) {
            if (!covered.has(t)) { subset = false; break; }
        }
        if (subset) return i;
    }
    return null;
}

function widestCoverage(occasions: Occasion[]): Occasion {
    let best = occasions[0]!;
    let bestN = -1;
    for (const occ of occasions) {
        const u = new Set<number>();
        for (const seg of occ) for (const wi of segWidxSet(seg)) u.add(wi);
        if (u.size > bestN) { bestN = u.size; best = occ; }
    }
    return best;
}

/**
 * Group a chapter's segments by verse ref and resolve occasions + the canonical
 * take per verse. Verses are returned in recitation order (by their earliest
 * segment start), matching how the chapter plays.
 */
export function groupVerseOccasions(segments: SegmentEntry[]): VerseOccasions[] {
    const ordered = [...segments].filter((s) => s.ref).sort((a, b) => a.t[0] - b.t[0]);

    const byVerse = new Map<string, SegmentEntry[]>();
    for (const seg of ordered) {
        const list = byVerse.get(seg.ref);
        if (list) list.push(seg);
        else byVerse.set(seg.ref, [seg]);
    }

    const startsByVerse = new Map<string, number[]>();
    for (const [ref, segs] of byVerse) startsByVerse.set(ref, segs.map((s) => s.t[0]));

    const out: VerseOccasions[] = [];
    for (const [ref, verseSegs] of byVerse) {
        const foreignStarts: number[] = [];
        for (const [otherRef, starts] of startsByVerse) {
            if (otherRef !== ref) foreignStarts.push(...starts);
        }
        foreignStarts.sort((a, b) => a - b);

        const occasions = splitOccasions(verseSegs, foreignStarts);

        let nWords = 0;
        for (const seg of verseSegs) for (const wi of segWidxSet(seg)) if (wi > nWords) nWords = wi;
        const target = new Set<number>();
        for (let i = 1; i <= nWords; i++) target.add(i);

        const completing = occasions.filter((occ) => completesAt(occ, target) !== null);
        const canonical = completing.length ? completing[0]! : widestCoverage(occasions);
        const canonicalIndex = occasions.indexOf(canonical);

        out.push({
            ref,
            occasions,
            canonical,
            canonicalIndex,
            firstStartMs: verseSegs[0]!.t[0],
        });
    }

    out.sort((a, b) => a.firstStartMs - b.firstStartMs);
    return out;
}

/**
 * Maximal contiguous word coverage check: does `segs` cover every widx in
 * `target`? Used to detect a redundant leading false-start.
 */
function coversTarget(segs: Occasion, target: Set<number>): boolean {
    const cov = new Set<number>();
    for (const seg of segs) for (const wi of segWidxSet(seg)) cov.add(wi);
    for (const t of target) if (!cov.has(t)) return false;
    return true;
}

/**
 * Drop a redundant leading false-start: keep only from the LAST segment that
 * restarts the verse at word 1 whose run still covers the whole verse. An
 * abandoned prefix before such a restart is redundant; mid-verse lookbacks
 * (a backward jump to a non-first word) never restart at 1, so they are kept.
 */
function trimLeadingFalseStart(kept: Occasion, target: Set<number>): Occasion {
    if (target.size === 0) return kept;
    let best = 0;
    for (let r = 1; r < kept.length; r++) {
        if (kept[r]!.words[0]?.[0] !== 1) continue;
        if (coversTarget(kept.slice(r), target)) best = r;
    }
    return kept.slice(best);
}

/**
 * Flatten a canonical occasion into the words the per-verse clip renders.
 * Both a leading false-start and trailing post-completion segments are trimmed
 * (never cut mid-audio); the returned `[startMs, endMs]` span covers every kept
 * segment AND every word/letter time. A word/letter can bleed a few ms past its
 * segment's `t` bound, so the clip must reach the furthest word/letter end or it
 * would truncate the final word's tail (mirrors the backend `_canonical_verse`).
 */
export function canonicalClip(
    occasion: Occasion,
    nWords: number,
): { words: SegmentEntry['words']; startMs: number; endMs: number } {
    const target = new Set<number>();
    for (let i = 1; i <= nWords; i++) target.add(i);
    const comp = completesAt(occasion, target);
    const trailing = comp !== null ? occasion.slice(0, comp + 1) : occasion;
    const kept = trimLeadingFalseStart(trailing, target);

    const words: SegmentEntry['words'] = [];
    for (const seg of kept) words.push(...seg.words);

    let startMs = kept[0]?.t[0] ?? 0;
    let endMs = kept[0]?.t[1] ?? 0;
    for (const seg of kept) {
        if (seg.t[0] < startMs) startMs = seg.t[0];
        if (seg.t[1] > endMs) endMs = seg.t[1];
        for (const w of seg.words) {
            if (w[1] < startMs) startMs = w[1];
            if (w[2] > endMs) endMs = w[2];
            for (const lt of w[3] ?? []) {
                if (lt[1] != null && lt[1] < startMs) startMs = lt[1];
                if (lt[2] != null && lt[2] > endMs) endMs = lt[2];
            }
        }
    }
    return { words, startMs, endMs };
}

/** Highest word index across all of a verse's segments (= every recited word). */
export function maxWordIndex(verseSegs: SegmentEntry[]): number {
    let n = 0;
    for (const seg of verseSegs) for (const w of seg.words) if (w[0] > n) n = w[0];
    return n;
}
