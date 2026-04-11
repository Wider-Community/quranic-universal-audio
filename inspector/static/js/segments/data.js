/**
 * Data loading, chapter management, and segment lookups.
 */

import { state, dom } from './state.js';
import { LS_KEYS } from '../shared/constants.js';
import { surahOptionText } from '../shared/surah-info.js';
import { SearchableSelect } from '../shared/searchable-select.js';
import { computeSilenceAfter } from './filters.js';
import { renderSegList } from './rendering.js';
import { applyFiltersAndRender } from './filters.js';
import { _fetchPeaks, _fetchChapterPeaksIfNeeded } from './waveform.js';
import { _isCurrentReciterBySurah, _fetchCacheStatus, _rewriteAudioUrls } from './audio-cache.js';
import { stopSegAnimation } from './playback.js';
import { renderValidationPanel, captureValPanelState, restoreValPanelState } from './validation.js';
import { renderStatsPanel } from './stats.js';
import { renderEditHistoryPanel } from './history.js';

// ---------------------------------------------------------------------------
// Reciter loading
// ---------------------------------------------------------------------------

export async function loadSegReciters() {
    try {
        const resp = await fetch('/api/seg/reciters');
        state.segAllReciters = await resp.json();
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

export function filterAndRenderReciters() {
    dom.segReciterSelect.innerHTML = '<option value="">-- select --</option>';
    clearSegDisplay();

    const grouped = {};
    const uncategorized = [];

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
        for (const r of grouped[source]) {
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

export async function onSegReciterChange() {
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
        const resp = await fetch(`/api/seg/chapters/${reciter}`);
        if (dom.segReciterSelect.value !== reciter) return;
        const chapters = await resp.json();
        chapters.forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch;
            opt.textContent = surahOptionText(ch);
            dom.segChapterSelect.appendChild(opt);
        });
        if (state.segChapterSS) state.segChapterSS.refresh();
    } catch (e) {
        console.error('Error loading chapters:', e);
    }

    if (dom.segReciterSelect.value !== reciter) return;

    const [valResult, statsResult, allResult, histResult] = await Promise.allSettled([
        fetch(`/api/seg/validate/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/stats/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/all/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/edit-history/${reciter}`).then(r => r.ok ? r.json() : null),
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
        const errorChapters = _collectErrorChapters(state.segValidation);
        if (errorChapters.length > 0) _fetchPeaks(reciter, errorChapters);
        if (_isCurrentReciterBySurah()) _fetchCacheStatus(reciter);
    } else {
        console.error('Error loading all segments:', allResult.reason);
    }

    if (histResult.status === 'fulfilled' && histResult.value) {
        state.segHistoryData = histResult.value;
        renderEditHistoryPanel(state.segHistoryData);
    }
}

export async function onSegChapterChange() {
    const reciter = dom.segReciterSelect.value;
    const chapter = dom.segChapterSelect.value;
    dom.segVerseSelect.innerHTML = '<option value="">All</option>';

    dom.segAudioEl.src = '';
    dom.segPlayBtn.disabled = true;
    stopSegAnimation();
    state._segPrefetchCache = {};

    if (state.segValidation) {
        requestAnimationFrame(() => {
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
        const resp = await fetch(`/api/seg/data/${reciter}/${chapter}`);
        if (dom.segReciterSelect.value !== reciter || dom.segChapterSelect.value !== chapter) return;
        state.segData = await resp.json();
        if (state.segData.error) return;
        if (_isCurrentReciterBySurah() && state.segData.audio_url && !state.segData.audio_url.startsWith('/api/')) {
            state.segData.audio_url = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(state.segData.audio_url)}`;
        }

        const verses = new Set();
        (state.segAllData?.segments || [])
            .filter(s => s.chapter === parseInt(chapter) && s.matched_ref)
            .forEach(s => {
                const start = s.matched_ref.split('-')[0]?.split(':');
                if (start?.length >= 2) verses.add(parseInt(start[1]));
            });
        [...verses].sort((a, b) => a - b).forEach(v => {
            const opt = document.createElement('option');
            opt.value = v; opt.textContent = v;
            dom.segVerseSelect.appendChild(opt);
        });

        const chNum = parseInt(chapter);
        state.segData.segments = (state.segAllData?.segments || []).filter(s => s.chapter === chNum);

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

export function clearSegDisplay() {
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
    state.segPeaksByAudio = null;
    if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
    dom.segListEl.innerHTML = '';
    dom.segPlayBtn.disabled = true;
    dom.segSaveBtn.disabled = true;
    dom.segPlayStatus.textContent = '';
    stopSegAnimation();
}

// ---------------------------------------------------------------------------
// Chapter segment lookups
// ---------------------------------------------------------------------------

/** Build lazily-indexed per-chapter segment lookup from segAllData */
export function getChapterSegments(chapter) {
    if (!state.segAllData || !state.segAllData.segments) return [];
    if (!state.segAllData._byChapter) {
        state.segAllData._byChapter = {};
        state.segAllData._byChapterIndex = new Map();
        state.segAllData.segments.forEach(s => {
            const ch = s.chapter;
            if (!state.segAllData._byChapter[ch]) state.segAllData._byChapter[ch] = [];
            state.segAllData._byChapter[ch].push(s);
            state.segAllData._byChapterIndex.set(`${ch}:${s.index}`, s);
        });
        for (const ch of Object.keys(state.segAllData._byChapter)) {
            state.segAllData._byChapter[ch].sort((a, b) => a.index - b.index);
        }
    }
    return state.segAllData._byChapter[chapter] || [];
}

export function getSegByChapterIndex(chapter, index) {
    if (!state.segAllData || !state.segAllData.segments) return null;
    if (!state.segAllData._byChapterIndex) getChapterSegments(chapter);
    return state.segAllData._byChapterIndex.get(`${chapter}:${index}`) || null;
}

export function getAdjacentSegments(chapter, index) {
    const segs = getChapterSegments(chapter);
    const pos = segs.findIndex(s => s.index === index);
    return {
        prev: pos > 0 ? segs[pos - 1] : null,
        next: pos >= 0 && pos < segs.length - 1 ? segs[pos + 1] : null
    };
}

/**
 * Sync segData.segments (chapter-specific edits) back into segAllData.segments.
 */
export function syncChapterSegsToAll() {
    if (!state.segAllData || !state.segData || !state.segData.segments) return;
    const chapter = parseInt(dom.segChapterSelect.value);
    if (!chapter) return;
    const other = state.segAllData.segments.filter(s => s.chapter !== chapter);
    const updated = state.segData.segments.map(s => { s.chapter = chapter; return s; });
    const insertIdx = other.findIndex(s => s.chapter > chapter);
    if (insertIdx === -1) {
        state.segAllData.segments = [...other, ...updated];
    } else {
        state.segAllData.segments = [
            ...other.slice(0, insertIdx),
            ...updated,
            ...other.slice(insertIdx),
        ];
    }
    state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
}

/**
 * Get the current chapter's segments from segData or segAllData.
 */
export function _getChapterSegs() {
    if (state.segData?.segments?.length) return state.segData.segments;
    const ch = parseInt(dom.segChapterSelect.value);
    if (ch && state.segAllData?.segments) return state.segAllData.segments.filter(s => s.chapter === ch);
    return [];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract unique chapter numbers from all validation error categories. */
function _collectErrorChapters(validation) {
    if (!validation) return [];
    const chapters = new Set();
    const cats = ['errors', 'missing_verses', 'missing_words', 'failed',
                  'low_confidence', 'boundary_adj',
                  'cross_verse', 'audio_bleeding', 'repetitions'];
    for (const cat of cats) {
        const items = validation[cat];
        if (items) items.forEach(i => { if (i.chapter) chapters.add(i.chapter); });
    }
    return [...chapters].sort((a, b) => a - b);
}
