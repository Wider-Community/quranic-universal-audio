/**
 * Lenient URL helpers for contributor-supplied audio links.
 *
 * A scheme is NOT required — `cdn.example/001.mp3` is a fine URL and defaults
 * to `https://`. We only reject genuine non-URLs (whitespace, non-http schemes,
 * or a host without a dot). Mirrors `qua_shared/schemas/intake_requests.py`
 * `normalize_url` + the backend `_is_plausible_url`. Not a reachability check.
 */

const SCHEME_RE = /^[a-z][a-z0-9+.-]*:\/\//i;

/** Make a user-typed URL absolute (default scheme https). */
export function normalizeUrl(raw: string | null | undefined): string {
    const u = (raw ?? '').trim();
    if (!u) return u;
    if (SCHEME_RE.test(u)) return u;
    if (u.startsWith('//')) return `https:${u}`;
    return `https://${u}`;
}

/** True if `raw` is a fetchable-looking http(s) web address (scheme optional). */
export function isPlausibleUrl(raw: string | null | undefined): boolean {
    const u = (raw ?? '').trim();
    if (!u || /\s/.test(u)) return false;
    try {
        const url = new URL(normalizeUrl(u));
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
        return url.hostname.includes('.') && url.hostname.length > 3;
    } catch {
        return false;
    }
}
