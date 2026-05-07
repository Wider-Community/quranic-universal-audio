import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegPeaksResponse, SegSegmentPeaksResponse } from '../../../../lib/types/api';
import type { Segment, SegmentPeaks } from '../../../../lib/types/domain';
import { getWaveformPeaks, setWaveformPeaks } from '../../../../lib/utils/waveform-cache';
import {
    getAdjacentSegments,
    getSegByChapterIndex,
    segAllData,
    selectedReciter,
} from '../../stores/chapter';
import { segConfig } from '../../stores/config';
import { editCanvas } from '../../stores/edit';
import { segIndexMap } from '../../stores/filters';
import { waveformContainers } from '../../stores/playback';
import type { TimerHandle } from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';
import { drawSegBaseAndOverlays } from './draw-seg';
import { _findCoveringPeaks, clearSegPeaksCache, pushSegPeaksEntry } from './peaks-cache';
import { drawSplitWaveform } from './split-draw';
import { drawTrimWaveform } from './trim-draw';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _waveformObserver: IntersectionObserver | null = null;
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
}

// ---------------------------------------------------------------------------
// Peaks: bulk indexing of segment-level peaks
// ---------------------------------------------------------------------------

export function indexSegPeaksBulk(peaksMap: Record<string, SegmentPeaks> | null | undefined): void {
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

/** Push a list of persisted history-peaks records (from
 *  `/api/seg/history-peaks/<reciter>`) into the covering-range cache so the
 *  History panel renders without re-computing. Tolerant of partial records —
 *  any malformed entry is skipped. */
export function indexHistoryPeaksRecords(
    records: ReadonlyArray<{ url?: string; start_ms?: number; end_ms?: number; peaks?: unknown; duration_ms?: number }> | null | undefined,
): void {
    if (!records?.length) return;
    for (const r of records) {
        const url = r.url;
        const startMs = r.start_ms;
        const endMs = r.end_ms;
        const durationMs = r.duration_ms;
        const peaks = r.peaks;
        if (!url || typeof startMs !== 'number' || typeof endMs !== 'number'
            || typeof durationMs !== 'number' || !Array.isArray(peaks) || peaks.length === 0) continue;
        pushSegPeaksEntry(url, {
            startMs,
            endMs,
            peaks: peaks as SegmentPeaks['peaks'],
            durationMs,
        });
    }
}

// ---------------------------------------------------------------------------
// Redraw all pending waveform canvases
// ---------------------------------------------------------------------------

export function redrawPeaksWaveforms(): void {
    const observer = _ensureWaveformObserver();
    const activeEdit = get(editCanvas);
    for (const container of get(waveformContainers)) {
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
            if (isNaN(idx) || isNaN(chapter)) return;

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

            let wfSeg: Segment = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;
            if (canvas._padHL && !canvas._splitHL) {
                const ext = Math.max(wfSeg.time_end, canvas._padHL.padEnd);
                wfSeg = { ...wfSeg, time_end: ext };
            }

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

            const audioUrl = wfSeg.audio_url
                || get(segAllData)?.audio_by_chapter?.[String(chapter)]
                || '';
            if (drawSegBaseAndOverlays(canvas, wfSeg.time_start, wfSeg.time_end, audioUrl)) {
                _waveformObserver?.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
            }
            // Cache miss: leave canvas flat. Stream-mode peaks compute on
            // play (`_fetchPeaksForClick`); History rows hydrate from the
            // peaks JSONL on panel open.
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
        indexSegPeaksBulk(newPeaks);
        redrawPeaksWaveforms();
    } catch { /* ignore */ }
}

/** Fetch segment peaks for an extended range through *paddedEndMs* (qalqala batch preview). */
export async function fetchPeaksForPaddedEnd(
    seg: Segment,
    chapter: number | string,
    paddedEndMs: number,
): Promise<void> {
    const reciter = get(selectedReciter);
    const allData = get(segAllData);
    if (!reciter || !allData) return;
    const audioUrl = seg.audio_url || allData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;

    const { prev, next } = getAdjacentSegments(chapter, seg.index);
    const prevEnd = prev?.time_end ?? 0;
    const nextStart = next?.time_start ?? Number.POSITIVE_INFINITY;
    const cfg = get(segConfig);
    const PAD_EXTRA_MS = 500;
    const entry = {
        url: audioUrl,
        start_ms: Math.max(prevEnd, seg.time_start - cfg.trimPadLeft, 0),
        end_ms: Math.min(nextStart, paddedEndMs + PAD_EXTRA_MS),
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
        indexSegPeaksBulk(newPeaks);
        redrawPeaksWaveforms();
    } catch { /* ignore */ }
}
