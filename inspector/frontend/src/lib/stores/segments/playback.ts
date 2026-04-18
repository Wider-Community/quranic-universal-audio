/**
 * Segments tab — playback control state.
 */

import { writable } from 'svelte/store';

/**
 * Whether auto-play (continuous segment advance) is enabled.
 * Persisted to localStorage via LS_KEYS.SEG_AUTOPLAY.
 */
export const autoPlayEnabled = writable<boolean>(
    localStorage.getItem('insp_seg_autoplay') !== 'false',
);

/** Whether continuous-play (auto-advance to next segment after one ends) is
 *  currently engaged. Short-lived — toggled per play session, not persisted. */
export const continuousPlay = writable<boolean>(false);

/** Timestamp (ms, within the current audio source) at which the current
 *  play-range should stop. Written when starting a segment or range; read by
 *  the rAF tick to decide when to pause. */
export const playEndMs = writable<number>(0);

/** Which audio element is currently driving playback: 'main' = the main
 *  segments tab audio element, 'error' = the error-card audio element, or
 *  `null` when idle. */
export const activeAudioSource = writable<'main' | 'error' | null>(null);

/** The <audio> element driving segments-tab playback. Populated by
 *  SegmentsAudioControls.svelte via bind:this once AudioPlayer mounts.
 *  Consumers read via get(segAudioElement) and null-check. */
export const segAudioElement = writable<HTMLAudioElement | null>(null);

/** The #seg-list scroll container. Populated by SegmentsList.svelte via
 *  bind:this. Consumers read via get(segListElement) and null-check. */
export const segListElement = writable<HTMLDivElement | null>(null);

/** Current playback speed multiplier. Persisted to localStorage via
 *  LS_KEYS.SEG_SPEED. SegmentsAudioControls' speed <select> writes to it;
 *  hot paths that need to set audioEl.playbackRate read via
 *  get(playbackSpeed). */
export const playbackSpeed = writable<number>(1);

/** Status text rendered in the #seg-play-status span. Reactive markup in
 *  SegmentsAudioControls. */
export const playStatusText = writable<string>('');

/** Label on the main play/pause button. Reactive markup in
 *  SegmentsAudioControls. */
export const playButtonLabel = writable<'Play' | 'Pause'>('Play');
