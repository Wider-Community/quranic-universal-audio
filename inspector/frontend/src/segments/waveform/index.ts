/**
 * Waveform observer, peaks fetching/polling, and redraw orchestration.
 * Uses canvas callback pattern for edit-mode draws.
 */

import { fetchJson } from '../../lib/api';
import { getWaveformPeaks,setWaveformPeaks } from '../../lib/utils/waveform-cache';
import type { SegPeaksResponse, SegSegmentPeaksResponse } from '../../types/api';
import type { Segment, SegmentPeaks } from '../../types/domain';
import type { AdjacentSegments } from '../data';
import type { DrawWaveformFn } from '../registry';
import { _findCoveringPeaks, dom, state } from '../state';
import { _drawMergeHighlight,_drawSplitHighlight, _drawTrimHighlight, drawWaveformFromPeaksForSeg } from './draw';
import type { SegCanvas } from './types';

// ---------------------------------------------------------------------------
// Break waveform/index ↔ data circular dependency (S2-B06 / P4).
// Both directions were causing cycles: waveform imported getAdjacentSegments /
// getSegByChapterIndex from data; data imported _fetchChapterPeaksIfNeeded from
// waveform. Both edges are broken with registrations wired in segments/index.ts.
// ---------------------------------------------------------------------------

let _getAdjacentSegmentsFn: ((chapter: number | string, index: number) => AdjacentSegments) | null = null;
let _getSegByChapterIndexFn: ((chapter: number | string, index: number) => Segment | null) | null = null;

export function registerDataLookups(
    getAdjFn: (chapter: number | string, index: number) => AdjacentSegments,
    getSegFn: (chapter: number | string, index: number) => Segment | null,
): void {
    _getAdjacentSegmentsFn = getAdjFn;
    _getSegByChapterIndexFn = getSegFn;
}

function getAdjacentSegments(chapter: number | string, index: number): AdjacentSegments {
    return _getAdjacentSegmentsFn?.(chapter, index) ?? { prev: null, next: null };
}

function getSegByChapterIndex(chapter: number | string, index: number): Segment | null {
    return _getSegByChapterIndexFn?.(chapter, index) ?? null;
}

// ---------------------------------------------------------------------------
// Break waveform/index ↔ rendering circular dependency (S2-B06 / P4).
// `_getEditCanvas` is registered by segments/index.ts after both modules load.
// ---------------------------------------------------------------------------

let _getEditCanvasFn: (() => HTMLCanvasElement | null) | null = null;
export function registerGetEditCanvas(fn: () => HTMLCanvasElement | null): void { _getEditCanvasFn = fn; }
function _getEditCanvas(): HTMLCanvasElement | null { return _getEditCanvasFn?.() ?? null; }

// Forward references for edit-mode draw functions.
// The observer needs to call drawSplitWaveform/drawTrimWaveform when it encounters
// a canvas in edit mode. These are registered from edit-common via registerWaveformHandlers.
let _drawSplitWaveformFn: DrawWaveformFn | null = null;
let _drawTrimWaveformFn: DrawWaveformFn | null = null;

export interface WaveformHandlers {
    drawSplitWaveform?: DrawWaveformFn;
    drawTrimWaveform?: DrawWaveformFn;
}

export function registerWaveformHandlers(handlers: WaveformHandlers): void {
    if (handlers.drawSplitWaveform) _drawSplitWaveformFn = handlers.drawSplitWaveform;
    if (handlers.drawTrimWaveform) _drawTrimWaveformFn = handlers.drawTrimWaveform;
}

// ---------------------------------------------------------------------------
// Segment-level peaks URL index: enables covering-range lookups
// ---------------------------------------------------------------------------

/** Raw segment-peaks entry as received from the server (fields may be missing
 *  on partial/error responses — guarded below). Shape is `Partial<SegmentPeaks>`
 *  at the runtime boundary. */
type SegPeaksEntry = Partial<SegmentPeaks>;

