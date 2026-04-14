/**
 * Data loading, chapter management, and segment lookups.
 */

import { fetchJson, fetchJsonOrNull } from '../lib/api';
import { LS_KEYS } from '../lib/utils/constants';
import { surahOptionText } from '../lib/utils/surah-info';
import { clearWaveformCache } from '../lib/utils/waveform-cache';
import type {
    SegAllResponse,
    SegChaptersResponse,
    SegDataResponse,
    SegEditHistoryResponse,
    SegRecitersResponse,
    SegStatsResponse,
    SegValidateResponse,
} from '../types/api';
import type { Segment } from '../types/domain';
import { computeSilenceAfter } from './filters';
import { applyFiltersAndRender } from './filters';
import { renderEditHistoryPanel } from './history/index';
import { _fetchCacheStatus, _isCurrentReciterBySurah, _rewriteAudioUrls } from './playback/audio-cache';
import { stopSegAnimation } from './playback/index';
import { dom,state } from './state';
import { renderStatsPanel } from './stats';
import { captureValPanelState, renderValidationPanel, restoreValPanelState } from './validation/index';
import { _fetchChapterPeaksIfNeeded } from './waveform/index';

// ---------------------------------------------------------------------------
// Reciter loading
// ---------------------------------------------------------------------------

export async function loadSegReciters(): Promise<void> {
    try {
        state.segAllReciters = await fetchJson<SegRecitersResponse>('/api/seg/reciters');
        filterAndRenderReciters();

        const _savedSegReciter = localStorage.getItem(LS_KEYS.SEG_RECITER);
        if (_savedSegReciter) {
            dom.segReciterSelect.value = _savedSegReciter;
            if (dom.segReciterSelect.value === _savedSegReciter) {
                onSegReciterChange();
            }
        }
    } catch (e) {
        console.error('Error loading seg reciters:', e);
    }
}

export function filterAndRenderReciters(): void {
    dom.segReciterSelect.innerHTML = '<option value="">-- select --</option>';
    clearSegDisplay();

    const grouped: Record<string, typeof state.segAllReciters> = {};
    const uncategorized: typeof state.segAllReciters = [];

    for (const r of state.segAllReciters) {
        const src = r.audio_source || '';
        if (src) {
            if (!grouped[src]) grouped[src] = [];
            grouped[src].push(r);
        } else {
            uncategorized.push(r);
        }
    }

    for (const source of Object.keys(grouped).sort()) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = source;
        const reciters = grouped[source] ?? [];
        for (const r of reciters) {
            const opt = document.createElement('option');
            opt.value = r.slug;
            opt.textContent = r.name;
            optgroup.appendChild(opt);
        }
        dom.segReciterSelect.appendChild(optgroup);
    }

    if (uncategorized.length > 0) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '(uncategorized)';
        for (const r of uncategorized) {
            const opt = document.createElement('option');
            opt.value = r.slug;
            opt.textContent = r.name;
            optgroup.appendChild(opt);
        }
        dom.segReciterSelect.appendChild(optgroup);
    }
}

// ---------------------------------------------------------------------------
// Chapter/reciter change handlers
// ---------------------------------------------------------------------------

