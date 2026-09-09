/**
 * play-url.ts — direct-CDN vs audio-proxy resolution.
 *
 * The verdict is per host and cached; an unknown host is proxied (never
 * silence), a 206 CORS probe flips it to direct, anything else keeps the
 * proxy. Same-origin and non-http URLs never probe.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    _resetPlayUrlForTest,
    isDirectPlayable,
    playUrl,
    probeDirectPlayable,
    proxyPlayUrl,
    resolvePlayUrl,
} from '../play-url';

const CDN = 'https://audio-cdn.example.com/quran/husary/002.mp3';
const CDN_SIBLING = 'https://audio-cdn.example.com/quran/husary/003.mp3';
const PROXIED = `/api/seg/audio-proxy/husary?url=${encodeURIComponent(CDN)}`;

let fetchMock: ReturnType<typeof vi.fn>;

function respond(status: number): void {
    fetchMock.mockImplementation(() => Promise.resolve(new Response(null, { status })));
}

beforeEach(() => {
    _resetPlayUrlForTest();
    fetchMock = vi.fn();
    respond(206);
    vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('proxyPlayUrl', () => {
    it('wraps a cross-origin URL and passes /api/ and empty through', () => {
        expect(proxyPlayUrl('husary', CDN)).toBe(PROXIED);
        expect(proxyPlayUrl('husary', '/api/seg/clip/x')).toBe('/api/seg/clip/x');
        expect(proxyPlayUrl('husary', '')).toBe('');
    });
});

describe('playUrl before any probe', () => {
    it('returns the proxy wrapper for an unprobed host', () => {
        expect(isDirectPlayable(CDN)).toBe(false);
        expect(playUrl('husary', CDN)).toBe(PROXIED);
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('probeDirectPlayable', () => {
    it('sends one CORS Range probe and flips the host to direct on 206', async () => {
        await expect(probeDirectPlayable(CDN)).resolves.toBe(true);
        expect(fetchMock).toHaveBeenCalledOnce();
        const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }];
        expect(url).toBe(CDN);
        expect(init.mode).toBe('cors');
        expect(init.headers.Range).toBe('bytes=0-0');
        expect(playUrl('husary', CDN)).toBe(CDN);
    });

    it('caches the verdict per host — a sibling chapter does not re-probe', async () => {
        await probeDirectPlayable(CDN);
        await probeDirectPlayable(CDN_SIBLING);
        expect(fetchMock).toHaveBeenCalledOnce();
        expect(playUrl('husary', CDN_SIBLING)).toBe(CDN_SIBLING);
    });

    it('coalesces concurrent probes of one host into a single fetch', async () => {
        await Promise.all([probeDirectPlayable(CDN), probeDirectPlayable(CDN_SIBLING)]);
        expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('keeps the proxy when the CDN answers 200 (no Range support)', async () => {
        respond(200);
        await expect(probeDirectPlayable(CDN)).resolves.toBe(false);
        expect(playUrl('husary', CDN)).toBe(PROXIED);
    });

    it('keeps the proxy when the CORS fetch rejects (no ACAO)', async () => {
        fetchMock.mockImplementation(() => Promise.reject(new TypeError('Failed to fetch')));
        await expect(probeDirectPlayable(CDN)).resolves.toBe(false);
        expect(playUrl('husary', CDN)).toBe(PROXIED);
        // Negative verdicts are cached too — no re-probe storm on every play.
        await probeDirectPlayable(CDN);
        expect(fetchMock).toHaveBeenCalledOnce();
    });

    it('never probes same-origin or non-http URLs', async () => {
        await expect(probeDirectPlayable('/api/seg/clip/x')).resolves.toBe(false);
        await expect(probeDirectPlayable('qua-sample://abc/1')).resolves.toBe(false);
        await expect(probeDirectPlayable('')).resolves.toBe(false);
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('resolvePlayUrl', () => {
    it('probes then returns the direct URL on 206', async () => {
        await expect(resolvePlayUrl('husary', CDN)).resolves.toBe(CDN);
    });

    it('probes then returns the proxy on failure', async () => {
        respond(403);
        await expect(resolvePlayUrl('husary', CDN)).resolves.toBe(PROXIED);
    });
});
