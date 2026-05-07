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
import { segData, selectedReciter } from '../../stores/chapter';
import { AUTOPLAY_GAP_PAUSE_MS } from '../constants';
import { nextDisplayedSeg } from './prefetch';

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
    const data = get(segData);
    const reciter = get(selectedReciter);
    const segDurMs = Math.max(0, seg.time_end - seg.time_start);

    if (data?.vbr && reciter && seg.audio_url) {
        const clipUrl = buildSegmentClipUrl(reciter, seg);
        const seekClipMs = seekToMs != null
            ? Math.max(0, Math.min(segDurMs, seekToMs - seg.time_start))
            : 0;
        return {
            startMs: seekClipMs,
            endMs: segDurMs,
            src: clipUrl,
            clipFileOffsetMs: seg.time_start,
        };
    }

    return {
        startMs: seekToMs ?? seg.time_start,
        endMs: seg.time_end,
        src: seg.audio_url || null,
    };
}

/** Construct the `/api/seg/segment-clip/<reciter>?…` URL for a segment.
 *  Deterministic on (url, start_ms, end_ms) so the browser HTTP cache
 *  absorbs repeat plays of the same segment. */
export function buildSegmentClipUrl(reciter: string, seg: Segment): string {
    const params = new URLSearchParams({
        url: seg.audio_url,
        start_ms: String(seg.time_start),
        end_ms: String(seg.time_end),
    });
    return `/api/seg/segment-clip/${encodeURIComponent(reciter)}?${params.toString()}`;
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
