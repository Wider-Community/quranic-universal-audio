import type { AudioPeaks } from '../../../../lib/types/peaks-transport';
import { getWaveformPeaks, normalizeAudioUrl } from '../../../../lib/utils/waveform-cache';
import type { SegPeaksRangeEntry } from '../../types/segments';

// ---------------------------------------------------------------------------
// Module-local peaks-by-url store
//
// Keys are always the *canonical* (proxy-stripped) URL. Stream-mode segment
// peaks come back from the server keyed by whichever form was POSTed — and
// History snapshots store whatever `audio_url` the segment had at edit time
// (often the proxy form). Normalising on both write and read makes proxy
// vs canonical interchangeable, matching `lib/utils/waveform-cache.ts`.
// ---------------------------------------------------------------------------

let _segPeaksByUrl: Record<string, SegPeaksRangeEntry[]> | null = null;

/** Push a segment-level peaks entry into the covering-range cache. */
export function pushSegPeaksEntry(url: string, entry: SegPeaksRangeEntry): void {
    if (!_segPeaksByUrl) _segPeaksByUrl = {};
    const key = normalizeAudioUrl(url);
    if (!_segPeaksByUrl[key]) _segPeaksByUrl[key] = [];
    _segPeaksByUrl[key]!.push(entry);
}

/** Drop all segment-level peaks — called on reciter change. */
export function clearSegPeaksCache(): void {
    _segPeaksByUrl = null;
}

/**
 * Find covering peaks for a given audio URL and optional time range.
 * First checks the chapter-wide waveform cache, then falls back to
 * segment-level peaks in the covering-range cache.
 */
export function _findCoveringPeaks(
    audioUrl: string,
    startMs?: number | null,
    endMs?: number | null,
): AudioPeaks | null {
    const pe = getWaveformPeaks(audioUrl);
    if (pe && pe.peaks && pe.peaks.length > 0) return pe;
    if (startMs != null && endMs != null && _segPeaksByUrl) {
        const entries = _segPeaksByUrl[normalizeAudioUrl(audioUrl)];
        if (entries) {
            for (const entry of entries) {
                if (entry.startMs <= startMs && entry.endMs >= endMs) {
                    return { peaks: entry.peaks, duration_ms: entry.durationMs, start_ms: entry.startMs };
                }
            }
        }
    }
    return null;
}
