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
 *                / `chapterStartMs`). The lower-bound walk relies on this
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
