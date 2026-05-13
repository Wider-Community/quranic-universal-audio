/**
 * Dashboard-tab AudioPort instance.
 *
 * Mirrors the per-tab pattern used by `audPort` (audio tab),
 * `segPort` (segments tab), and `tsPort` (timestamps tab). No global
 * port — each tab owns its element + transport so tab-switching
 * cleanly pauses one without touching the others.
 *
 * Dashboard plays full chapter MP3s (no VBR clip routing); the port
 * is here for transport uniformity and for App.svelte's tab-switch
 * pause path.
 *
 * Kill-switch is intentionally disabled. The dashboard hits chapter
 * URLs through `/api/seg/audio-proxy/...` which returns 302 to the
 * source CDN when the bucket prefetch hasn't covered the slug — every
 * un-prefetched reciter in dashboard browsing. Constructing a
 * `MediaElementAudioSourceNode` on a cross-origin element silences
 * playback per the Web Audio spec (no CORS approval on the CDN
 * response). Full-chapter playback doesn't need sample-accurate end-
 * of-region cutoff, so we keep the element on its default audio sink.
 */

import { AudioPort } from './audio-port';

export const dashPort: AudioPort = new AudioPort({ disableKillSwitch: true });
