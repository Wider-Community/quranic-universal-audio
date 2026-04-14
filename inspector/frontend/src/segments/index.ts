/**
 * Segments tab entry point -- DOMContentLoaded, event wiring, config loading.
 * Wires the extracted foundation modules together and registers handlers
 * for event delegation and keyboard shortcuts.
 */

// Validation / stats / history modules (imports for side-effect registration)
import './validation/index';
import './stats';

import { fetchJsonOrNull } from '../lib/api';
import { LS_KEYS } from '../lib/utils/constants';
import { surahInfoReady } from '../lib/utils/surah-info';
import { mustGet } from '../shared/dom';
import { SearchableSelect } from '../shared/searchable-select';
import type { SegConfigResponse } from '../types/api';
import { loadSegReciters, onSegChapterChange,onSegReciterChange } from './data';
// Edit modules
import { enterEditWithBuffer, exitEditMode, registerEditDrawFns,registerEditModes } from './edit/common';
import { deleteSegment } from './edit/delete';
import { mergeAdjacent } from './edit/merge';
import { startRefEdit } from './edit/reference';
import { confirmSplit, drawSplitWaveform,enterSplitMode } from './edit/split';
import { confirmTrim, drawTrimWaveform,enterTrimMode } from './edit/trim';
import { _handleSegCanvasMousedown, handleSegRowClick, registerAllSegEventHandlers } from './event-delegation';
import { addSegFilterCondition, applyFiltersAndRender, clearAllSegFilters } from './filters';
import { clearHistoryFilters, setHistorySort } from './history/filters';
import { hideHistoryView,showHistoryView } from './history/index';
import { handleSegKeydown, registerAllSegKeyboardHandlers } from './keyboard';
import { _deleteAudioCache,_prepareAudio } from './playback/audio-cache';
import { onSegAudioEnded,onSegPlayClick, onSegTimeUpdate, startSegAnimation, stopSegAnimation } from './playback/index';
import { confirmSaveFromPreview,hideSavePreview, onSegSaveClick } from './save';
import { dom, setClassifyFn,state } from './state';
import { _classifySegCategories } from './validation/categories';
import { playErrorCardAudio } from './validation/error-card-audio';
import { _isWrapperContextShown,ensureContextShown } from './validation/error-cards';
import { registerWaveformHandlers } from './waveform/index';

// ---------------------------------------------------------------------------
// Inject the classify function to break the state <-> categories cycle
// ---------------------------------------------------------------------------
setClassifyFn(_classifySegCategories);

// ---------------------------------------------------------------------------
// Wire up edit mode registrations (breaks edit-common -> edit-trim/split cycle)
// ---------------------------------------------------------------------------
registerEditModes(enterTrimMode, enterSplitMode);
registerEditDrawFns(drawTrimWaveform, drawSplitWaveform);

// Wire edit-mode draw functions into waveform observer
registerWaveformHandlers({
    drawSplitWaveform,
    drawTrimWaveform,
});


