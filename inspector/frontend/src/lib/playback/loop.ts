/**
 * Shared region-loop state for the recitation player.
 *
 * Lives in `lib/` (not `tabs/timestamps`) so BOTH the shared footer (prev/next
 * surah, ayah seek buttons) and the now-reciting filmstrip — which are lib
 * components — can clear the loop, alongside the timestamps tab's own keyboard /
 * shuffle handlers. The timestamps playback store re-exports these so existing
 * `../stores/playback` imports keep working.
 *
 * While `loopTarget` is non-null the timestamps tab's rAF watcher repeats
 * `[startSec, endSec)` (verse-local seconds) and the region stays highlighted.
 * Any deliberate navigation (seek, surah/ayah change, filmstrip click, shuffle)
 * calls `exitLoop()` to drop out of loop mode.
 */
import { writable } from 'svelte/store';

export interface TsLoopTarget {
    kind: 'word' | 'letter' | 'phoneme';
    /** Slice-relative (verse-local) seconds. */
    startSec: number;
    endSec: number;
    /** Owning word index (flat). Set even for letter/phoneme targets. */
    wordIndex: number;
    /** For 'letter': index within word.letters. For 'phoneme': flat intervals index. */
    childIndex?: number;
}

export const loopTarget = writable<TsLoopTarget | null>(null);

/** Force-exit loop mode (no-op when not looping). */
export function exitLoop(): void {
    loopTarget.set(null);
}
