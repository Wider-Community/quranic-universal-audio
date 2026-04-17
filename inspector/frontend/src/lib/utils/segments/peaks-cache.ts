import type { AudioPeaks } from '../../../types/domain';
import { state } from '../../segments-state';
import { getWaveformPeaks } from '../waveform-cache';

/**
 * Find covering peaks for a given audio URL and optional time range.
 * First checks the chapter-wide waveform cache, then falls back to
 * segment-level peaks stored in state._segPeaksByUrl.
 */
export function _findCoveringPeaks(
    audioUrl: string,
    startMs?: number | null,
    endMs?: number | null,
): AudioPeaks | null {
    const pe = getWaveformPeaks(audioUrl);
    if (pe && pe.peaks && pe.peaks.length > 0) return pe;
    if (startMs != null && endMs != null && state._segPeaksByUrl) {
        const entries = state._segPeaksByUrl[audioUrl];
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
