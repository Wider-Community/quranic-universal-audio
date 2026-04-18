import { get } from 'svelte/store';

import { fetchJson } from '../../api';
import {
    getAdjacentSegments,
    getSegByChapterIndex,
    segAllData,
    selectedReciter,
} from '../../stores/segments/chapter';
import { segConfig } from '../../stores/segments/config';
import { editCanvas } from '../../stores/segments/edit';
import { segIndexMap } from '../../stores/segments/filters';
import type { SegPeaksResponse, SegSegmentPeaksResponse } from '../../types/api';
import type { Segment, SegmentPeaks } from '../../types/domain';
import type {
    ObserverPeaksQueueItem,
    TimerHandle,
} from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';
import { getWaveformPeaks, setWaveformPeaks } from '../waveform-cache';
import { _findCoveringPeaks, clearSegPeaksCache, pushSegPeaksEntry } from './peaks-cache';
import { drawSplitWaveform } from './split-draw';
import { drawTrimWaveform } from './trim-draw';
import { _drawMergeHighlight, _drawSplitHighlight, _drawTrimHighlight, drawWaveformFromPeaksForSeg } from './waveform-draw-seg';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _waveformObserver: IntersectionObserver | null = null;
let _observerPeaksQueue: ObserverPeaksQueueItem[] = [];
let _observerPeaksTimer: TimerHandle | null = null;
let _observerPeaksRequested = new Set<string>();
let _peaksPollTimer: TimerHandle | null = null;

/** Reset all per-reciter waveform caches / observer. Called from
 *  clearPerReciterState. */
export function resetWaveformState(): void {
    if (_waveformObserver) {
        _waveformObserver.disconnect();
        _waveformObserver = null;
    }
    if (_peaksPollTimer) { clearTimeout(_peaksPollTimer); _peaksPollTimer = null; }
    clearSegPeaksCache();
    _observerPeaksQueue = [];
    if (_observerPeaksTimer) { clearTimeout(_observerPeaksTimer); _observerPeaksTimer = null; }
    _observerPeaksRequested = new Set();
}

// ---------------------------------------------------------------------------
// Peaks: bulk indexing of segment-level peaks
// ---------------------------------------------------------------------------

type SegPeaksEntry = Partial<SegmentPeaks>;

