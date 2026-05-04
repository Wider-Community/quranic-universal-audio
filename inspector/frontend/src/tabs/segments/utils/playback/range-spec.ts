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

import type { Segment } from '../../../../lib/types/domain';
import type { AudioRangeSpec, RangePolicy } from '../../../../lib/playback/audio-range';
import { AUTOPLAY_GAP_PAUSE_MS } from '../constants';
import { nextDisplayedSeg } from './prefetch';

export function buildSegRangeSpec(seg: Segment, seekToMs?: number | null): AudioRangeSpec {
    return {
        startMs: seekToMs ?? seg.time_start,
        endMs: seg.time_end,
        src: seg.audio_url || null,
    };
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
