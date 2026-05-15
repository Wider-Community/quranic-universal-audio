/**
 * Pure helper that translates the timestamps-tab's `(loadedVerse, loopTarget)`
 * state into the `{range, policy}` shape the unified `AudioRange` primitive
 * consumes.
 *
 * Two regimes:
 *   - `loopTarget` set → loop policy, range is the loop window in absolute
 *     seconds (`startSec + tsSegOffset` … `endSec + tsSegOffset`).
 *   - otherwise        → stop policy, range ends at `tsSegEnd` (or +∞ when
 *     `tsSegEnd <= 0`, i.e. no clamp configured).
 *
 * The two regimes are mutually exclusive — see `loopTarget` doc comment in
 * `stores/playback.ts`.
 */

import type { AudioRangeSpec, RangePolicy } from '../../../lib/playback/audio-range';
import type { TsLoopTarget } from '../stores/playback';
import type { TsLoadedVerse } from '../stores/verse';

export interface TimestampsRangeSpec {
    range: AudioRangeSpec;
    policy: RangePolicy;
}

export function buildTimestampsRangeSpec(
    loadedVerse: TsLoadedVerse | null,
    loopTarget: TsLoopTarget | null,
): TimestampsRangeSpec | null {
    if (!loadedVerse) return null;

    if (loopTarget) {
        const startMs = (loopTarget.startSec + loadedVerse.tsSegOffset) * 1000;
        const endMs = (loopTarget.endSec + loadedVerse.tsSegOffset) * 1000;
        return {
            range: { startMs, endMs },
            policy: { kind: 'loop' },
        };
    }

    // tsSegEnd <= 0 means "no clamp configured" — pass +∞ so the boundary
    // check never trips, but the rAF loop still runs (caller wants per-frame
    // currentTime store updates and karaoke-tick dispatch).
    const endMs = loadedVerse.tsSegEnd > 0 ? loadedVerse.tsSegEnd * 1000 : Number.POSITIVE_INFINITY;
    return {
        range: { startMs: 0, endMs },
        policy: { kind: 'stop' },
    };
}
