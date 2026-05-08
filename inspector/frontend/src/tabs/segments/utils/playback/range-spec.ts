/**
 * Pure helpers translating segments-tab playback state into the
 * `{range, policy}` shape the unified `AudioRange` primitive consumes.
 *
 * Two regimes:
 *   - Main-list play (accordion === false) → `advance` policy with
 *     `gapMs = AUTOPLAY_GAP_PAUSE_MS` and a nextRange resolver that checks
 *     `getAutoPlayEnabled()` live so toggling autoplay mid-segment takes
 *     effect at the very next boundary without rebuilding the range.
 *   - Accordion play → `stop` policy. Autoplay is intentionally main-list
 *     only; accordion plays always stop at `time_end`.
 *
 * Coordinate space: file-absolute milliseconds throughout. The `AudioPort`
 * owns CBR vs VBR transport (chapter URL vs server-clip URL) and offset
 * bookkeeping; this module produces specs the port consumes verbatim.
 */

import { get } from 'svelte/store';

import type { AudioRangeSpec, RangePolicy } from '../../../../lib/playback/audio-range';
import type { Segment } from '../../../../lib/types/domain';
import { reciterVbrChapters, selectedReciter } from '../../stores/chapter';
import { AUTOPLAY_GAP_PAUSE_MS } from '../constants';
import { nextDisplayedSeg } from './resolvers';

/** Build the per-play `AudioRangeSpec` for a segment. File-absolute ms
 *  throughout — `AudioPort` translates to clip-relative `currentTime`
 *  internally for VBR clips. */
export function buildSegRangeSpec(seg: Segment, seekToMs?: number | null): AudioRangeSpec {
    return {
        startMs: seekToMs ?? seg.time_start,
        endMs: seg.time_end,
    };
}

/** Resolve a per-segment clip URL for a [startMs, endMs] window if `chapter`
 *  is VBR for the active reciter, else null. Used by the prefetch path —
 *  accordion validation cards (e.g. MissingVersesCard boundary segments)
 *  can render rows from chapters other than the active one, and the
 *  per-reciter VBR map decides clip-vs-chapter routing per sibling without
 *  routing each candidate through `segData.vbr`. */
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
    return buildClipUrl(reciter, seg.audio_url, seg.time_start, seg.time_end);
}

interface NextRangeOptions {
    /** The displayed slice at advance-time. Re-resolved each boundary, so
     *  a filter change between segments takes effect on the very next gap. */
    getDisplayed: () => Segment[] | null;
    /** Index of the segment whose boundary we're advancing FROM. */
    currentIndex: number;
}

export function resolveSegNextRange({ getDisplayed, currentIndex }: NextRangeOptions): AudioRangeSpec | null {
    const displayed = getDisplayed();
    if (!displayed) return null;
    const next = nextDisplayedSeg(displayed, currentIndex);
    // Only consecutive segments auto-advance — keep the current "+1 index"
    // contract so a filter that hides intermediate rows doesn't jump
    // unexpectedly across the gap.
    if (!next || next.index !== currentIndex + 1) return null;
    return buildSegRangeSpec(next);
}

export interface BuildSegPolicyOptions {
    /** Live getter so toggling autoplay mid-segment takes effect at the next
     *  boundary without rebuilding the AudioRange. */
    getAutoPlayEnabled: () => boolean;
    isAccordionPlay: boolean;
    /** Read the index of the segment whose boundary is firing, lazily.
     *  Must be a getter because the policy outlives a single segment —
     *  AudioRange reuses the same policy across N consecutive boundary
     *  fires during an autoplay run, and a stale captured index would
     *  resolve to the same "next" segment every time and loop forever. */
    getCurrentIndex: () => number;
    getDisplayed: () => Segment[] | null;
}

export function buildSegPolicy(opts: BuildSegPolicyOptions): RangePolicy {
    if (opts.isAccordionPlay) {
        return { kind: 'stop' };
    }
    return {
        kind: 'advance',
        gapMs: AUTOPLAY_GAP_PAUSE_MS,
        nextRange: () => {
            if (!opts.getAutoPlayEnabled()) return null;
            return resolveSegNextRange({
                getDisplayed: opts.getDisplayed,
                currentIndex: opts.getCurrentIndex(),
            });
        },
    };
}
