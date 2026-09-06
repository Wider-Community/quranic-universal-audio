/**
 * Play-URL resolver — the ONE place that decides whether a chapter MP3 is
 * loaded straight from its CDN or through the same-origin audio-proxy.
 *
 * Why this exists: every chapter used to be wrapped in
 * `/api/seg/audio-proxy/<reciter>?url=…` so the `<audio crossorigin="anonymous">`
 * element (routed through Web Audio's `MediaElementAudioSourceNode`) always
 * saw an `Access-Control-Allow-Origin` header. That routes the whole
 * multi-minute MP3 through the single-worker Space, and from far-away
 * clients (AU / Middle East ↔ US Space) that pipe runs at ~300-500 KB/s —
 * the browser's read-ahead on a 60 MB chapter then starves every other
 * request multiplexed on the same HTTP/2 connection (small JSON calls
 * queue for 5-10 s). Most published CDNs (tarteel / mp3quran / quranicaudio /
 * way2quran / archive.org) already send `ACAO: *` + Range from an edge near
 * the user, so playing them directly is both faster and off the Space.
 *
 * Contract:
 * - `probeDirectPlayable(url)` asks the CDN once per host (`Range: bytes=0-0`,
 *   CORS mode) and caches the verdict. Direct requires a 206 — Range support
 *   is what makes seeking work — and a CORS-readable response (a missing
 *   ACAO rejects the fetch, which is exactly the case where the element
 *   would play silence).
 * - `playUrl(reciter, url)` is the SYNC decision used at `setSource` time:
 *   direct when the host is known-good, proxy otherwise (unknown hosts stay
 *   on the proxy — never silence). Callers that can `await` should probe
 *   first (chapter load, shuffle prime) so the first play already goes direct.
 * - Same-origin (`/api/...`) and non-http (`qua-sample://`) URLs always pass
 *   through the proxy wrapper unchanged / wrapped, respectively.
 *
 * The proxy string shape is unchanged so `normalizeAudioUrl` / `audioSrcMatches`
 * keep treating proxied and direct forms of one chapter as the same resource.
 */

/** host → true when the CDN answered a CORS Range probe with 206. */
const _hostDirect = new Map<string, boolean>();
const _inflight = new Map<string, Promise<boolean>>();

/** Build the same-origin proxy URL for a chapter MP3. Already-proxied
 *  (`/api/...`) URLs and empty strings pass through untouched. */
export function proxyPlayUrl(reciter: string, url: string): string {
    if (!url || url.startsWith('/api/')) return url;
    return `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(url)}`;
}

/** The cross-origin http(s) host of `url`, or null when it isn't one
 *  (same-origin path, `qua-sample://`, malformed). */
function _crossOriginHost(url: string): string | null {
    if (!url || url.startsWith('/')) return null;
    try {
        const u = new URL(url, globalThis.location?.origin ?? 'http://localhost');
        if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
        if (globalThis.location && u.origin === globalThis.location.origin) return null;
        return u.host;
    } catch {
        return null;
    }
}

/** True when `url`'s host has already passed the CORS + Range probe. */
export function isDirectPlayable(url: string): boolean {
    const host = _crossOriginHost(url);
    return !!host && _hostDirect.get(host) === true;
}

/** Probe `url`'s host once (cached, coalesced). Resolves true when the CDN
 *  can be played directly. Never throws — a network / CORS failure is a
 *  `false` verdict and the caller falls back to the proxy. */
export function probeDirectPlayable(url: string): Promise<boolean> {
    const host = _crossOriginHost(url);
    if (!host) return Promise.resolve(false);
    const known = _hostDirect.get(host);
    if (known !== undefined) return Promise.resolve(known);
    const pending = _inflight.get(host);
    if (pending) return pending;

    const probe = fetch(url, {
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        headers: { Range: 'bytes=0-0' },
    })
        .then((res) => {
            // Drain so the connection is reusable; the body is one byte.
            void res.body?.cancel().catch(() => {});
            return res.status === 206;
        })
        .catch(() => false)
        .then((ok) => {
            _hostDirect.set(host, ok);
            _inflight.delete(host);
            return ok;
        });
    _inflight.set(host, probe);
    return probe;
}

/** Sync resolution: direct CDN URL when its host is known-good, else the
 *  proxy wrapper. Safe to call before any probe — unknown = proxy. */
export function playUrl(reciter: string, url: string): string {
    return isDirectPlayable(url) ? url : proxyPlayUrl(reciter, url);
}

/** Probe-then-resolve for callers that can await (chapter load, prewarm). */
export async function resolvePlayUrl(reciter: string, url: string): Promise<string> {
    await probeDirectPlayable(url);
    return playUrl(reciter, url);
}

/** Test hook: forget every probe verdict. */
export function _resetPlayUrlForTest(): void {
    _hostDirect.clear();
    _inflight.clear();
}
