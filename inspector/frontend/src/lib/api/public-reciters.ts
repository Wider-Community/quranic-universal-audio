/**
 * Public reciter API client — read-only fetchers for ``/api/public/*``.
 *
 * No auth required. All endpoints emit Cache-Control: public, max-age=30
 * so a returning visitor or CDN absorbs repeats.
 *
 * Slice E of phase 6.
 */

import type { BucketCounts, PublicReciterPage } from '../types/generated/schemas';
import type { PublicBucket } from '../types/public-bucket';

export interface FetchRecitersOpts {
    bucket?: readonly PublicBucket[];
    search?: string;
    sort?: 'recent' | 'alphabetical' | 'deliveries';
    cursor?: number;
    limit?: number;
    signal?: AbortSignal;
}

export async function fetchPublicReciters(
    opts: FetchRecitersOpts = {},
): Promise<PublicReciterPage> {
    const params = new URLSearchParams();
    for (const b of opts.bucket ?? []) params.append('bucket', b);
    if (opts.search) params.set('search', opts.search);
    if (opts.sort) params.set('sort', opts.sort);
    if (opts.cursor !== undefined) params.set('cursor', String(opts.cursor));
    if (opts.limit !== undefined) params.set('limit', String(opts.limit));

    const qs = params.toString();
    const url = `/api/public/reciters${qs ? `?${qs}` : ''}`;
    const resp = await fetch(url, { signal: opts.signal });
    if (!resp.ok) {
        throw new Error(`fetchPublicReciters: HTTP ${resp.status}`);
    }
    return (await resp.json()) as PublicReciterPage;
}

export async function fetchPublicStats(signal?: AbortSignal): Promise<BucketCounts> {
    const resp = await fetch('/api/public/stats', { signal });
    if (!resp.ok) {
        throw new Error(`fetchPublicStats: HTTP ${resp.status}`);
    }
    return (await resp.json()) as BucketCounts;
}

/**
 * Monotonic catalog version (`db_seq`) — a cheap change-probe the dashboard
 * poll fetches each tick to decide whether the full roster needs refetching.
 */
export async function fetchCatalogVersion(signal?: AbortSignal): Promise<number> {
    const resp = await fetch('/api/public/version', { signal });
    if (!resp.ok) {
        throw new Error(`fetchCatalogVersion: HTTP ${resp.status}`);
    }
    const body = (await resp.json()) as { db_seq: number };
    return body.db_seq;
}
