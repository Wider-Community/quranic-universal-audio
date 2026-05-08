/**
 * Audio prefetch for the next displayed / accordion segment.
 *
 * Two transport paths:
 *
 *  - **CBR**: warms the chapter audio URL. Useful only when the next segment
 *    actually points at a different audio file from the current one — for
 *    consecutive same-chapter segments the URL matches and we skip.
 *  - **VBR**: warms the per-segment clip URL (`/api/seg/segment-clip/...`).
 *    Each clip endpoint hits ffmpeg `-ss/-t`, so a speculative `fetch()`
 *    while the user is still on the previous segment hides the ~200–400 ms
 *    spin-up before the next play.
 *
 *  The endpoint sets `Cache-Control: public, max-age=…, immutable`, so a
 *  bare fetch warms the browser HTTP cache; the subsequent `audio.src=…`
 *  is served from cache.
 *
 *  Two "next" resolvers — chapter-mode advances by `Segment.index + 1` in
 *  the displayed slice; accordion-mode advances by *list position* in the
 *  card's rendered sibling list (which may not be index-sorted, e.g. a
 *  context window around an issue, and may span chapters).
 */

import type { Segment } from '../../../../lib/types/domain';
import { audioSrcMatches } from '../../../../lib/utils/audio';
import { vbrClipForChapter } from './range-spec';
import { nextDisplayedSeg, nextSiblingSeg } from './resolvers';

// Re-export for the existing import sites. The resolvers themselves live in
// `./resolvers` so range-spec can also use them without an import cycle.
export { nextDisplayedSeg, nextSiblingSeg } from './resolvers';

/**
 * Prefetch the audio for the next segment in `list` after the row identified
 * by (`currentChapter`, `currentIndex`).
 *
 * For VBR siblings the clip URL is fetched (per-reciter VBR map decides);
 * for CBR siblings the chapter audio URL is fetched, skipping when it
 * matches `currentAudioSrc` (the common consecutive-same-chapter case).
 *
 * If `currentChapter` is null the function falls back to chapter-mode
 * resolution by `Segment.index + 1` (legacy callers that haven't been
 * migrated to pass a chapter pointer).
 */
export function prefetchNextSegAudio(
    list: Segment[] | null,
    currentIndex: number,
    currentAudioSrc: string,
    prefetchCache: Record<string, Promise<unknown>>,
    currentChapter: number | null = null,
): void {
    const next = currentChapter != null
        ? nextSiblingSeg(list, currentChapter, currentIndex)
        : nextDisplayedSeg(list, currentIndex);
    if (!next || !next.audio_url) return;

    // VBR path: prefetch the clip URL keyed off the *next* sibling's chapter,
    // so cross-chapter accordion rows get the right encoding routing.
    const nextChapter = next.chapter;
    if (nextChapter != null) {
        const clip = vbrClipForChapter(nextChapter, next.audio_url, next.time_start, next.time_end);
        if (clip) {
            if (clip.clipUrl in prefetchCache) return;
            prefetchCache[clip.clipUrl] = fetch(clip.clipUrl)
                .then(r => r.blob())
                .catch(() => {});
            return;
        }
    }

    // CBR path: warm the chapter URL. Skips when the next segment shares the
    // current segment's audio (no useful warming) or when already cached.
    if (audioSrcMatches(next.audio_url, currentAudioSrc)) return;
    if (next.audio_url in prefetchCache) return;
    prefetchCache[next.audio_url] = fetch(next.audio_url)
        .then(r => r.blob())
        .catch(() => {});
}
