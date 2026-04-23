/**
 * Cross-tab helper for fetching segment-level waveform peaks via the
 * `/api/seg/segment-peaks/<reciter>` endpoint (ffmpeg + HTTP Range, disk-cached).
 *
 * The Segments tab has its own observer-batched fetch path in
 * `tabs/segments/utils/waveform/utils.ts`. This helper is for ad-hoc
 * single-slice fetches (e.g. the Timestamps tab loading one verse at a time).
 *
 * The backend route is reciter-agnostic for URL validation — `reciter` only
 * scopes the disk-cache directory, so any URL/range can be requested.
 */

import { fetchJson } from '../api';
import type { SegSegmentPeaksResponse } from '../types/api';
import type { SegmentPeaks } from '../types/domain';

export interface FetchSegmentPeaksOptions {
    /** When true, server returns null instead of computing on a cache miss. */
    cachedOnly?: boolean;
}

/**
 * Fetch peaks for a single audio slice. Returns the slice peaks, or null if
 * the backend declined (e.g. cached_only miss, ffmpeg failure, empty range).
 */
export async function fetchSegmentPeaks(
    reciter: string,
    url: string,
    startMs: number,
    endMs: number,
    opts: FetchSegmentPeaksOptions = {},
): Promise<SegmentPeaks | null> {
    if (!reciter || !url || endMs <= startMs) return null;
    const data = await fetchJson<SegSegmentPeaksResponse>(
        `/api/seg/segment-peaks/${reciter}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                segments: [{ url, start_ms: startMs, end_ms: endMs }],
                cached_only: opts.cachedOnly ?? false,
            }),
        },
    );
    const key = `${url}:${startMs}:${endMs}`;
    return data.peaks?.[key] ?? null;
}