function _indexSegPeaksBulk(peaksMap: Record<string, SegPeaksEntry> | null | undefined): void {
    if (!peaksMap) return;
    for (const [key, data] of Object.entries(peaksMap)) {
        if (!data?.peaks?.length || data.start_ms == null || data.end_ms == null || data.duration_ms == null) continue;
        const url = key.split(':').slice(0, -2).join(':');  // strip ":startMs:endMs"
        if (!state._segPeaksByUrl) state._segPeaksByUrl = {};
        if (!state._segPeaksByUrl[url]) state._segPeaksByUrl[url] = [];
        state._segPeaksByUrl[url]!.push({
            startMs: data.start_ms,
            endMs: data.end_ms,
            peaks: data.peaks,
            durationMs: data.duration_ms,
        });
    }
}

export function _ensureWaveformObserver(): IntersectionObserver {
    if (state._waveformObserver) return state._waveformObserver;
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const canvas = entry.target as SegCanvas;
            const row = canvas.closest<HTMLElement>('.seg-row');
            if (!row) return;
            const idx = parseInt(row.dataset.segIndex ?? '');
            const chapter = parseInt(row.dataset.segChapter ?? '');

            let seg: Segment | null = null;
            if (row.dataset.histTimeStart) {
                seg = {
                    time_start: parseInt(row.dataset.histTimeStart),
                    time_end: parseInt(row.dataset.histTimeEnd ?? ''),
                    audio_url: row.dataset.histAudioUrl || '',
                    chapter,
                } as Segment;
            } else {
                seg = (state._segIndexMap ? state._segIndexMap.get(`${chapter}:${idx}`) ?? null : null)
                    || (chapter ? getSegByChapterIndex(chapter, idx) : null);
            }
            if (!seg) return;

            const wfSeg: Segment = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;

            // If in split/trim edit mode, delegate to edit draw functions
            if (canvas._splitData) {
                canvas._splitBaseCache = null;
                _drawSplitWaveformFn?.(canvas);
                state._waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }
            if (canvas._trimWindow) {
                canvas._wfCache = null;
                _drawTrimWaveformFn?.(canvas);
                state._waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }

            if (drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter)) {
                _drawSplitHighlight(canvas, wfSeg);
                _drawTrimHighlight(canvas, seg);
                _drawMergeHighlight(canvas, seg);
                state._waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
            } else {
                _queueObserverPeaksFetch(seg, chapter);
            }
        });
    }, { rootMargin: '200px' });
    state._waveformObserver = observer;
    return observer;
}

// Wave 7a.2: `drawAllSegWaveforms` deleted — dead since Wave 7a.1
// (no callers; guarded on `state.segDisplayedSegments` which is never
// written post-Wave 7). SegmentRow.svelte::onMount now registers each
// canvas with the observer directly. (Wave 7a.1 handoff NB-2.)

// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

