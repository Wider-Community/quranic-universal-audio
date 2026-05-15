/**
 * Shared audio playback utilities.
 */

import { normalizeAudioUrl } from './waveform-cache';

/**
 * Call audio.play() and swallow AbortError — fired when src changes or
 * pause() interrupts a pending play() promise. Non-abort errors still throw.
 */
export function safePlay(audioEl: HTMLAudioElement): Promise<void> | undefined {
    const p = audioEl.play();
    if (p && typeof p.catch === 'function') {
        p.catch((e: unknown) => {
            if (e && (e as { name?: string }).name !== 'AbortError') throw e;
        });
    }
    return p;
}

/**
 * True if `src` and `target` refer to the same underlying audio resource.
 *
 * Accepts either side as a canonical URL or as a Flask audio-proxy wrapper
 * (`/api/seg/audio-proxy/<reciter>?url=<percent-encoded-canonical>`); both
 * normalize to the canonical CDN URL before comparison. Also tolerates the
 * relative-vs-origin-absolute mismatch (`/foo.mp3` vs `http://host/foo.mp3`)
 * via a bidirectional `endsWith` check.
 */
export function audioSrcMatches(src: string | null | undefined, target: string | null | undefined): boolean {
    if (!src || !target) return false;
    if (src === target) return true;
    const a = normalizeAudioUrl(src);
    const b = normalizeAudioUrl(target);
    if (a === b) return true;
    return a.endsWith(b) || b.endsWith(a);
}
