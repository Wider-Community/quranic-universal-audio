/**
 * Waveform drawing functions -- peaks-based rendering, playhead, overlays.
 */

import type { AudioPeaks, PeakBucket, Segment } from '../../types/domain';
import { _findCoveringPeaks,state } from '../state';
import type { SegCanvas } from './types';

type Peaks = PeakBucket[];

export function drawSegmentWaveformFromPeaks(
    canvas: SegCanvas,
    startMs: number,
    endMs: number,
    peaks: Peaks,
    totalDurationMs: number,
): void {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    if (!peaks || peaks.length === 0 || totalDurationMs <= 0) return;

    const startIdx = Math.floor((startMs / totalDurationMs) * peaks.length);
    const endIdx = Math.ceil((endMs / totalDurationMs) * peaks.length);
    const slice = peaks.slice(Math.max(0, startIdx), Math.min(peaks.length, endIdx));
    if (slice.length === 0) return;

    const buckets = width;
    const scale = height / 2 * 0.9;

    function sampleAt(arr: Peaks, idx: number, component: 0 | 1): number {
        const fi = (idx / buckets) * (arr.length - 1);
        const lo = Math.floor(fi);
        const hi = Math.min(lo + 1, arr.length - 1);
        const t = fi - lo;
        return (arr[lo]?.[component] ?? 0) * (1 - t) + (arr[hi]?.[component] ?? 0) * t;
    }

    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(slice, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const x = (i / buckets) * width;
        const minVal = sampleAt(slice, i, 0);
        const y = centerY - minVal * scale;
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(slice, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    canvas._wfCache = null;
}

/** Draw waveform from peaks for a segment, resolving its audio URL. Returns true if drawn. */
export function drawWaveformFromPeaksForSeg(canvas: SegCanvas, seg: Segment, chapter: number | string): boolean {
    if (!state.segPeaksByAudio) return false;
    const audioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const pe = state.segPeaksByAudio[audioUrl];
    if (pe?.peaks?.length) {
        drawSegmentWaveformFromPeaks(canvas, seg.time_start, seg.time_end, pe.peaks, pe.duration_ms);
        return true;
    }
    // Fallback: try covering-range peaks (segment-level or padded).
    // Subtract range start offset: per-segment peaks begin at start_ms within the file,
    // not at t=0.  Without this, time_start/duration_ms > 1 → empty slice → blank canvas.
    const covering = _findCoveringPeaks(audioUrl, seg.time_start, seg.time_end);
    if (covering?.peaks?.length) {
        const rs = covering.start_ms ?? 0;
        drawSegmentWaveformFromPeaks(canvas, seg.time_start - rs, seg.time_end - rs, covering.peaks as Peaks, covering.duration_ms);
        return true;
    }
    return false;
}

export function drawSegPlayhead(
    canvas: SegCanvas,
    startMs: number,
    endMs: number,
    currentTimeMs: number,
    audioUrl: string,
): void {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const cacheKey = `${startMs}:${endMs}`;
    if (canvas._wfCache && canvas._wfCacheKey === cacheKey) {
        ctx.putImageData(canvas._wfCache, 0, 0);
    } else {
        if (audioUrl) {
            // Use covering-peaks lookup: supports both full-file peaks and per-segment
            // chunk peaks (fetched via _fetchPeaksForClick). Without this, chunk peaks
            // don't draw here -- only a blank canvas + playhead shows.
            const pe = _findCoveringPeaks(audioUrl, startMs, endMs);
            if (pe?.peaks?.length) {
                const rs = pe.start_ms ?? 0;
                drawSegmentWaveformFromPeaks(canvas, startMs - rs, endMs - rs, pe.peaks as PeakBucket[], pe.duration_ms);
            }
        }
        canvas._wfCache = ctx.getImageData(0, 0, canvas.width, canvas.height);
        canvas._wfCacheKey = cacheKey;
    }

    if (currentTimeMs < startMs || currentTimeMs > endMs) return;

    const width = canvas.width;
    const height = canvas.height;
    const progress = (currentTimeMs - startMs) / (endMs - startMs);
    const x = progress * width;

    ctx.strokeStyle = '#f72585';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    ctx.fillStyle = '#f72585';
    ctx.beginPath();
    ctx.moveTo(x - 4, 0);
    ctx.lineTo(x + 4, 0);
    ctx.lineTo(x, 6);
    ctx.closePath();
    ctx.fill();
}

interface SlicedPeaks {
    maxVals: Float32Array;
    minVals: Float32Array;
}

/** Slice peaks for a time range and resample to `buckets` bins. */
export function _slicePeaks(
    audioUrl: string,
    startMs: number,
    endMs: number,
    buckets: number,
): SlicedPeaks | null {
    if (!state.segPeaksByAudio) return null;
    let pe: AudioPeaks | undefined = state.segPeaksByAudio[audioUrl];
    if (!pe?.peaks?.length) {
        pe = _findCoveringPeaks(audioUrl, startMs, endMs) ?? undefined;
    }
    if (!pe?.peaks?.length) return null;
    const peaks = pe.peaks;
    const rs = pe.start_ms ?? 0;
    const pps = peaks.length / pe.duration_ms;
    const startIdx = Math.max(0, Math.floor((startMs - rs) * pps));
    const endIdx = Math.min(peaks.length, Math.ceil((endMs - rs) * pps));
    const slice = peaks.slice(startIdx, endIdx);
    if (slice.length === 0) return null;
    const maxVals = new Float32Array(buckets);
    const minVals = new Float32Array(buckets);
    if (slice.length >= buckets) {
        const blockSize = slice.length / buckets;
        for (let i = 0; i < buckets; i++) {
            const from = Math.floor(i * blockSize);
            const to = Math.min(Math.ceil((i + 1) * blockSize), slice.length);
            let mx = -1, mn = 1;
            for (let j = from; j < to; j++) {
                const bk = slice[j];
                if (!bk) continue;
                if (bk[1] > mx) mx = bk[1];
                if (bk[0] < mn) mn = bk[0];
            }
            maxVals[i] = mx;
            minVals[i] = mn;
        }
    } else {
        for (let i = 0; i < buckets; i++) {
            const fi = (i / buckets) * (slice.length - 1);
            const lo = Math.floor(fi);
            const hi = Math.min(lo + 1, slice.length - 1);
            const t = fi - lo;
            const loBk = slice[lo];
            const hiBk = slice[hi];
            if (!loBk || !hiBk) continue;
            minVals[i] = loBk[0] * (1 - t) + hiBk[0] * t;
            maxVals[i] = loBk[1] * (1 - t) + hiBk[1] * t;
        }
    }
    return { maxVals, minVals };
}

/** Draw red/green overlay on history card waveforms to show trim changes. */
export function _drawTrimHighlight(canvas: SegCanvas, seg: Segment): void {
    const hl = canvas._trimHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width, h = canvas.height;
    const dur = seg.time_end - seg.time_start;
    if (dur <= 0) return;

    const rgba = hl.color === 'red' ? 'rgba(244, 67, 54, 0.3)' : 'rgba(76, 175, 80, 0.3)';
    ctx.fillStyle = rgba;

    if (seg.time_start < hl.otherStart) {
        const x2 = ((hl.otherStart - seg.time_start) / dur) * w;
        ctx.fillRect(0, 0, x2, h);
    }
    if (seg.time_end > hl.otherEnd) {
        const x1 = ((hl.otherEnd - seg.time_start) / dur) * w;
        ctx.fillRect(x1, 0, w - x1, h);
    }
}

/** Draw dim + green overlay on split chain after-card waveforms. */
export function _drawSplitHighlight(canvas: SegCanvas, wfSeg: Segment): void {
    const hl = canvas._splitHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width, h = canvas.height;
    const dur = wfSeg.time_end - wfSeg.time_start;
    if (dur <= 0) return;
    const toX = (ms: number): number => Math.max(0, Math.min(w, ((ms - wfSeg.time_start) / dur) * w));

    const hlStart = hl.hlStart ?? hl.wfStart;
    const hlEnd = hl.hlEnd ?? hl.wfEnd;
    const x1 = toX(hlStart);
    const x2 = toX(hlEnd);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    if (x1 > 0) ctx.fillRect(0, 0, x1, h);
    if (x2 < w) ctx.fillRect(x2, 0, w - x2, h);

    ctx.fillStyle = 'rgba(76, 175, 80, 0.3)';
    if (x2 > x1) ctx.fillRect(x1, 0, x2 - x1, h);
}

/** Draw dim + green overlay on merge result card showing the absorbed segment's range. */
export function _drawMergeHighlight(canvas: SegCanvas, seg: Segment): void {
    const hl = canvas._mergeHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const w = canvas.width, h = canvas.height;
    const dur = seg.time_end - seg.time_start;
    if (dur <= 0) return;
    const toX = (ms: number): number => Math.max(0, Math.min(w, ((ms - seg.time_start) / dur) * w));

    const x1 = toX(hl.hlStart);
    const x2 = toX(hl.hlEnd);

    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    if (x1 > 0) ctx.fillRect(0, 0, x1, h);
    if (x2 < w) ctx.fillRect(x2, 0, w - x2, h);

    ctx.fillStyle = 'rgba(76, 175, 80, 0.3)';
    if (x2 > x1) ctx.fillRect(x1, 0, x2 - x1, h);
}
