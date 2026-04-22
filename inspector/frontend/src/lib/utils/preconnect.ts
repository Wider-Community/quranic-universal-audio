/**
 * Pre-warm cross-origin TCP/TLS connections for audio CDNs.
 *
 * The first audio play in a session pays a full DNS+TLS+TCP handshake to
 * the CDN (server10.mp3quran.net etc). After idle, that connection closes
 * and the next play pays it again. Injecting `<link rel="preconnect">`
 * for the reciter's audio origins as soon as the reciter is selected
 * lets the browser open the connection in the background, so it's warm
 * by the time Play is clicked.
 *
 * Tracks injected origins so reciter switches diff the set instead of
 * leaking <link> tags. Omits the `crossorigin` attribute because the
 * <audio> element fetches without CORS — adding it would mismatch the
 * actual request's credentials mode and the browser would open a second
 * connection anyway.
 */

const _injected = new Set<string>();
const _ATTR = 'data-preconnect-origin';

function _originOf(url: string): string | null {
    if (!url) return null;
    if (url.startsWith('/') || url.startsWith('blob:') || url.startsWith('data:')) return null;
    try {
        const u = new URL(url);
        if (u.origin === window.location.origin) return null;
        return u.origin;
    } catch {
        return null;
    }
}

/**
 * Ensure a `<link rel="preconnect">` exists for every cross-origin URL's
 * origin in `urls`, and remove links for origins not in the new set.
 * Same-origin and relative URLs are ignored.
 */
export function preconnectOrigins(urls: Iterable<string>): void {
    const wanted = new Set<string>();
    for (const url of urls) {
        const o = _originOf(url);
        if (o) wanted.add(o);
    }
    for (const origin of _injected) {
        if (wanted.has(origin)) continue;
        const link = document.head.querySelector(`link[${_ATTR}="${origin}"]`);
        if (link) link.remove();
        _injected.delete(origin);
    }
    for (const origin of wanted) {
        if (_injected.has(origin)) continue;
        const link = document.createElement('link');
        link.rel = 'preconnect';
        link.href = origin;
        link.setAttribute(_ATTR, origin);
        document.head.appendChild(link);
        _injected.add(origin);
    }
}

/** Drop all injected preconnect links. */
export function clearPreconnects(): void {
    preconnectOrigins([]);
}
