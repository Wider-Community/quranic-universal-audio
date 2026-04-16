/**
 * Audio prefetch for the next displayed segment.
 *
 * Extracted from segments/playback/index.ts (Ph5). Reads displayed segments
 * and prefetch cache from the imperative `state` object and uses `audioSrcMatches`
 * from lib/utils/audio to compare URLs.
 */

import type { Segment } from '../../../types/domain';
import { audioSrcMatches } from '../audio';

/**
 * Find the next displayed segment after the given index.
 * Returns null if the index is not found or is the last segment.
 */
export function nextDisplayedSeg(
    displayedSegments: Segment[] | null,
    afterIndex: number,
): Segment | null {
    if (!displayedSegments) return null;
    const pos = displayedSegments.findIndex(s => s.index === afterIndex);
    if (pos >= 0 && pos < displayedSegments.length - 1) {
        return displayedSegments[pos + 1] ?? null;
    }
    return null;
}

/**
 * Prefetch the audio for the next segment after `currentIndex`.
 * Skips if the next segment shares the same audio URL as the current one
 * or if it has already been prefetched.
 */
export function prefetchNextSegAudio(
    displayedSegments: Segment[] | null,
    currentIndex: number,
    currentAudioSrc: string,
    prefetchCache: Record<string, Promise<unknown>>,
): void {
    const next = nextDisplayedSeg(displayedSegments, currentIndex);
    if (!next) return;
    if (!next.audio_url || audioSrcMatches(next.audio_url, currentAudioSrc)) return;
    if (next.audio_url in prefetchCache) return;
    prefetchCache[next.audio_url] = fetch(next.audio_url)
        .then(r => r.blob())
        .catch(() => {});
}