export function indexSegPeaksBulk(peaksMap: Record<string, SegPeaksEntry> | null | undefined): void {
    if (!peaksMap) return;
    for (const [key, data] of Object.entries(peaksMap)) {
        if (!data?.peaks?.length || data.start_ms == null || data.end_ms == null || data.duration_ms == null) continue;
        const url = key.split(':').slice(0, -2).join(':');  // strip ":startMs:endMs"
        pushSegPeaksEntry(url, {
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

/** The 4 imperatively-rendered container IDs that may host seg-row canvases. */
const _CONTAINER_IDS = ['seg-list', 'seg-validation', 'seg-validation-global', 'seg-history-view', 'seg-save-preview'];

export function redrawPeaksWaveforms(): void {
    const observer = _ensureWaveformObserver();
    const activeEdit = get(editCanvas);
    for (const id of _CONTAINER_IDS) {
        const container = document.getElementById(id);
        if (!container) continue;
        container.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(c => {
            if (c === activeEdit) return;
            observer.unobserve(c);
            observer.observe(c);
        });
    }
    if (activeEdit?._splitData) {
        activeEdit._splitBaseCache = null;
        drawSplitWaveform(activeEdit);
    } else if (activeEdit?._trimWindow) {
        activeEdit._wfCache = null;
        drawTrimWaveform(activeEdit);
    }
}

// ---------------------------------------------------------------------------
// Observer-triggered segment-level peaks pre-fetch
// ---------------------------------------------------------------------------

function _queueObserverPeaksFetch(seg: Segment, chapter: number | string): void {
    const audioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    const key = `${audioUrl}:${seg.time_start}:${seg.time_end}`;
    if (_observerPeaksRequested.has(key)) return;
    _observerPeaksRequested.add(key);
    _observerPeaksQueue.push({ url: audioUrl, start_ms: seg.time_start, end_ms: seg.time_end });

    if (_observerPeaksTimer) clearTimeout(_observerPeaksTimer);
    _observerPeaksTimer = setTimeout(_flushObserverPeaksQueue, 150);
}

function _flushObserverPeaksQueue(): void {
    _observerPeaksTimer = null;
    const queue = _observerPeaksQueue.splice(0);
    if (queue.length === 0) return;
    const reciter = get(selectedReciter);
    if (!reciter) return;

    fetchJson<SegSegmentPeaksResponse>(`/api/seg/segment-peaks/${reciter}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ segments: queue, cached_only: true }),
    })
        .then(data => {
            if (!get(segAllData) || get(selectedReciter) !== reciter) return;
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
    if (_waveformObserver) return _waveformObserver;
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
                const idxMap = get(segIndexMap);
                seg = idxMap.get(`${chapter}:${idx}`)
                    ?? (chapter ? getSegByChapterIndex(chapter, idx) : null);
            }
            if (!seg) return;

            const wfSeg: Segment = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;

            if (canvas._splitData) {
                canvas._splitBaseCache = null;
                drawSplitWaveform(canvas);
                _waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }
            if (canvas._trimWindow) {
                canvas._wfCache = null;
                drawTrimWaveform(canvas);
                _waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }

            if (drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter)) {
                _drawSplitHighlight(canvas, wfSeg);
                _drawTrimHighlight(canvas, seg);
                _drawMergeHighlight(canvas, seg);
                _waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
            } else {
                _queueObserverPeaksFetch(seg, chapter);
            }
        });
    }, { rootMargin: '200px' });
    _waveformObserver = observer;
    return observer;
}

// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

export function _fetchPeaks(reciter: string, chapters: Array<number | string>): void {
    if (_peaksPollTimer) { clearTimeout(_peaksPollTimer); _peaksPollTimer = null; }
    if (!chapters || chapters.length === 0) return;
    const url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetchJson<SegPeaksResponse>(url).then(data => {
        if (!get(segAllData) || get(selectedReciter) !== reciter) return;
        for (const [audioUrl, pe] of Object.entries(data.peaks || {})) {
            if (audioUrl) setWaveformPeaks(audioUrl, pe);
        }
        redrawPeaksWaveforms();
        if (!data.complete && Object.keys(data.peaks || {}).length > 0) {
            _peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

export function _fetchChapterPeaksIfNeeded(reciter: string, chapter: number | string): void {
    const allData = get(segAllData);
    if (!allData) return;
    const audioUrl = allData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    if (getWaveformPeaks(audioUrl)) return;
    _fetchPeaks(reciter, [chapter]);
}

export async function _fetchPeaksForClick(seg: Segment, chapter: number | string): Promise<void> {
    const reciter = get(selectedReciter);
    const allData = get(segAllData);
    if (!reciter || !allData) return;
    const audioUrl = seg.audio_url || allData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    if (getWaveformPeaks(audioUrl)?.peaks?.length) return;
    if (_findCoveringPeaks(audioUrl, seg.time_start, seg.time_end)) return;

    const { prev, next } = getAdjacentSegments(chapter, seg.index);
    const prevEnd = prev?.time_end ?? 0;
    const nextStart = next?.time_start ?? Number.POSITIVE_INFINITY;
    const cfg = get(segConfig);
    const entry = {
        url: audioUrl,
        start_ms: Math.max(prevEnd, seg.time_start - cfg.trimPadLeft, 0),
        end_ms: Math.min(nextStart, seg.time_end + cfg.trimPadRight),
    };

    try {
        const data = await fetchJson<SegSegmentPeaksResponse>(`/api/seg/segment-peaks/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ segments: [entry] }),
        });
        if (!get(segAllData) || get(selectedReciter) !== reciter) return;
        const newPeaks = data.peaks || {};
        if (Object.keys(newPeaks).length === 0) return;
        indexSegPeaksBulk(newPeaks as unknown as Record<string, SegPeaksEntry>);
        redrawPeaksWaveforms();
    } catch { /* ignore */ }
}
