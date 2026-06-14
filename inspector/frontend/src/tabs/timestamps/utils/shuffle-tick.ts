/**
 * Pure per-frame decision for the Timestamps tab's auto-random ("shuffle")
 * boundary, split out of `TimestampsTab`'s rAF tick so the contiguous-seam
 * overshoot race is unit-testable without rAF / audio / store plumbing.
 *
 * Ayahs recited continuously are contiguous (verse N's end == verse N+1's
 * start), so the playhead crosses a seam with no gap. Each frame the tick must
 * decide whether to FIRE the shuffle jump (the auditioned ayah just ended)
 * BEFORE it advances the visual focus — otherwise a frame that overshoots the
 * seam (heavy repaint right after a jump starves rAF, most visible when the
 * just-loaded ayah is short) would re-base the boundary onto the NEXT ayah and
 * leak it in full. Resolving the fire decision first, against the auditioned
 * ayah's captured end, bounds the leak to a single frame.
 */

export interface ShuffleTickVerse {
    ref: string;
    startMs: number;
    endMs: number;
}

export type ShuffleTickOutcome =
    | { kind: 'fire' }
    | { kind: 'focus'; ref: string | null };

export interface ShuffleFireArgs {
    /** Shuffle is engaged on the active tab and not overridden by a region loop. */
    armed: boolean;
    /** Playhead, chapter-absolute ms. */
    ms: number;
    /** End of the ayah currently being auditioned (chapter-absolute ms), or null
     *  when no verse is loaded. */
    focusEndMs: number | null;
    /** Fire this many ms before the exact end so the jump lands without a beat of
     *  the next ayah leaking in. */
    guardMs: number;
    /** True once the jump has already fired for the ayah in focus (once-per-ayah
     *  guard). */
    firedForCurrentFocus: boolean;
}

/** The ayah-end fire predicate: armed, the auditioned ayah's end is known, it
 *  hasn't already fired for that ayah, and the playhead has reached within
 *  `guardMs` of — or PAST — its end. The `>=` makes the guard a LOWER bound, so
 *  an overshoot (a skipped frame) still fires; that is the property the leak bug
 *  violated by re-measuring against the next ayah after focus had advanced. */
export function shouldFireShuffle(args: ShuffleFireArgs): boolean {
    const { armed, ms, focusEndMs, guardMs, firedForCurrentFocus } = args;
    if (!armed || focusEndMs === null || firedForCurrentFocus) return false;
    return ms >= focusEndMs - guardMs;
}

/** The verse to focus for playhead `ms`: the one containing it, else the nearest
 *  preceding, else the first. Returns its ref, or null when there are no verses. */
export function verseAt(verses: ShuffleTickVerse[], ms: number): string | null {
    if (verses.length === 0) return null;
    let hit: ShuffleTickVerse | null = null;
    for (const v of verses) {
        if (ms >= v.startMs && ms < v.endMs) { hit = v; break; }
        if (v.startMs <= ms) hit = v; // nearest preceding
    }
    return (hit ?? verses[0]!).ref;
}

/** Combined tick decision: fire the shuffle jump if the auditioned ayah ended,
 *  otherwise report which verse to focus. Firing is resolved BEFORE focus so an
 *  overshoot past a contiguous seam still measures against the auditioned ayah,
 *  never the next one. */
export function resolveShuffleTick(
    args: ShuffleFireArgs & { verses: ShuffleTickVerse[] },
): ShuffleTickOutcome {
    if (shouldFireShuffle(args)) return { kind: 'fire' };
    return { kind: 'focus', ref: verseAt(args.verses, args.ms) };
}
