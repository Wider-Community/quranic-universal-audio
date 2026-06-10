/**
 * Per-segment clip URL builders for VBR transport routing.
 *
 * The autoplay range/policy builders that lived here were removed when the
 * Segments tab switched to chapter-continuous playback (chapter audio plays
 * through; the active row highlight follows the playhead via
 * `onSegTimeUpdate`'s time→segment scan). What remains is the per-segment
 * clip URL builder, still used by:
 *   - `vbrClipForChapter` — accordion validation cards (e.g. MissingVersesCard
 *     boundary segments) may render rows from chapters other than the active
 *     one; the per-reciter VBR map decides clip-vs-chapter routing per sibling.
 *   - `buildSegmentClipUrl` — convenience wrapper taking a Segment-shaped
 *     input; retained because the existing tests (and any future Segment-
 *     keyed callers) still need it.
 *
 * Coordinate space: file-absolute milliseconds throughout.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { reciterVbrChapters, selectedReciter } from '../../stores/chapter';

/** Resolve a per-segment clip URL for a [startMs, endMs] window if `chapter`
 *  is VBR for the active reciter, else null. */
export function vbrClipForChapter(
    chapter: number,
    audioUrl: string,
    startMs: number,
    endMs: number,
): { clipUrl: string; fileOffsetMs: number } | null {
    const reciter = get(selectedReciter);
    const vbrSet = get(reciterVbrChapters);
    if (!reciter || !audioUrl || !vbrSet?.has(chapter)) return null;
    return {
        clipUrl: buildClipUrl(reciter, audioUrl, startMs, endMs),
        fileOffsetMs: startMs,
    };
}

/** Construct the `/api/seg/segment-clip/<reciter>?…` URL.
 *  Deterministic on (url, start_ms, end_ms) so the browser HTTP cache
 *  absorbs repeat plays of the same range. */
export function buildClipUrl(reciter: string, audioUrl: string, startMs: number, endMs: number): string {
    const params = new URLSearchParams({
        url: audioUrl,
        start_ms: String(startMs),
        end_ms: String(endMs),
    });
    return `/api/seg/segment-clip/${encodeURIComponent(reciter)}?${params.toString()}`;
}

/** @deprecated Use {@link buildClipUrl}. Kept as a thin alias because the
 *  existing tests (and any future callers needing a Segment-shaped input)
 *  still want a per-segment helper. */
export function buildSegmentClipUrl(reciter: string, seg: Segment): string {
    return buildClipUrl(reciter, seg.audio_url ?? '', seg.time_start, seg.time_end);
}
