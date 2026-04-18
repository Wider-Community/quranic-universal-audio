/**
 * Segments tab — playback control state.
 *
 * Kept minimal: only the one field that SegmentsAudioControls.svelte needs
 * reactively for its button class binding. All other playback fields
 * (continuous-play, play-end-ms, current-idx, anim-id, prefetch cache)
 * stay on `state.*` — they are written and read exclusively by imperative
 * code (playback/index.ts, keyboard.ts, event-delegation.ts) and moving
 * them to stores during the Wave 5-10 interim creates a two-way bridge
 * problem since Svelte can't observe `state.X = Y` mutations from those hot
 * paths.
 *
 * NOTE: timestamps/playback.ts holds auto-mode + auto-advancing + currentTime
 * because TimestampsTab.svelte owns the entire timestamps playback lifecycle.
 * Segments playback lifecycle spans many imperative modules (Wave 6-10); full
 * migration happens Wave-by-wave. `createPlaybackStore()` factoring (S2-D33)
 * was evaluated and rejected: segments continuous-play differs enough from
 * timestamps auto-next that a shared factory adds abstraction cost for no
 * concrete gain. See Wave 6a handoff §12 for details.
 */

import { writable } from 'svelte/store';

/**
 * Whether auto-play (continuous segment advance) is enabled.
 * Persisted to localStorage via LS_KEYS.SEG_AUTOPLAY.
 *
 * SegmentsAudioControls.svelte reads this to set the autoplay button class.
 * segments/index.ts DOMContentLoaded handler now reads the initial value from
 * here instead of constructing it inline.
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
