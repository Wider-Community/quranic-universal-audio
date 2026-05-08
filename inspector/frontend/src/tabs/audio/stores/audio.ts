/**
 * Audio tab — shared playback element store.
 */

import { writable } from 'svelte/store';

import { AudioPort } from '../../../lib/playback/audio-port';

/** The <audio> element driving audio-tab playback. Set by AudioTab on mount;
 *  cleared to null on destroy. Consumers null-check before use.
 *
 *  @deprecated Use `audPort` instead. The element is now wrapped by the
 *  port; this export is retained transitionally. */
export const audAudioElement = writable<HTMLAudioElement | null>(null);

/** Audio tab AudioPort. The Audio tab plays full files via standard
 *  `<audio>` controls, no VBR clip routing — the port is here for
 *  uniformity with the segments + timestamps tabs and to give App.svelte
 *  a single tab-switch pause path. */
export const audPort: AudioPort = new AudioPort();

export const audPortReady = writable<boolean>(false);
