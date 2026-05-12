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
 */

import { AudioPort } from './audio-port';

export const dashPort: AudioPort = new AudioPort();
