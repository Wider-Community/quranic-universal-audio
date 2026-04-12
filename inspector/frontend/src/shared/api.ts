/**
 * Single fetch boundary for the inspector frontend.
 *
 * All Flask `/api/*` requests go through one of these helpers so we have a
 * consistent typing surface. Binary audio decoder fetches use
 * `fetchArrayBuffer`; cache pre-warm fetches in playback code keep using
 * raw `fetch()` (they intentionally store the Response Promise without
 * consuming the body).
 *
 * `fetchJson` deliberately does NOT throw on non-2xx responses — the Flask
 * routes return `jsonify({error: "..."})` with a non-2xx status, and callers
 * check `data.error`. A strict variant can be added later if wanted.
 */

export class ApiError extends Error {
    readonly url: string;
    readonly status: number;
    readonly body: string;

    constructor(url: string, status: number, body: string) {
        super(`API ${status} ${url}${body ? `: ${body.slice(0, 200)}` : ''}`);
        this.name = 'ApiError';
        this.url = url;
        this.status = status;
        this.body = body;
    }
}

/**
 * GET/POST JSON — parses the response body regardless of status code.
 *
 * Matches the legacy `fetch(url).then(r => r.json())` pattern: callers that
 * care about error responses inspect the returned payload's `error` field.
 */
export async function fetchJson<T = unknown>(url: string, init?: RequestInit): Promise<T> {
    const res = await fetch(url, init);
    return (await res.json()) as T;
}

/**
 * Like `fetchJson` but returns `null` on non-2xx — use for endpoints where
 * "not found" is a meaningful response (e.g. edit-history before first save).
 */
export async function fetchJsonOrNull<T = unknown>(
    url: string,
    init?: RequestInit,
): Promise<T | null> {
    const res = await fetch(url, init);
    if (!res.ok) return null;
    return (await res.json()) as T;
}

/** Fetch raw bytes — used by the audio decoder paths for verse/segment audio. */
export async function fetchArrayBuffer(url: string, init?: RequestInit): Promise<ArrayBuffer> {
    const res = await fetch(url, init);
    if (!res.ok) {
        const body = await res.text().catch(() => '');
        throw new ApiError(url, res.status, body);
    }
    return res.arrayBuffer();
}
