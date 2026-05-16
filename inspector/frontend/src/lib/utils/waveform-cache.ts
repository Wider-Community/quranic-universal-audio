/**
 * Non-reactive waveform peaks cache for the Segments tab.
 *
 * Stores chapter-wide AudioPeaks keyed by canonical (non-proxy) audio URL.
 * Uses a plain module-scope Map<string, AudioPeaks> — NOT a Svelte store —
 * because waveform data is write-once-per-chapter and never observed reactively.
 *
 * ## Proxy URL normalization
 *
 * The audio-proxy rewrites CDN URLs to `/api/seg/audio-proxy/<reciter>?url=<enc>`.
 * Every URL is normalized to its canonical (CDN/server) form before use as a
 * cache key so reads always hit regardless of which form the caller provides.
 */

import type { AudioPeaks } from '../types/domain';

// ---------------------------------------------------------------------------
// URL normalisation
// ---------------------------------------------------------------------------

/**
 * Strip the audio-proxy wrapper, returning the underlying CDN/server URL.
 *
 * Proxy format: `/api/seg/audio-proxy/<reciter>?url=<percent-encoded-original>`
 *
 * If the URL is already canonical (not a proxy URL), return it unchanged.
 * This makes normalizeAudioUrl() safe to call on any URL.
 */
export function normalizeAudioUrl(url: string): string {
    // Match the proxy form whether the URL is relative (`/api/seg/...`) or
    // absolute (`http://host/api/seg/...`). audioEl.src returns the resolved
    // absolute form even when set via a relative href, so the regex must
    // tolerate both — otherwise audioSrcMatches misses the proxy ↔ canonical
    // equivalence and downstream logic (seg-on-audio detection, autoplay
    // gap advance) silently falls back to non-matching paths.
    const m = url.match(/\/api\/seg\/audio-proxy\/[^?]+\?url=(.+)/);
    return (m && m[1]) ? decodeURIComponent(m[1]) : url;
}

// ---------------------------------------------------------------------------
// Cache store
// ---------------------------------------------------------------------------

const _cache = new Map<string, AudioPeaks>();

/**
 * Look up peaks for an audio URL.
 * Accepts either a canonical URL or a proxy URL — both resolve to the same key.
 */
export function getWaveformPeaks(url: string): AudioPeaks | undefined {
    return _cache.get(normalizeAudioUrl(url));
}

/**
 * Store peaks for an audio URL.
 * Always indexes under the canonical URL so proxy-URL lookups hit.
 */
export function setWaveformPeaks(url: string, peaks: AudioPeaks): void {
    _cache.set(normalizeAudioUrl(url), peaks);
}

/**
 * Invalidate a single URL's cache entry (pass the canonical or proxy form).
 * If `url` is omitted, clears the entire cache.
 */
export function invalidateWaveformCache(url?: string): void {
    if (url === undefined) {
        _cache.clear();
    } else {
        _cache.delete(normalizeAudioUrl(url));
    }
}

/**
 * Clear the entire waveform peaks cache.
 * Convenience alias for `invalidateWaveformCache()` with no argument.
 */
export function clearWaveformCache(): void {
    _cache.clear();
}