// ---------------------------------------------------------------------------
// DOMContentLoaded
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
    // Initialize DOM references
    dom.segReciterSelect = mustGet<HTMLSelectElement>('seg-reciter-select');
    dom.segChapterSelect = mustGet<HTMLSelectElement>('seg-chapter-select');
    dom.segVerseSelect = mustGet<HTMLSelectElement>('seg-verse-select');
    dom.segListEl = mustGet<HTMLDivElement>('seg-list');
    dom.segAudioEl = mustGet<HTMLAudioElement>('seg-audio-player');
    dom.segPlayBtn = mustGet<HTMLButtonElement>('seg-play-btn');
    dom.segAutoPlayBtn = mustGet<HTMLButtonElement>('seg-autoplay-btn');
    dom.segSpeedSelect = mustGet<HTMLSelectElement>('seg-speed-select');
    dom.segSaveBtn = mustGet<HTMLButtonElement>('seg-save-btn');
    dom.segPlayStatus = mustGet<HTMLElement>('seg-play-status');
    dom.segValidationGlobalEl = mustGet<HTMLDivElement>('seg-validation-global');
    dom.segValidationEl = mustGet<HTMLDivElement>('seg-validation');
    dom.segStatsPanel = mustGet<HTMLDivElement>('seg-stats-panel');
    dom.segStatsCharts = mustGet<HTMLDivElement>('seg-stats-charts');
    dom.segFilterBarEl = mustGet<HTMLDivElement>('seg-filter-bar');
    dom.segFilterRowsEl = mustGet<HTMLDivElement>('seg-filter-rows');
    dom.segFilterAddBtn = mustGet<HTMLButtonElement>('seg-filter-add-btn');
    dom.segFilterClearBtn = mustGet<HTMLButtonElement>('seg-filter-clear-btn');
    dom.segFilterCountEl = mustGet<HTMLElement>('seg-filter-count');
    dom.segFilterStatusEl = mustGet<HTMLElement>('seg-filter-status');
    dom.segHistoryView = mustGet<HTMLDivElement>('seg-history-view');
    dom.segHistoryBtn = mustGet<HTMLButtonElement>('seg-history-btn');
    dom.segHistoryBackBtn = mustGet<HTMLButtonElement>('seg-history-back-btn');
    dom.segHistoryStats = mustGet<HTMLDivElement>('seg-history-stats');
    dom.segHistoryBatches = mustGet<HTMLDivElement>('seg-history-batches');
    dom.segHistoryFilters = mustGet<HTMLDivElement>('seg-history-filters');
    dom.segHistoryFilterOps = mustGet<HTMLDivElement>('seg-history-filter-ops');
    dom.segHistoryFilterCats = mustGet<HTMLDivElement>('seg-history-filter-cats');
    dom.segHistoryFilterClear = mustGet<HTMLButtonElement>('seg-history-filter-clear');
    dom.segHistorySortTime = mustGet<HTMLButtonElement>('seg-history-sort-time');
    dom.segHistorySortQuran = mustGet<HTMLButtonElement>('seg-history-sort-quran');
    dom.segSavePreview = mustGet<HTMLDivElement>('seg-save-preview');
    dom.segSavePreviewCancel = mustGet<HTMLButtonElement>('seg-save-preview-cancel');
    dom.segSavePreviewConfirm = mustGet<HTMLButtonElement>('seg-save-preview-confirm');
    dom.segSavePreviewStats = mustGet<HTMLDivElement>('seg-save-preview-stats');
    dom.segSavePreviewBatches = mustGet<HTMLDivElement>('seg-save-preview-batches');

    // Restore persistent settings
    state._segAutoPlayEnabled = localStorage.getItem(LS_KEYS.SEG_AUTOPLAY) !== 'false';
    dom.segAutoPlayBtn.className = 'btn ' + (state._segAutoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');
    const _savedSegSpeed = localStorage.getItem(LS_KEYS.SEG_SPEED);
    if (_savedSegSpeed) dom.segSpeedSelect.value = _savedSegSpeed;

    // Wire event listeners
    dom.segReciterSelect.addEventListener('change', onSegReciterChange);
    dom.segChapterSelect.addEventListener('change', onSegChapterChange);
    dom.segVerseSelect.addEventListener('change', applyFiltersAndRender);
    dom.segPlayBtn.addEventListener('click', onSegPlayClick);
    dom.segAutoPlayBtn.addEventListener('click', () => {
        state._segAutoPlayEnabled = !state._segAutoPlayEnabled;
        state._segContinuousPlay = state._segAutoPlayEnabled;
        dom.segAutoPlayBtn.className = 'btn ' + (state._segAutoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');
        localStorage.setItem(LS_KEYS.SEG_AUTOPLAY, String(state._segAutoPlayEnabled));
    });
    dom.segSpeedSelect.addEventListener('change', () => {
        const rate = parseFloat(dom.segSpeedSelect.value);
        dom.segAudioEl.playbackRate = rate;
        if (state.valCardAudio) state.valCardAudio.playbackRate = rate;
        localStorage.setItem(LS_KEYS.SEG_SPEED, dom.segSpeedSelect.value);
    });

    dom.segAudioEl.addEventListener('play', startSegAnimation);
    dom.segAudioEl.addEventListener('pause', stopSegAnimation);
    dom.segAudioEl.addEventListener('ended', onSegAudioEnded);
    dom.segAudioEl.addEventListener('timeupdate', onSegTimeUpdate);

    document.addEventListener('keydown', handleSegKeydown);

    dom.segFilterAddBtn.addEventListener('click', addSegFilterCondition);
    dom.segFilterClearBtn.addEventListener('click', clearAllSegFilters);

    // Delegated event listeners for segment card actions
    [dom.segListEl, dom.segValidationEl, dom.segValidationGlobalEl, dom.segHistoryView, dom.segSavePreview].forEach(el => {
        el.addEventListener('click', handleSegRowClick);
        el.addEventListener('mousedown', _handleSegCanvasMousedown);
    });

    // Register event delegation + keyboard handlers (all slots at once — TS
    // enforces completeness; missing a key is a compile error).
    registerAllSegEventHandlers({
        startRefEdit,
        enterEditWithBuffer,
        mergeAdjacent,
        deleteSegment,
        playErrorCardAudio,
        ensureContextShown,
        _isWrapperContextShown,
    });

    registerAllSegKeyboardHandlers({
        onSegSaveClick,
        hideSavePreview,
        confirmSaveFromPreview,
        exitEditMode,
        confirmTrim,
        confirmSplit,
        startRefEdit,
    });

    // Save button
    dom.segSaveBtn.addEventListener('click', onSegSaveClick);

    // History view handlers
    dom.segHistoryBtn?.addEventListener('click', showHistoryView);
    dom.segHistoryBackBtn?.addEventListener('click', hideHistoryView);
    dom.segHistoryFilterClear?.addEventListener('click', clearHistoryFilters);
    dom.segHistorySortTime?.addEventListener('click', () => setHistorySort('time'));
    dom.segHistorySortQuran?.addEventListener('click', () => setHistorySort('quran'));

    // Save preview handlers
    dom.segSavePreviewCancel?.addEventListener('click', () => hideSavePreview());
    dom.segSavePreviewConfirm?.addEventListener('click', confirmSaveFromPreview);

    // Load display config
    try {
        const cfg = await fetchJsonOrNull<SegConfigResponse>('/api/seg/config');
        if (cfg) {
            const root = document.documentElement.style;
            if (cfg.seg_font_size) root.setProperty('--seg-font-size', String(cfg.seg_font_size));
            if (cfg.seg_word_spacing) root.setProperty('--seg-word-spacing', String(cfg.seg_word_spacing));
            if (cfg.trim_pad_left != null) state.TRIM_PAD_LEFT = cfg.trim_pad_left;
            if (cfg.trim_pad_right != null) state.TRIM_PAD_RIGHT = cfg.trim_pad_right;
            if (cfg.trim_dim_alpha != null) state.TRIM_DIM_ALPHA = cfg.trim_dim_alpha;
            if (cfg.show_boundary_phonemes != null) state.SHOW_BOUNDARY_PHONEMES = cfg.show_boundary_phonemes;
            if (cfg.validation_categories) state._validationCategories = cfg.validation_categories;
            if (cfg.low_conf_default_threshold != null) state._lcDefaultThreshold = cfg.low_conf_default_threshold;
            if (cfg.muqattaat_verses) state._muqattaatVerses = new Set(cfg.muqattaat_verses.map(([s,a]) => `${s}:${a}`));
            if (cfg.qalqala_letters) state._qalqalaLetters = new Set(cfg.qalqala_letters);
            if (cfg.standalone_refs) state._standaloneRefs = new Set(cfg.standalone_refs.map(([s,a,w]) => `${s}:${a}:${w}`));
            if (cfg.standalone_words) state._standaloneWords = new Set(cfg.standalone_words);
            if (cfg.accordion_context) state._accordionContext = cfg.accordion_context;
        }
    } catch (_) { /* use CSS defaults */ }

    await surahInfoReady;
    state.segChapterSS = new SearchableSelect(dom.segChapterSelect);

    // Wire cache panel buttons
    document.getElementById('seg-prepare-btn')?.addEventListener('click', () => _prepareAudio(dom.segReciterSelect.value));
    document.getElementById('seg-delete-cache-btn')?.addEventListener('click', () => _deleteAudioCache(dom.segReciterSelect.value));

    loadSegReciters();
});
