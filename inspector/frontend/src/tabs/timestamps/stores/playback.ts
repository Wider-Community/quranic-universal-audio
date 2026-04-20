/**
 * Timestamps tab — playback control state.
 */

import { writable } from 'svelte/store';

/** Auto-advance mode — null = off, 'next' = advance to next verse on end,
 *  'random-any' = load random verse from any reciter on end,
 *  'random-current' = load random verse from the currently-selected reciter on end. */
export type TsAutoMode = 'next' | 'random-any' | 'random-current' | null;

/** Current auto-advance mode. */
export const autoMode = writable<TsAutoMode>(null);

/** Guard against re-entry from the timeupdate handler when the end is crossed. */
export const autoAdvancing = writable<boolean>(false);

/** Audio element current time (seconds, absolute). Updated per animation frame. */
export const currentTime = writable<number>(0);

/** The <audio> element driving timestamps-tab playback. Set by TimestampsAudio
 *  on mount; cleared to null on destroy. Consumers null-check before use. */
export const tsAudioElement = writable<HTMLAudioElement | null>(null);

/**
 * Looped element. While non-null, playback repeats `[startSec, endSec)` on
 * every rAF frame (see TimestampsAudio._tick) and the region is permanently
 * highlighted on the waveform + in the analysis/animation pane. Mutually
 * exclusive with autoMode — toggling either one clears the other.
 *
 * Same-target detection uses `kind + wordIndex + childIndex` (no float compares).
 */
export interface TsLoopTarget {
    kind: 'word' | 'letter' | 'phoneme';
    /** Slice-relative seconds. */
    startSec: number;
    endSec: number;
    /** Owning word index (flat). Set even for letter/phoneme targets. */
    wordIndex: number;
    /** For 'letter': index within word.letters. For 'phoneme': flat intervals index. */
    childIndex?: number;
}
export const loopTarget = writable<TsLoopTarget | null>(null);
