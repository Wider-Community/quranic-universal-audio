/**
 * Waveform observer, peaks fetching/polling, and redraw orchestration.
 * Uses canvas callback pattern for edit-mode draws.
 */

import { state, dom, _findCoveringPeaks } from './state.js';
import { getSegByChapterIndex } from './data.js';
import { _getEditCanvas } from './rendering.js';
import { drawWaveformFromPeaksForSeg, _drawSplitHighlight, _drawTrimHighlight, _drawMergeHighlight } from './waveform-draw.js';
import { _isCurrentReciterBySurah } from './audio-cache.js';

// Forward references for edit-mode draw functions (Phase 7).
// The observer needs to call drawSplitWaveform/drawTrimWaveform when it encounters
// a canvas in edit mode. These are registered from index.js via registerWaveformHandlers.
let _drawSplitWaveformFn = null;
let _drawTrimWaveformFn = null;

export function registerWaveformHandlers(handlers) {
    if (handlers.drawSplitWaveform) _drawSplitWaveformFn = handlers.drawSplitWaveform;
    if (handlers.drawTrimWaveform) _drawTrimWaveformFn = handlers.drawTrimWaveform;
}

// ---------------------------------------------------------------------------
// Segment-level peaks URL index: enables covering-range lookups
// ---------------------------------------------------------------------------

function _indexSegPeaksBulk(peaksMap) {
    if (!peaksMap) return;
    for (const [key, data] of Object.entries(peaksMap)) {
        if (!data?.peaks?.length || data.start_ms == null) continue;
        const url = key.split(':').slice(0, -2).join(':');  // strip ":startMs:endMs"
        if (!state._segPeaksByUrl) state._segPeaksByUrl = {};
        if (!state._segPeaksByUrl[url]) state._segPeaksByUrl[url] = [];
        state._segPeaksByUrl[url].push({
            startMs: data.start_ms,
            endMs: data.end_ms,
            peaks: data.peaks,
            durationMs: data.duration_ms,
        });
    }
}

export function _ensureWaveformObserver() {
    if (state._waveformObserver) return state._waveformObserver;
    state._waveformObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const canvas = entry.target;
            const row = canvas.closest('.seg-row');
            if (!row) return;
            const idx = parseInt(row.dataset.segIndex);
            const chapter = parseInt(row.dataset.segChapter);

            let seg;
            if (row.dataset.histTimeStart) {
                seg = {
                    time_start: parseInt(row.dataset.histTimeStart),
                    time_end: parseInt(row.dataset.histTimeEnd),
                    audio_url: row.dataset.histAudioUrl || '',
                    chapter,
                };
            } else {
                seg = (state._segIndexMap ? state._segIndexMap.get(`${chapter}:${idx}`) : null) || (chapter ? getSegByChapterIndex(chapter, idx) : null);
            }
            if (!seg) return;

            const wfSeg = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;

            // If in split/trim edit mode, delegate to edit draw functions
            if (canvas._splitData) {
                canvas._splitBaseCache = null;
                _drawSplitWaveformFn?.(canvas);
                state._waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }
            if (canvas._trimWindow) {
                canvas._wfCache = null;
                _drawTrimWaveformFn?.(canvas);
                state._waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }

            if (drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter)) {
                _drawSplitHighlight(canvas, wfSeg);
                _drawTrimHighlight(canvas, seg);
                _drawMergeHighlight(canvas, seg);
                state._waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
            } else {
                _queueObserverPeaksFetch(seg, chapter);
            }
        });
    }, { rootMargin: '200px' });
    return state._waveformObserver;
}

export function drawAllSegWaveforms() {
    if (!state.segDisplayedSegments) return;
    const observer = _ensureWaveformObserver();
    dom.segListEl.querySelectorAll('canvas[data-needs-waveform]').forEach(canvas => {
        observer.unobserve(canvas);
        observer.observe(canvas);
    });
}

// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

export function _fetchPeaks(reciter, chapters) {
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    if (!chapters || chapters.length === 0) return;
    let url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetch(url).then(r => r.json()).then(data => {
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

export function _fetchChapterPeaksIfNeeded(reciter, chapter) {
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

function _queueObserverPeaksFetch(seg, chapter) {
    const audioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    const key = `${audioUrl}:${seg.time_start}:${seg.time_end}`;
    if (state._observerPeaksRequested.has(key)) return;
    state._observerPeaksRequested.add(key);
    state._observerPeaksQueue.push({ url: audioUrl, start_ms: seg.time_start, end_ms: seg.time_end });

    if (state._observerPeaksTimer) clearTimeout(state._observerPeaksTimer);
    state._observerPeaksTimer = setTimeout(_flushObserverPeaksQueue, 150);
}

function _flushObserverPeaksQueue() {
    state._observerPeaksTimer = null;
    const queue = state._observerPeaksQueue.splice(0);
    if (queue.length === 0) return;
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;

    fetch(`/api/seg/segment-peaks/${reciter}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ segments: queue, cached_only: true }),
    })
        .then(r => r.json())
        .then(data => {
            if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
            const newPeaks = data.peaks || {};
            if (Object.keys(newPeaks).length === 0) return;
            _indexSegPeaksBulk(newPeaks);
            _redrawPeaksWaveforms();
        })
        .catch(() => {});
}

export function _redrawPeaksWaveforms() {
    const observer = _ensureWaveformObserver();
    const editCanvas = _getEditCanvas();
    [dom.segListEl, dom.segValidationEl, dom.segValidationGlobalEl, dom.segHistoryView, dom.segSavePreview].forEach(container => {
        if (!container) return;
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => {
            if (c === editCanvas) return;
            observer.unobserve(c);
            observer.observe(c);
        });
    });
    // Redraw split/trim canvas directly
    if (editCanvas?._splitData) { editCanvas._splitBaseCache = null; _drawSplitWaveformFn?.(editCanvas); }
    else if (editCanvas?._trimWindow) { editCanvas._wfCache = null; _drawTrimWaveformFn?.(editCanvas); }
}