export async function onSegReciterChange(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (reciter) localStorage.setItem(LS_KEYS.SEG_RECITER, reciter);
    dom.segChapterSelect.innerHTML = '<option value="">-- select --</option>';
    if (state.segChapterSS) state.segChapterSS.refresh();
    dom.segVerseSelect.innerHTML = '<option value="">All</option>';
    clearSegDisplay();
    state._segDataStale = false;
    // Hide validation, stats, and history
    dom.segValidationGlobalEl.hidden = true;
    dom.segValidationGlobalEl.innerHTML = '';
    dom.segValidationEl.hidden = true;
    dom.segValidationEl.innerHTML = '';
    state.segValidation = null;
    dom.segStatsPanel.hidden = true;
    dom.segStatsPanel.removeAttribute('open');
    state.segStatsData = null;
    dom.segHistoryView.hidden = true;
    dom.segHistoryBtn.hidden = true;
    dom.segHistoryStats.innerHTML = '';
    dom.segHistoryBatches.innerHTML = '';
    state.segHistoryData = null;
    state._allHistoryItems = null;
    state._splitChains = null;
    state._chainedOpIds = null;
    state._segSavedChains = null;
    if (!reciter) return;

    try {
        const chapters = await fetchJson<SegChaptersResponse>(`/api/seg/chapters/${reciter}`);
        if (dom.segReciterSelect.value !== reciter) return;
        if (!Array.isArray(chapters)) return;
        chapters.forEach((ch: number) => {
            const opt = document.createElement('option');
            opt.value = String(ch);
            opt.textContent = surahOptionText(ch);
            dom.segChapterSelect.appendChild(opt);
        });
        if (state.segChapterSS) state.segChapterSS.refresh();
    } catch (e) {
        console.error('Error loading chapters:', e);
    }

    if (dom.segReciterSelect.value !== reciter) return;

    const [valResult, statsResult, allResult, histResult] = await Promise.allSettled([
        fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`),
        fetchJson<SegStatsResponse>(`/api/seg/stats/${reciter}`),
        fetchJson<SegAllResponse>(`/api/seg/all/${reciter}`),
        fetchJsonOrNull<SegEditHistoryResponse>(`/api/seg/edit-history/${reciter}`),
    ]);

    if (dom.segReciterSelect.value !== reciter) return;

    if (valResult.status === 'fulfilled') {
        state.segValidation = valResult.value;
        renderValidationPanel(state.segValidation);
    } else {
        console.error('Error loading validation:', valResult.reason);
    }

    if (statsResult.status === 'fulfilled') {
        state.segStatsData = statsResult.value;
        if (!state.segStatsData.error) renderStatsPanel(state.segStatsData);
    } else {
        console.error('Error loading stats:', statsResult.reason);
    }

    if (allResult.status === 'fulfilled') {
        state.segAllData = allResult.value;
        _rewriteAudioUrls();
        computeSilenceAfter();
        if (dom.segFilterBarEl) dom.segFilterBarEl.hidden = false;
        applyFiltersAndRender();
        if (_isCurrentReciterBySurah()) _fetchCacheStatus(reciter);
    } else {
        console.error('Error loading all segments:', allResult.reason);
    }

    if (histResult.status === 'fulfilled' && histResult.value) {
        state.segHistoryData = histResult.value;
        renderEditHistoryPanel(state.segHistoryData);
    }
}

export async function onSegChapterChange(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    const chapter = dom.segChapterSelect.value;
    dom.segVerseSelect.innerHTML = '<option value="">All</option>';

    dom.segAudioEl.src = '';
    dom.segPlayBtn.disabled = true;
    stopSegAnimation();
    state._segPrefetchCache = {};

    if (state.segValidation) {
        requestAnimationFrame(() => {
            if (!state.segValidation) return;
            const globalState = captureValPanelState(dom.segValidationGlobalEl);
            const chState = captureValPanelState(dom.segValidationEl);
            const ch = chapter ? parseInt(chapter) : null;
            if (ch !== null) {
                renderValidationPanel(state.segValidation, null, dom.segValidationGlobalEl, 'All Chapters');
                renderValidationPanel(state.segValidation, ch, dom.segValidationEl, `Chapter ${ch}`);
                restoreValPanelState(dom.segValidationGlobalEl, globalState);
                restoreValPanelState(dom.segValidationEl, chState);
            } else {
                dom.segValidationGlobalEl.hidden = true;
                dom.segValidationGlobalEl.innerHTML = '';
                renderValidationPanel(state.segValidation, null, dom.segValidationEl);
                restoreValPanelState(dom.segValidationEl, chState);
            }
        });
    }

    applyFiltersAndRender();

    if (!reciter || !chapter) return;
    dom.segPlayBtn.disabled = false;

    try {
        const segData = await fetchJson<SegDataResponse>(`/api/seg/data/${reciter}/${chapter}`);
        if (dom.segReciterSelect.value !== reciter || dom.segChapterSelect.value !== chapter) return;
        state.segData = segData;
        if (state.segData.error) return;
        if (_isCurrentReciterBySurah() && state.segData.audio_url && !state.segData.audio_url.startsWith('/api/')) {
            state.segData.audio_url = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(state.segData.audio_url)}`;
        }

        const verses = new Set<number>();
        (state.segAllData?.segments || [])
            .filter((s: Segment) => s.chapter === parseInt(chapter) && !!s.matched_ref)
            .forEach((s: Segment) => {
                const start = s.matched_ref.split('-')[0]?.split(':');
                if (start && start.length >= 2 && start[1] != null) verses.add(parseInt(start[1]));
            });
        [...verses].sort((a, b) => a - b).forEach((v) => {
            const opt = document.createElement('option');
            opt.value = String(v); opt.textContent = String(v);
            dom.segVerseSelect.appendChild(opt);
        });

        const chNum = parseInt(chapter);
        state.segData.segments = (state.segAllData?.segments || []).filter((s: Segment) => s.chapter === chNum);

        _fetchChapterPeaksIfNeeded(reciter, chNum);

        if (state.segData.audio_url) {
            dom.segAudioEl.src = state.segData.audio_url;
            dom.segAudioEl.preload = 'metadata';
        }
    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}

// ---------------------------------------------------------------------------
// Display clear
// ---------------------------------------------------------------------------

export function clearSegDisplay(): void {
    if (state._waveformObserver) { state._waveformObserver.disconnect(); state._waveformObserver = null; }
    state._segIndexMap = null;
    state.segAllData = null;
    state.segActiveFilters = [];
    if (dom.segFilterBarEl) { dom.segFilterBarEl.hidden = true; dom.segFilterRowsEl.innerHTML = ''; }
    const cacheBar = document.getElementById('seg-cache-bar');
    if (cacheBar) cacheBar.hidden = true;
    if (state._audioCachePollTimer) { clearInterval(state._audioCachePollTimer); state._audioCachePollTimer = null; }
    if (dom.segFilterCountEl) dom.segFilterCountEl.textContent = '';
    if (dom.segFilterClearBtn) dom.segFilterClearBtn.hidden = true;
    if (dom.segFilterStatusEl) dom.segFilterStatusEl.textContent = '';
    state.segData = null;
    state.segDisplayedSegments = null;
    state.segCurrentIdx = -1;
    state.segDirtyMap.clear();
    state.segOpLog.clear();
    state._pendingOp = null;
    state.segEditMode = null;
    state.segEditIndex = -1;
    state.segStatsData = null;
    if (dom.segStatsPanel) { dom.segStatsPanel.hidden = true; dom.segStatsCharts.innerHTML = ''; }
    state.segHistoryData = null;
    state._allHistoryItems = null;
    state._splitChains = null;
    state._chainedOpIds = null;
    state._segSavedChains = null;
    dom.segHistoryBtn.hidden = true;
    dom.segHistoryView.hidden = true;
    dom.segHistoryStats.innerHTML = '';
    dom.segHistoryBatches.innerHTML = '';
    dom.segSavePreview.hidden = true;
    dom.segSavePreviewStats.innerHTML = '';
    dom.segSavePreviewBatches.innerHTML = '';
    state._segPrefetchCache = {};
    state._segContinuousPlay = false;
    state._segPlayEndMs = 0;
    clearWaveformCache();
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    state._segPeaksByUrl = null;
    state._observerPeaksQueue = [];
    if (state._observerPeaksTimer) { clearTimeout(state._observerPeaksTimer); state._observerPeaksTimer = null; }
    state._observerPeaksRequested = new Set();
    // Wave 7: SegmentsList.svelte renders #seg-list via {#each}; clearing
    // segAllData (above) makes the derived `displayedSegments` empty, which
    // shows the "No segments to display" placeholder. No imperative innerHTML
    // wipe needed; doing so would clobber Svelte's reconciliation.
    dom.segPlayBtn.disabled = true;
    dom.segSaveBtn.disabled = true;
    dom.segPlayStatus.textContent = '';
    stopSegAnimation();
}

// ---------------------------------------------------------------------------
// Chapter segment lookups
// ---------------------------------------------------------------------------

/** Build lazily-indexed per-chapter segment lookup from segAllData */
export function getChapterSegments(chapter: number | string): Segment[] {
    const all = state.segAllData;
    if (!all || !all.segments) return [];
    if (!all._byChapter) {
        const byChapter: Record<string, Segment[]> = {};
        const byIndex = new Map<string, Segment>();
        all.segments.forEach((s) => {
            const ch: number | undefined = s.chapter;
            if (ch == null) return;
            const key = String(ch);
            if (!byChapter[key]) byChapter[key] = [];
            byChapter[key].push(s);
            byIndex.set(`${ch}:${s.index}`, s);
        });
        for (const ch of Object.keys(byChapter)) {
            const list = byChapter[ch];
            if (list) list.sort((a, b) => a.index - b.index);
        }
        all._byChapter = byChapter;
        all._byChapterIndex = byIndex;
    }
    return all._byChapter[String(chapter)] || [];
}

export function getSegByChapterIndex(chapter: number | string, index: number): Segment | null {
    const all = state.segAllData;
    if (!all || !all.segments) return null;
    if (!all._byChapterIndex) getChapterSegments(chapter);
    return all._byChapterIndex?.get(`${chapter}:${index}`) || null;
}

export interface AdjacentSegments {
    prev: Segment | null;
    next: Segment | null;
}

export function getAdjacentSegments(chapter: number | string, index: number): AdjacentSegments {
    const segs = getChapterSegments(chapter);
    const pos = segs.findIndex((s) => s.index === index);
    return {
        prev: pos > 0 ? (segs[pos - 1] ?? null) : null,
        next: pos >= 0 && pos < segs.length - 1 ? (segs[pos + 1] ?? null) : null,
    };
}

/**
 * Sync segData.segments (chapter-specific edits) back into segAllData.segments.
 */
export function syncChapterSegsToAll(): void {
    if (!state.segAllData || !state.segData || !state.segData.segments) return;
    const chapter = parseInt(dom.segChapterSelect.value);
    if (!chapter) return;
    const other = state.segAllData.segments.filter((s) => s.chapter !== chapter);
    const updated = state.segData.segments.map((s) => {
        s.chapter = chapter;
        return s;
    });
    const insertIdx = other.findIndex((s) => (s.chapter ?? 0) > chapter);
    if (insertIdx === -1) {
        state.segAllData.segments = [...other, ...updated];
    } else {
        state.segAllData.segments = [
            ...other.slice(0, insertIdx),
            ...updated,
            ...other.slice(insertIdx),
        ];
    }
    state.segAllData._byChapter = null;
    state.segAllData._byChapterIndex = null;
}

/**
 * Get the current chapter's segments from segData or segAllData.
 */
export function _getChapterSegs(): Segment[] {
    if (state.segData?.segments?.length) return state.segData.segments;
    const ch = parseInt(dom.segChapterSelect.value);
    if (ch && state.segAllData?.segments) return state.segAllData.segments.filter((s) => s.chapter === ch);
    return [];
}

