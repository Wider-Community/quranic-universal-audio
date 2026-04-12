/**
 * Waveform observer, peaks fetching/polling, and redraw orchestration.
 * Uses canvas callback pattern for edit-mode draws.
 */

import { state, dom, _findCoveringPeaks } from '../state';
import { getSegByChapterIndex } from '../data';
import { _getEditCanvas } from '../rendering';
import { drawWaveformFromPeaksForSeg, _drawSplitHighlight, _drawTrimHighlight, _drawMergeHighlight } from './draw';
import { _isCurrentReciterBySurah } from '../playback/audio-cache';
import { fetchJson } from '../../shared/api';
import type { SegPeaksResponse, SegSegmentPeaksResponse } from '../../types/api';
import type { DrawWaveformFn } from '../../types/registry';
import type { Segment, SegmentPeaks } from '../../types/domain';
import type { SegCanvas } from './types';

// NOTE: un-used helper for future Phase 7 typing of _findCoveringPeaks
void _findCoveringPeaks;

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

export function drawAllSegWaveforms(): void {
    if (!state.segDisplayedSegments) return;
    const observer = _ensureWaveformObserver();
    dom.segListEl.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(canvas => {
        observer.unobserve(canvas);
        observer.observe(canvas);
    });
}

// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

export function _fetchPeaks(reciter: string, chapters: Array<number | string>): void {
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    if (!chapters || chapters.length === 0) return;
    const url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetchJson<SegPeaksResponse>(url).then(data => {
        if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
        if (!state.segPeaksByAudio) state.segPeaksByAudio = {};
        Object.assign(state.segPeaksByAudio, data.peaks || {});
        if (_isCurrentReciterBySurah()) {
            for (const [origUrl, pe] of Object.entries(data.peaks || {})) {
                if (origUrl && !origUrl.startsWith('/api/')) {
                    state.segPeaksByAudio[`/api/seg/audio-proxy/${dom.segReciterSelect.value}?url=${encodeURIComponent(origUrl)}`] = pe;
                }
            }
        }
        _redrawPeaksWaveforms();
        if (!data.complete) {
            state._peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

export function _fetchChapterPeaksIfNeeded(reciter: string, chapter: number | string): void {
    if (!state.segAllData) return;
    const audioUrl = state.segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    if (state.segPeaksByAudio?.[audioUrl]) return;
    const proxyUrl = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(audioUrl)}`;
    if (state.segPeaksByAudio?.[proxyUrl]) return;
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
