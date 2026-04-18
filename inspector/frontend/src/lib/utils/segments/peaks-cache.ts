import type { AudioPeaks } from '../../../types/domain';
import type { SegPeaksRangeEntry } from '../../types/segments';
import { getWaveformPeaks } from '../waveform-cache';

// ---------------------------------------------------------------------------
// Module-local peaks-by-url store (was state._segPeaksByUrl)
// ---------------------------------------------------------------------------

let _segPeaksByUrl: Record<string, SegPeaksRangeEntry[]> | null = null;

/** Push a segment-level peaks entry into the covering-range cache. */
export function pushSegPeaksEntry(url: string, entry: SegPeaksRangeEntry): void {
    if (!_segPeaksByUrl) _segPeaksByUrl = {};
    if (!_segPeaksByUrl[url]) _segPeaksByUrl[url] = [];
    _segPeaksByUrl[url]!.push(entry);
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
        const entries = _segPeaksByUrl[audioUrl];
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