export function _fetchPeaks(reciter: string, chapters: Array<number | string>): void {
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    if (!chapters || chapters.length === 0) return;
    const url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetchJson<SegPeaksResponse>(url).then(data => {
        if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
        // Store peaks via waveform-cache util (normalizes proxy URLs — fixes S2-B04).
        // Wave 7 CF: backwards-compat sync to state.segPeaksByAudio removed —
        // all read sites (draw.ts, _slicePeaks, _findCoveringPeaks, edit/trim,
        // edit/split) now use getWaveformPeaks() directly.
        for (const [audioUrl, pe] of Object.entries(data.peaks || {})) {
            if (audioUrl) setWaveformPeaks(audioUrl, pe);
        }
        _redrawPeaksWaveforms();
        // Only poll while some peaks arrived (i.e. audio is partially cached).
        // Empty result means no local audio files -- per-segment on-demand handles it.
        if (!data.complete && Object.keys(data.peaks || {}).length > 0) {
            state._peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

export function _fetchChapterPeaksIfNeeded(reciter: string, chapter: number | string): void {
    if (!state.segAllData) return;
    const audioUrl = state.segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    // Single cache lookup via normalized key — covers both CDN and proxy URL forms (S2-B04).
    if (getWaveformPeaks(audioUrl)) return;
    _fetchPeaks(reciter, [chapter]);
}

// ---------------------------------------------------------------------------
// Observer-triggered segment-level peaks pre-fetch
// ---------------------------------------------------------------------------

function _queueObserverPeaksFetch(seg: Segment, chapter: number | string): void {
    const audioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    const key = `${audioUrl}:${seg.time_start}:${seg.time_end}`;
    if (state._observerPeaksRequested.has(key)) return;
    state._observerPeaksRequested.add(key);
    state._observerPeaksQueue.push({ url: audioUrl, start_ms: seg.time_start, end_ms: seg.time_end });

    if (state._observerPeaksTimer) clearTimeout(state._observerPeaksTimer);
    state._observerPeaksTimer = setTimeout(_flushObserverPeaksQueue, 150);
}

function _flushObserverPeaksQueue(): void {
    state._observerPeaksTimer = null;
    const queue = state._observerPeaksQueue.splice(0);
    if (queue.length === 0) return;
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;

    fetchJson<SegSegmentPeaksResponse>(`/api/seg/segment-peaks/${reciter}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // cached_only: true -- observer only uses disk cache; on-demand ffmpeg is triggered by
        // _fetchPeaksForClick on play/click so we don't saturate the server with concurrent ffmpeg calls.
        body: JSON.stringify({ segments: queue, cached_only: true }),
    })
        .then(data => {
            if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
            const newPeaks = data.peaks || {};
            if (Object.keys(newPeaks).length === 0) return;
            _indexSegPeaksBulk(newPeaks as unknown as Record<string, SegPeaksEntry>);
            _redrawPeaksWaveforms();
        })
        .catch(() => {});
}

// ---------------------------------------------------------------------------
// On-demand peak fetch for a clicked / played segment (ffmpeg HTTP Range)
// ---------------------------------------------------------------------------

/** Fetch waveform peaks for a segment via HTTP Range + ffmpeg on the server.
 *  Called on play-button click so peaks appear with a brief delay instead of
 *  never (the observer only checks disk cache, cached_only: true). */
export async function _fetchPeaksForClick(seg: Segment, chapter: number | string): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter || !state.segAllData) return;
    const audioUrl = seg.audio_url || state.segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    // Skip if already have usable peaks for this segment (normalized lookup — S2-B04)
    if (getWaveformPeaks(audioUrl)?.peaks?.length) return;
    if (_findCoveringPeaks(audioUrl, seg.time_start, seg.time_end)) return;

    // Cap the padded range by prev/next segment boundaries so the chunk does
    // not overlap neighbour segments -- otherwise N's covering peaks engulf
    // N+1 (TRIM_PAD is 10s) and N+1's waveform renders before it plays.
    // Matches edit/trim.ts window clamping.
    const { prev, next } = getAdjacentSegments(chapter, seg.index);
    const prevEnd = prev?.time_end ?? 0;
    const nextStart = next?.time_start ?? Number.POSITIVE_INFINITY;
    const entry = {
        url: audioUrl,
        start_ms: Math.max(prevEnd, seg.time_start - state.TRIM_PAD_LEFT, 0),
        end_ms: Math.min(nextStart, seg.time_end + state.TRIM_PAD_RIGHT),
    };

    try {
        const data = await fetchJson<SegSegmentPeaksResponse>(`/api/seg/segment-peaks/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ segments: [entry] }),
        });
        if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
        const newPeaks = data.peaks || {};
        if (Object.keys(newPeaks).length === 0) return;
        _indexSegPeaksBulk(newPeaks as unknown as Record<string, SegPeaksEntry>);
        _redrawPeaksWaveforms();
    } catch { /* ignore */ }
}

export function _redrawPeaksWaveforms(): void {
    const observer = _ensureWaveformObserver();
    const editCanvas = _getEditCanvas() as SegCanvas | null;
    [dom.segListEl, dom.segValidationEl, dom.segValidationGlobalEl, dom.segHistoryView, dom.segSavePreview].forEach(container => {
        if (!container) return;
        container.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(c => {
            if (c === editCanvas) return;
            observer.unobserve(c);
            observer.observe(c);
        });
    });
    // Redraw split/trim canvas directly
    if (editCanvas?._splitData) { editCanvas._splitBaseCache = null; _drawSplitWaveformFn?.(editCanvas); }
    else if (editCanvas?._trimWindow) { editCanvas._wfCache = null; _drawTrimWaveformFn?.(editCanvas); }
}
