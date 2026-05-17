/**
 * Build the per-op peak records that ride along with a save payload.
 *
 * For each op we compute one covering range across all of its before/after
 * snapshots, then resolve peaks for that range from whichever in-memory
 * cache is populated (chapter-wide or covering-range). Found ranges become
 * persisted records — missing ones are silently skipped, and the lazy
 * compute-on-play path will fill them in later sessions.
 *
 * Edit chaining: each op's covering range is derived independently from its
 * own snapshots, so split→trim and similar chains store fresh ranges per op
 * without depending on prior persisted entries.
 */

import type { EditOp, PeakBucket } from '../../../../lib/types/domain';
import { getWaveformPeaks } from '../../../../lib/utils/waveform-cache';
import { _findCoveringPeaks } from './peaks-cache';

export interface OpPeakRecord {
    op_id: string;
    url: string;
    start_ms: number;
    end_ms: number;
    peaks: PeakBucket[];
    duration_ms: number;
}

interface SnapLike {
    audio_url?: unknown;
    time_start?: unknown;
    time_end?: unknown;
}

interface OpLike {
    op_id?: unknown;
    targets_before?: unknown;
    targets_after?: unknown;
}

/** Find the covering (url, startMs, endMs) range across an op's snapshots.
 *  Returns null when snapshots disagree on URL or carry no time range. */
function _coveringRangeForOp(op: OpLike): { url: string; startMs: number; endMs: number } | null {
    const snaps: SnapLike[] = [];
    for (const k of ['targets_before', 'targets_after'] as const) {
        const arr = op[k];
        if (Array.isArray(arr)) {
            for (const s of arr) {
                if (s && typeof s === 'object') snaps.push(s as SnapLike);
            }
        }
    }
    if (snaps.length === 0) return null;

    let url: string | null = null;
    let startMs = Number.POSITIVE_INFINITY;
    let endMs = Number.NEGATIVE_INFINITY;
    for (const s of snaps) {
        const u = typeof s.audio_url === 'string' ? s.audio_url : '';
        const ts = typeof s.time_start === 'number' ? s.time_start : null;
        const te = typeof s.time_end === 'number' ? s.time_end : null;
        if (!u || ts == null || te == null) continue;
        if (url === null) url = u;
        else if (url !== u) return null;  // cross-URL op — out of scope for this single-range record
        if (ts < startMs) startMs = ts;
        if (te > endMs) endMs = te;
    }
    if (url === null || !isFinite(startMs) || !isFinite(endMs) || endMs <= startMs) return null;
    return { url, startMs, endMs };
}

/** Slice the chapter-wide peaks array down to a [start, end] sub-range and
 *  emit it as a self-contained covering record (peaks shaped like a segment
 *  peaks blob, indexable directly by the covering-range cache). */
function _sliceFromChapterPeaks(
    fullPeaks: PeakBucket[],
    fullDurationMs: number,
    startMs: number,
    endMs: number,
): { peaks: PeakBucket[]; startMs: number; endMs: number; durationMs: number } | null {
    if (!fullPeaks.length || fullDurationMs <= 0) return null;
    const pps = fullPeaks.length / fullDurationMs;
    const startIdx = Math.max(0, Math.floor(startMs * pps));
    const endIdx = Math.min(fullPeaks.length, Math.ceil(endMs * pps));
    if (endIdx <= startIdx) return null;
    // Report the slice's ACTUAL time span (not the requested window).
    // Renderers compute peaks-per-ms from these fields; if they reflect
    // the requested window when the slice is actually wider, pps comes
    // out wrong and the canvas mapping drifts by up to one bucket per
    // side — invisible at 30 bps, visible at 10 bps. Storing the actual
    // span keeps the invariant `peaks.length == durationMs * pps` exact.
    const actualStartMs = startIdx / pps;
    const actualEndMs = endIdx / pps;
    return {
        peaks: fullPeaks.slice(startIdx, endIdx),
        startMs: actualStartMs,
        endMs: actualEndMs,
        durationMs: actualEndMs - actualStartMs,
    };
}

/** Build peak records for every op that has its peaks in memory.
 *  Caller-supplied ops can be from any chapters — each is resolved
 *  independently against the in-memory caches. */
export function collectOpPeaks(ops: ReadonlyArray<EditOp>): OpPeakRecord[] {
    const out: OpPeakRecord[] = [];
    for (const op of ops) {
        const opId = (op as OpLike).op_id;
        if (typeof opId !== 'string' || !opId) continue;

        const range = _coveringRangeForOp(op as OpLike);
        if (!range) continue;
        const { url, startMs, endMs } = range;

        // Prefer chapter-wide peaks (full-download mode) — slice the covering
        // range out so the record stands alone in any future session.
        const chapter = getWaveformPeaks(url);
        if (chapter?.peaks?.length && chapter.duration_ms > 0) {
            const sliced = _sliceFromChapterPeaks(chapter.peaks, chapter.duration_ms, startMs, endMs);
            if (sliced) {
                // Use the slice's ACTUAL span on the record so
                // `peaks.length == duration_ms * pps` stays exact —
                // see _sliceFromChapterPeaks comment for the rationale.
                out.push({
                    op_id: opId,
                    url,
                    start_ms: sliced.startMs,
                    end_ms: sliced.endMs,
                    peaks: sliced.peaks,
                    duration_ms: sliced.durationMs,
                });
                continue;
            }
        }

        // Fall back to a covering entry from the segment-peaks cache.
        const covering = _findCoveringPeaks(url, startMs, endMs);
        if (covering?.peaks?.length) {
            out.push({
                op_id: opId,
                url,
                start_ms: covering.start_ms ?? startMs,
                end_ms: (covering.start_ms ?? startMs) + covering.duration_ms,
                peaks: covering.peaks as PeakBucket[],
                duration_ms: covering.duration_ms,
            });
        }
    }
    return out;
}
