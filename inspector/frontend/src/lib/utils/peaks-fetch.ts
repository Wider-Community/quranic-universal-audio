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
import type { SegPeaksResponse, SegSegmentPeaksRequest, SegSegmentPeaksResponse } from '../types/generated/schemas';
import type { AudioPeaks, PeakBucket, SegmentPeaks } from '../types/peaks-transport';
import { b64ToInt8 } from './peaks-decode';
import { normalizeAudioUrl, setWaveformPeaks } from './waveform-cache';

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
    const item = data.peaks?.[key];
    if (!item) return null;
    // The wire `peaks` are `[min, max]` float pairs (codegen types the tuple
    // element opaquely as `[unknown, unknown][]`).
    return {
        peaks: (item.peaks ?? []) as PeakBucket[],
        start_ms: item.start_ms,
        end_ms: item.end_ms,
        duration_ms: item.duration_ms,
    };
}

// ---------------------------------------------------------------------------
// Baked chapter peaks (the FAST path) — slim 10bps int8 chapter overview,
// server-cached + sliced client-side. This is what the Segments tab uses
// (_fetchPeaks) and what the Timestamps waveform now prefers over the per-verse
// ffmpeg fallback above. ~6KB/chapter, decode ~0.175ms once/chapter, then each
// verse is a ~2µs array slice (vs 289-762ms ffmpeg).
// ---------------------------------------------------------------------------

/** Bounded in-flight + result cache keyed by `${reciter}:${chapter}` — NOT by
 *  audio URL, so FE-derived URL drift (e.g. https-prepend vs the raw sidecar
 *  URL the route keys by) can never make the lookup silently miss. */
const CHAPTER_PEAKS_CACHE = 8;
const _chapterPeaks = new Map<string, Promise<Record<string, AudioPeaks>>>();

/**
 * Fetch + decode the baked slim chapter peaks for one chapter, returning the
 * decoded `{audioUrl: AudioPeaks}` map (one entry for by_surah, one-per-verse
 * for by_ayah). Concurrent calls for the same chapter dedupe via the in-flight
 * promise. Returns an empty map when the chapter has no baked peaks (the caller
 * then falls through to the ffmpeg `fetchSegmentPeaks` path).
 *
 * The `?h=` cache-buster is intentionally omitted: TS doesn't know the audio
 * URL list up front and released-reciter audio is frozen, so the route's
 * 1-day `Cache-Control` is safe. Decode goes through the shared `b64ToInt8`.
 */
export function ensureChapterPeaks(
    reciter: string,
    chapter: number,
): Promise<Record<string, AudioPeaks>> {
    const key = `${reciter}:${chapter}`;
    const hit = _chapterPeaks.get(key);
    if (hit) return hit;
    const promise = (async () => {
        const data = await fetchJson<SegPeaksResponse>(
            `/api/seg/peaks/${encodeURIComponent(reciter)}?chapters=${chapter}`,
        );
        const out: Record<string, AudioPeaks> = {};
        for (const [url, raw] of Object.entries(data.peaks ?? {})) {
            const env = raw as unknown as {
                q?: string; n?: number; peaks_b64?: string; duration_ms?: number;
            };
            if (env.q !== 'int8' || typeof env.peaks_b64 !== 'string' || typeof env.n !== 'number') {
                continue;
            }
            const ap: AudioPeaks = {
                peaks: b64ToInt8(env.peaks_b64, env.n),
                duration_ms: env.duration_ms ?? 0,
            };
            out[url] = ap;
            // Also populate the cross-tab URL-keyed cache (harmless; lets any
            // URL-keyed consumer hit). TS lookups go through pickChapterPeaks.
            if (url) setWaveformPeaks(url, ap);
        }
        return out;
    })();
    _chapterPeaks.set(key, promise);
    promise.catch(() => _chapterPeaks.delete(key)); // allow retry on failure
    while (_chapterPeaks.size > CHAPTER_PEAKS_CACHE) {
        const oldest = _chapterPeaks.keys().next().value;
        if (oldest === undefined || oldest === key) break;
        _chapterPeaks.delete(oldest);
    }
    return promise;
}

