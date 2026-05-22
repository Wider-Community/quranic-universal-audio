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
import type { SegSegmentPeaksRequest, SegSegmentPeaksResponse } from '../types/api';
import type { SegmentPeaks } from '../types/domain';

/**
 * Fetch peaks for a single audio slice via the ffmpeg + HTTP-Range fallback
 * endpoint (``/api/seg/segment-peaks/<reciter>``). This is the single fallback
 * tier when chapter-overview peaks aren't available — chapter peaks load via
 * ``_fetchPeaks`` (slim int8 envelope) and FE slices them locally; this
 * helper only fires when there's no chapter peaks to slice.
 *
 * Returns the slice peaks (nested float ``PeakBucket[]``), or null if the
 * backend couldn't produce them (ffmpeg failure, empty range, unknown URL).
 *
 * ``bps`` (buckets per second) defaults to the backend's HD 30. The History
 * tab passes 10 to match the chapter overview + the persisted
 * ``edit_history_peaks.jsonl`` (cheaper compute, and the write-back record is
 * already 10 bps).
 */
export async function fetchSegmentPeaks(
    reciter: string,
    url: string,
    startMs: number,
    endMs: number,
    chapter?: number,
    bps?: number,
): Promise<SegmentPeaks | null> {
    if (!reciter || !url || endMs <= startMs) return null;
    const body: SegSegmentPeaksRequest = {
        segments: [{ url, start_ms: startMs, end_ms: endMs, chapter, bps }],
    };
    const data = await fetchJson<SegSegmentPeaksResponse>(
        `/api/seg/segment-peaks/${reciter}`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        },
    );
    const key = `${url}:${startMs}:${endMs}`;
    return data.peaks?.[key] ?? null;
}
