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
 */

import { get } from 'svelte/store';

import type { AudioRangeSpec, RangePolicy } from '../../../../lib/playback/audio-range';
import type { Segment } from '../../../../lib/types/domain';
import { reciterVbrChapters, segData, selectedReciter } from '../../stores/chapter';
import { AUTOPLAY_GAP_PAUSE_MS } from '../constants';
import { nextDisplayedSeg } from './resolvers';

/** Build the per-play `AudioRangeSpec` for a segment.
 *
 *  Two regimes — chosen at call time from `$segData.vbr`:
 *
 *  - **CBR (default)**: spec is file-absolute. `startMs/endMs` map straight
 *    to the segment's time window in the chapter audio; the audio element
 *    seeks to `startMs/1000` and the rAF compares `currentTime` directly
 *    against `endMs`.
 *
 *  - **VBR**: spec points at the server clip endpoint (a per-segment MP3
 *    extracted with `ffmpeg -ss/-t` from the source). The clip plays from
 *    byte 0, so `startMs/endMs` are clip-relative (`0..segDur`) and
 *    `clipFileOffsetMs = seg.time_start` lets the rAF tick recover
 *    file-absolute time for the playhead and segment-detection callers.
 *    `seekToMs` is mapped into the clip space (`seekToMs - seg.time_start`).
 *
 *  The VBR routing piggybacks on the existing src-swap path in
 *  `audio-range.ts:_loadAndStart` — every play in a VBR chapter swaps the
 *  audio element's src to a per-segment clip URL.
 */
export function buildSegRangeSpec(seg: Segment, seekToMs?: number | null): AudioRangeSpec {
    return buildRangePlaybackSpec(seg.audio_url, seg.time_start, seg.time_end, seekToMs);
}

/** Build an AudioRangeSpec for an arbitrary [startMs, endMs] window of a
 *  chapter audio URL. The single VBR-routing primitive — used by segment
 *  playback, edit-mode preview (trim/split), History panel, and SavePreview.
 *
 *  CBR: returns a file-absolute spec pointing at the chapter URL.
 *
 *  VBR: returns a clip-relative spec pointing at the segment-clip endpoint
 *  for the requested window. The clip plays from byte 0; `clipFileOffsetMs`
 *  lets `AudioRange.getCurrentTimeMs()` and the rAF tick recover file-absolute
 *  time for playhead drawing and segment-detection.
 *
 *  Reads `$segData.vbr` and `$selectedReciter` from the segments stores —
 *  these are populated as soon as the chapter loads, before any playback can
 *  start, so an unset value here means we genuinely don't know the chapter's
 *  encoding (treat as CBR — the no-regression default). */
export function buildRangePlaybackSpec(
    audioUrl: string,
    startMs: number,
    endMs: number,
    seekToMs?: number | null,
): AudioRangeSpec {
    const data = get(segData);
    const reciter = get(selectedReciter);
    const durMs = Math.max(0, endMs - startMs);

    if (data?.vbr && reciter && audioUrl) {
        const clipUrl = buildClipUrl(reciter, audioUrl, startMs, endMs);
        const seekClipMs = seekToMs != null
            ? Math.max(0, Math.min(durMs, seekToMs - startMs))
            : 0;
        return {
            startMs: seekClipMs,
            endMs: durMs,
            src: clipUrl,
            clipFileOffsetMs: startMs,
        };
    }

    return {
        startMs: seekToMs ?? startMs,
        endMs,
        src: audioUrl || null,
    };
}

/** Resolve the active chapter's clip URL for a [startMs, endMs] window if
 *  the chapter is VBR, else null. Useful for callers (`_playRange`,
 *  `_seekFromCanvasEvent`) that don't go through `AudioRange` and need to
 *  drive the audio element directly. Returns null in the CBR fast path so
 *  callers can keep their existing chapter-audio + currentTime logic. */
export function vbrClipFor(
    audioUrl: string,
    startMs: number,
    endMs: number,
): { clipUrl: string; fileOffsetMs: number } | null {
    const data = get(segData);
    const reciter = get(selectedReciter);
    if (!data?.vbr || !reciter || !audioUrl) return null;
    return {
        clipUrl: buildClipUrl(reciter, audioUrl, startMs, endMs),
        fileOffsetMs: startMs,
    };
}

/** Same as {@link vbrClipFor}, but consults the per-reciter VBR chapter map
 *  instead of the active chapter's `segData.vbr`. Used by prefetch when the
 *  next sibling may live in a different chapter from the one currently
 *  playing — accordion validation cards (e.g. MissingVersesCard boundary
 *  segments) can render rows from chapters other than the active one, and
 *  routing each candidate through `segData.vbr` would force the active
 *  chapter's encoding onto every sibling. */
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