/**
 * Pick the chapter-peaks entry for a verse out of an {@link ensureChapterPeaks}
 * map. by_surah chapters yield exactly one entry (the whole chapter) → used
 * directly, immune to URL drift. by_ayah chapters yield one entry per verse →
 * matched on the verse's audio URL (proxy-normalised). Returns null when
 * nothing matches; the caller falls back to the ffmpeg `/segment-peaks` path.
 */
export function pickChapterPeaks(
    map: Record<string, AudioPeaks>,
    audioUrl: string,
): AudioPeaks | null {
    const entries = Object.values(map);
    if (entries.length === 1) return entries[0]!;
    if (entries.length === 0) return null;
    const want = normalizeAudioUrl(audioUrl);
    for (const [url, ap] of Object.entries(map)) {
        if (normalizeAudioUrl(url) === want) return ap;
    }
    return null;
}

// ---------------------------------------------------------------------------
// Shared ffmpeg-fallback cache (the SECOND tier) — for reciters/chapters with
// no baked chapter peaks (un-backfilled, pre-publish, by_ayah without a match,
// and ALL reciters on a dev bucket that has no peaks/*.json.gz). Module-level
// so a prewarm and the later render hit the SAME entry — without this the
// waveform's per-instance LRU made the fallback impossible to warm ahead of a
// jump. Keyed by reciter+url+window so it survives across verse/chapter swaps.
// ---------------------------------------------------------------------------
const SEGMENT_PEAKS_CACHE = 12;
const _segmentPeaks = new Map<string, Promise<SegmentPeaks | null>>();

function _segKey(reciter: string, url: string, startMs: number, endMs: number, bps?: number): string {
    return `${reciter}:${url}:${startMs}:${endMs}:${bps ?? ''}`;
}

/**
 * Fetch the ffmpeg-fallback peaks for a single verse window, de-duped + cached
 * at module scope so a prewarm and the subsequent render share the result.
 * Thin idempotent wrapper over {@link fetchSegmentPeaks}; returns null (and
 * does not cache) on empty/failed fetches so the next call retries.
 */
export function ensureSegmentPeaks(
    reciter: string,
    url: string,
    startMs: number,
    endMs: number,
    chapter?: number,
    bps?: number,
): Promise<SegmentPeaks | null> {
    if (!reciter || !url || endMs <= startMs) return Promise.resolve(null);
    const key = _segKey(reciter, url, startMs, endMs, bps);
    const hit = _segmentPeaks.get(key);
    if (hit) return hit;
    const promise = fetchSegmentPeaks(reciter, url, startMs, endMs, chapter, bps);
    _segmentPeaks.set(key, promise);
    // Drop empty/failed results so they don't pin a permanent miss.
    promise.then((v) => { if (!v || !v.peaks?.length) _segmentPeaks.delete(key); })
        .catch(() => _segmentPeaks.delete(key));
    while (_segmentPeaks.size > SEGMENT_PEAKS_CACHE) {
        const oldest = _segmentPeaks.keys().next().value;
        if (oldest === undefined || oldest === key) break;
        _segmentPeaks.delete(oldest);
    }
    return promise;
}

/**
 * Prewarm a verse's peaks into the caches the TS waveform render reads. The TS
 * waveform paints the baked chapter slice as an instant placeholder and then
 * upgrades to the HD ffmpeg peaks (`reactToVerse`), so we warm BOTH: the baked
 * chapter overview (cheap, one shared GET/chapter) and the per-verse HD ffmpeg
 * window. Fire-and-forget from a look-ahead (next sequential verse / shuffle
 * target) so the post-jump render AND its HD upgrade are both cache hits.
 * `startMs`/`endMs` MUST match the render's window (round of the verse's
 * time_start_ms/time_end_ms).
 */
export async function prewarmVersePeaks(
    reciter: string,
    chapter: number,
    url: string,
    startMs: number,
    endMs: number,
): Promise<void> {
    if (!reciter || !chapter) return;
    void ensureChapterPeaks(reciter, chapter).catch(() => {}); // placeholder tier
    await ensureSegmentPeaks(reciter, url ?? '', startMs, endMs, chapter).catch(() => {}); // HD upgrade
}

/** Test seam — clears the chapter- and segment-peaks caches. */
export function _resetChapterPeaksForTests(): void {
    _chapterPeaks.clear();
    _segmentPeaks.clear();
}
