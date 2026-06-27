/**
 * Recitation timeline — the shared "which word is recited at time t" locator.
 *
 * Both the teleprompter line (`LineAnimation`) and the ayah filmstrip
 * (`AyahFilmstrip`) drive themselves off the actual recitation rather than a
 * monotonic clock, so they must agree on the active unit. This module owns that
 * mapping: a flat, sorted-by-start list of every occurrence interval across all
 * units, plus a stateful active-unit lookup that handles forward playback
 * (O(1)), seek-back, silence gaps, and repeats/look-backs (O(log n) bsearch).
 *
 * Pure + unit-agnostic: `t` and the interval bounds are in whatever unit the
 * caller's `AnimUnit.intervals` use (seconds in `types.ts`). No module state —
 * the O(1) fast-path hint is threaded through the `last` parameter.
 */

import type { AnimUnit } from './types';

/** One occurrence interval, tagged with its owning unit's global index. */
export interface SortedInterval {
    start: number;
    end: number;
    unitIdx: number;
    /** Target ayahKey when this occurrence's take waṣl-bridges into the next
     *  verse (the last word of a bridging take); undefined otherwise. */
    waslTo?: string;
}

/** A located active unit + the occurrence interval containing the query time.
 *  (Char-level sweeps need the interval bounds to remap repeats.) */
export interface ActiveHit {
    unitIdx: number;
    ivStart: number;
    ivEnd: number;
    /** Set when the located occurrence is the last word of a take that
     *  waṣl-bridges into the next verse; value = target ayahKey. Lets the
     *  filmstrip + teleprompter react to the LIVE take without re-matching. */
    waslTo?: string;
}

/**
 * Flatten every occurrence interval across all units, sorted ascending by
 * start. Each `units[i]` has ≥1 ascending intervals; reading order is normally
 * also temporal order, but repeats can interleave — so we sort defensively.
 * Built once per chapter.
 */
export function buildSortedIntervals(units: AnimUnit[]): SortedInterval[] {
    const out: SortedInterval[] = [];
    for (let i = 0; i < units.length; i++) {
        const u = units[i]!;
        for (const iv of u.intervals) {
            out.push({ start: iv.start, end: iv.end, unitIdx: i, waslTo: iv.waslTo });
        }
    }
    out.sort((a, b) => a.start - b.start);
    return out;
}

/**
 * Locate the unit active at time `t`, with an O(1) fast-path and an O(log n)
 * bsearch fallback. `last` is the caller's previous active `unitIdx` (or -1 for
 * a random-access query with no useful hint) — the fast-path tries `last` and
 * `last + 1`, covering forward playback without a search.
 *
 * Returns the hit (unit index + the occurrence interval containing `t`), or
 * `null` during a silence gap (before the first interval, after the last, or in
 * a pause between occurrences).
 */
export function findActiveAt(
    units: AnimUnit[],
    sorted: SortedInterval[],
    t: number,
    last: number,
): ActiveHit | null {
    const n = units.length;
    if (n === 0) return null;
    // Fast path: same unit as last frame, or the next unit. Covers the common
    // forward-playback case in O(1) — no allocation, no bsearch.
    for (const cand of [last, last + 1]) {
        if (cand < 0 || cand >= n) continue;
        const u = units[cand]!;
        for (const iv of u.intervals) {
            if (t >= iv.start && t < iv.end) {
                return { unitIdx: cand, ivStart: iv.start, ivEnd: iv.end, waslTo: iv.waslTo };
            }
        }
    }
    // Fallback: bsearch the flat sorted interval list. Handles seek-back,
    // silence gaps, and repeats where a later reading-order unit's first
    // occurrence has not yet started but an earlier unit's repeat has.
    if (sorted.length === 0 || t < sorted[0]!.start) return null;
    let lo = 0;
    let hi = sorted.length - 1;
    while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (sorted[mid]!.start <= t) lo = mid;
        else hi = mid - 1;
    }
    const iv = sorted[lo]!;
    if (t < iv.end) {
        return { unitIdx: iv.unitIdx, ivStart: iv.start, ivEnd: iv.end, waslTo: iv.waslTo };
    }
    return null;
}

/**
 * The first occurrence interval that STARTS strictly after `t` — i.e. the next
 * unit to be recited once the current silence ends. Used to resolve which verse
 * a between-verse pause is heading toward (so the filmstrip can scroll across
 * the gap instead of freezing). Returns `null` past the last interval.
 */
export function nextIntervalAfter(sorted: SortedInterval[], t: number): SortedInterval | null {
    if (sorted.length === 0 || t >= sorted[sorted.length - 1]!.start) return null;
    let lo = 0;
    let hi = sorted.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (sorted[mid]!.start > t) hi = mid;
        else lo = mid + 1;
    }
    const iv = sorted[lo]!;
    return iv.start > t ? iv : null;
}
