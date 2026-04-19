/**
 * Timestamps tab — playback control state.
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

/** The <audio> element driving timestamps-tab playback. Set by TimestampsAudio
 *  on mount; cleared to null on destroy. Consumers null-check before use. */
export const tsAudioElement = writable<HTMLAudioElement | null>(null);
