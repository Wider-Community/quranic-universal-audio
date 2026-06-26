/**
 * Ayah-boundary seek target.
 *
 * For published (timestamped) playback the footer's seek-back/-forward buttons
 * and the ←/→ keyboard jump between ayah starts instead of a fixed ±Ns.
 *
 *   - forward: the next ayah's start (null when already in the last ayah).
 *   - back:    restart the current ayah if more than `restartMs` into it,
 *              otherwise the previous ayah's start (media-player convention).
 *
 * @param starts  Ayah start times (ms, chapter-absolute). MUST be ascending —
 *                callers pass a memoised sorted list (see `recitationAyahStarts`
 *                / `distinctVerseStartMs`). The lower-bound walk relies on this
 *                ordering (the `else break` short-circuits on a sorted miss).
 * @param curMs   Chapter-absolute playhead (ms).
 * @param dir     +1 forward, -1 back.
 * @returns Chapter-absolute target ms, or null when there's nowhere to go.
 */
export function adjacentAyahStartMs(
    starts: number[],
    curMs: number,
    dir: 1 | -1,
    restartMs = 1500,
): number | null {
    if (!starts.length) return null;

    // Current ayah = last start at/below the playhead (1ms tolerance).
    let ci = -1;
    for (let i = 0; i < starts.length; i++) {
        if (starts[i]! <= curMs + 1) ci = i;
        else break;
    }

    if (dir > 0) {
        const ni = ci + 1;
        return ni < starts.length ? starts[ni]! : null; // already in last ayah
    }

    // Back.
    if (ci <= 0) return starts[0]!; // before/in the first ayah → its start
    const curStart = starts[ci]!;
    if (curMs - curStart > restartMs) return curStart; // restart current
    return starts[ci - 1]!; // previous ayah
}

/**
 * Ayah-boundary seek target, anchored on a KNOWN current-ayah index rather than
 * inferred from start ordering.
 *
 * The position-based `adjacentAyahStartMs` infers the current ayah from the last
 * start at/below the playhead — wrong inside a re-take (a loopback / re-do) whose
 * audio plays AFTER a later verse's canonical start, so the playhead reads as
 * that later verse and prev/next skip. When the recitation locator can resolve
 * which verse is actually being recited, pass its index here for an exact step.
 *
 * @param starts  Ascending ayah start times (ms, chapter-absolute).
 * @param ci      Index (into `starts`) of the ayah being recited now.
 * @param curMs   Chapter-absolute playhead (ms).
 * @param dir     +1 forward, -1 back.
 * @returns Chapter-absolute target ms, or null when there's nowhere to go.
 */
export function adjacentAyahStartFromIndex(
    starts: number[],
    ci: number,
    curMs: number,
    dir: 1 | -1,
    restartMs = 1500,
): number | null {
    if (!starts.length || ci < 0 || ci >= starts.length) return null;

    if (dir > 0) {
        const ni = ci + 1;
        return ni < starts.length ? starts[ni]! : null;
    }

    if (ci <= 0) return starts[0]!;
    const curStart = starts[ci]!;
    // Inside a re-take, `curMs` can be far past the canonical start; restart the
    // current verse (its canonical pass) rather than dropping to the previous.
    if (curMs - curStart > restartMs) return curStart;
    return starts[ci - 1]!;
}

/**
 * The ayah start nearest to `ms` (magnetic snap). Used when dragging the linear
 * progress bar so a release lands on an ayah start, never mid-ayah. `starts` is
 * the list of chapter-absolute ayah start times (ms). Returns null when empty so
 * the caller can fall back to the raw drag target (non-timestamped playback).
 */
export function nearestAyahStartMs(starts: number[], ms: number): number | null {
    if (!starts.length) return null;
    let best = starts[0]!;
    let bestD = Math.abs(ms - best);
    for (let i = 1; i < starts.length; i++) {
        const d = Math.abs(ms - starts[i]!);
        if (d < bestD) {
            bestD = d;
            best = starts[i]!;
        }
    }
    return best;
}
