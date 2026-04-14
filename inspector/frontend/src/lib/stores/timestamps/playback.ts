/**
 * Timestamps tab — playback control state.
 *
 * Split from Stage-1 `state.tsAutoMode`, `state.tsAutoAdvancing`, and
 * per-frame playhead position. `currentTime` is updated by the animation
 * loop in `TimestampsTab.svelte`; consumers (UnifiedDisplay, AnimationDisplay,
 * TimestampsWaveform) use it imperatively via `get($currentTime)` for 60fps
 * work — stores themselves are not the hot path, the value they hold is.
 */

import { writable } from 'svelte/store';

/** Auto-advance mode — null = off, 'next' = advance to next verse on end,
 *  'random' = load random verse on end. */
export type TsAutoMode = 'next' | 'random' | null;

/** Current auto-advance mode. */
export const autoMode = writable<TsAutoMode>(null);

/** Guard against re-entry from the timeupdate handler when the end is crossed. */
export const autoAdvancing = writable<boolean>(false);

/** Audio element current time (seconds, absolute). Updated per animation frame. */
export const currentTime = writable<number>(0);

/** Playing state — derived from the AudioElement's play/pause events. */
export const isPlaying = writable<boolean>(false);
