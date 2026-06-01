/**
 * Infer reciter waqf (stop) word-refs from MFA timestamps.
 *
 * MFA-aligned timestamps are gapless within a continuous breath group — the
 * end_ms of one phone touches the start_ms of the next — and only carry a
 * real gap where the reciter actually paused. We use that signal directly:
 * for each consecutive word pair where the next word's start is later than
 * this word's end, the reciter stopped at this word, so we emit its location
 * as a `stop_ref` for the phonemizer.
 *
 * Output drives `/api/ts/tajweed/<verse_ref>?stops=...` so that cross-word
 * tajweed rules (idgham etc.) are correctly suppressed where the reciter
 * paused. No extra bucket read — the per-word timings are already in the
 * shard the FE just loaded.
 *
 * `> 0` (not a noise threshold): MFA output is deterministic ms-rounded, so
 * a real pause produces a positive integer gap and a continuous transition
 * produces exactly zero. Adding a threshold would falsely keep idgham over
 * sub-perceptible pauses the reciter still treated as one breath.
 */

import type { TsWord } from '../../../lib/types/domain';

/** Locations (`surah:ayah:word`) of every word the reciter stopped on. */
export function stopRefsFromGaps(words: readonly TsWord[]): string[] {
    const stops: string[] = [];
    for (let i = 0; i < words.length - 1; i++) {
        const a = words[i];
        const b = words[i + 1];
        if (!a || !b) continue;
        if (b.start > a.end) {
            stops.push(a.location);
        }
    }
    return stops;
}
