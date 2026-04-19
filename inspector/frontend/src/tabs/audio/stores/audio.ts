/**
 * Audio tab — shared playback element store.
 */

import { writable } from 'svelte/store';

/** The <audio> element driving audio-tab playback. Set by AudioTab on mount;
 *  cleared to null on destroy. Consumers null-check before use. */
export const audAudioElement = writable<HTMLAudioElement | null>(null);
