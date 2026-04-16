import type { AdjacentSegments } from '../../../segments/data';
import type { DrawWaveformFn } from '../../../segments/registry';
import { _findCoveringPeaks, dom, state } from '../../../segments/state';
import type { SegPeaksResponse, SegSegmentPeaksResponse } from '../../../types/api';
import type { Segment, SegmentPeaks } from '../../../types/domain';
import { fetchJson } from '../../api';
import type { SegCanvas } from '../../types/segments-waveform';
import { getWaveformPeaks, setWaveformPeaks } from '../waveform-cache';
import { _drawMergeHighlight, _drawSplitHighlight, _drawTrimHighlight, drawWaveformFromPeaksForSeg } from './waveform-draw-seg';

// ---------------------------------------------------------------------------
// Registered draw functions (wired from segments/index.ts)
// ---------------------------------------------------------------------------

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
// Registered data lookup functions (wired from segments/index.ts to break
// waveform ↔ data circular dependency)
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

function _getAdjacentSegments(chapter: number | string, index: number): AdjacentSegments {
    return _getAdjacentSegmentsFn?.(chapter, index) ?? { prev: null, next: null };
}

function _getSegByChapterIndex(chapter: number | string, index: number): Segment | null {
    return _getSegByChapterIndexFn?.(chapter, index) ?? null;
}

// ---------------------------------------------------------------------------
// Registered _getEditCanvas (wired from segments/index.ts to break
// waveform ↔ rendering circular dependency)
// ---------------------------------------------------------------------------

let _getEditCanvasFn: (() => HTMLCanvasElement | null) | null = null;
export function registerGetEditCanvas(fn: () => HTMLCanvasElement | null): void { _getEditCanvasFn = fn; }
function _getEditCanvasViaRegistry(): HTMLCanvasElement | null { return _getEditCanvasFn?.() ?? null; }

// ---------------------------------------------------------------------------
// Peaks: bulk indexing of segment-level peaks
// ---------------------------------------------------------------------------

type SegPeaksEntry = Partial<SegmentPeaks>;

export function indexSegPeaksBulk(peaksMap: Record<string, SegPeaksEntry> | null | undefined): void {
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

// ---------------------------------------------------------------------------
// Redraw all pending waveform canvases
// ---------------------------------------------------------------------------

export function redrawPeaksWaveforms(): void {
    const observer = _ensureWaveformObserver();
    const editCanvas = _getEditCanvasViaRegistry() as SegCanvas | null;
    [dom.segListEl, dom.segValidationEl, dom.segValidationGlobalEl, dom.segHistoryView, dom.segSavePreview].forEach(container => {
        if (!container) return;
        container.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(c => {
            if (c === editCanvas) return;
            observer.unobserve(c);
            observer.observe(c);
        });
    });
    if (editCanvas?._splitData) { editCanvas._splitBaseCache = null; _drawSplitWaveformFn?.(editCanvas); }
    else if (editCanvas?._trimWindow) { editCanvas._wfCache = null; _drawTrimWaveformFn?.(editCanvas); }
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
            indexSegPeaksBulk(newPeaks as unknown as Record<string, SegPeaksEntry>);
            redrawPeaksWaveforms();
        })
        .catch(() => {});
}

// ---------------------------------------------------------------------------
// IntersectionObserver for lazy waveform loading
// ---------------------------------------------------------------------------

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
                    || (chapter ? _getSegByChapterIndex(chapter, idx) : null);
            }
            if (!seg) return;

            const wfSeg: Segment = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;

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

// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

export function _fetchPeaks(reciter: string, chapters: Array<number | string>): void {
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    if (!chapters || chapters.length === 0) return;
    const url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetchJson<SegPeaksResponse>(url).then(data => {
        if (!state.segAllData || dom.segReciterSelect.value !== reciter) return;
        for (const [audioUrl, pe] of Object.entries(data.peaks || {})) {
            if (audioUrl) setWaveformPeaks(audioUrl, pe);
        }
        redrawPeaksWaveforms();
        if (!data.complete && Object.keys(data.peaks || {}).length > 0) {
            state._peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

export function _fetchChapterPeaksIfNeeded(reciter: string, chapter: number | string): void {
    if (!state.segAllData) return;
    const audioUrl = state.segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    if (getWaveformPeaks(audioUrl)) return;
    _fetchPeaks(reciter, [chapter]);
}

export async function _fetchPeaksForClick(seg: Segment, chapter: number | string): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter || !state.segAllData) return;
    const audioUrl = seg.audio_url || state.segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    if (getWaveformPeaks(audioUrl)?.peaks?.length) return;
    if (_findCoveringPeaks(audioUrl, seg.time_start, seg.time_end)) return;

    const { prev, next } = _getAdjacentSegments(chapter, seg.index);
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
        indexSegPeaksBulk(newPeaks as unknown as Record<string, SegPeaksEntry>);
        redrawPeaksWaveforms();
    } catch { /* ignore */ }
}
