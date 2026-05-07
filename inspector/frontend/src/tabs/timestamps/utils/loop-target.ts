/**
 * Shared helpers for the Timestamps loop feature.
 *
 * `findWordAt` is used by the waveform click/hover paths and the Loop toggle
 * (which needs to resolve the word containing `audio.currentTime` when first
 * engaging the loop).
 */

import type { TsWord } from '../../../lib/types/domain';

/**
 * Find the word covering `time`. When `clamp` is true (click / toggle path),
 * falls back to the first/last word when `time` lies outside the verse. When
 * false (hover path), returns null for inter-word silence.
 */
export function findWordAt(
    time: number,
    words: TsWord[],
    clamp: boolean,
): TsWord | null {
    if (!words.length) return null;
    for (const w of words) {
        if (time >= w.start && time < w.end) return w;
    }
    if (!clamp) return null;
    const first = words[0];
    const last = words[words.length - 1];
    if (first && time < first.start) return first;
    if (last) return last;
    return null;
}
