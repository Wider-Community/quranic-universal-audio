/**
 * Segments tab entry point -- DOMContentLoaded, event wiring, config loading.
 * Wires the extracted foundation modules together, and registers handler stubs
 * for Phase 7/8 functions that still live in segments.js.
 */

import { state, dom, setClassifyFn } from './state.js';
import { LS_KEYS } from '../shared/constants.js';
import { surahInfoReady } from '../shared/surah-info.js';
import { SearchableSelect } from '../shared/searchable-select.js';
import { _classifySegCategories } from './categories.js';
import { loadSegReciters, onSegReciterChange, onSegChapterChange, registerDataHandlers } from './data.js';
import { applyFiltersAndRender, addSegFilterCondition, clearAllSegFilters } from './filters.js';
import { startSegAnimation, stopSegAnimation, onSegPlayClick, onSegTimeUpdate, onSegAudioEnded } from './playback.js';
import { registerPlaybackHandlers } from './playback.js';
import { handleSegRowClick, _handleSegCanvasMousedown, registerHandler } from './event-delegation.js';
import { handleSegKeydown, registerKeyboardHandler } from './keyboard.js';
import { _prepareAudio, _deleteAudioCache } from './audio-cache.js';
import { registerWaveformHandlers } from './waveform.js';

// ---------------------------------------------------------------------------
// Inject the classify function to break the state <-> categories cycle
// ---------------------------------------------------------------------------
setClassifyFn(_classifySegCategories);

// ---------------------------------------------------------------------------
// DOMContentLoaded
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
    // Initialize DOM references
    dom.segReciterSelect = document.getElementById('seg-reciter-select');
    dom.segChapterSelect = document.getElementById('seg-chapter-select');
    dom.segVerseSelect = document.getElementById('seg-verse-select');
    dom.segListEl = document.getElementById('seg-list');
    dom.segAudioEl = document.getElementById('seg-audio-player');
    dom.segPlayBtn = document.getElementById('seg-play-btn');
    dom.segAutoPlayBtn = document.getElementById('seg-autoplay-btn');
    dom.segSpeedSelect = document.getElementById('seg-speed-select');
    dom.segSaveBtn = document.getElementById('seg-save-btn');
    dom.segPlayStatus = document.getElementById('seg-play-status');
    dom.segValidationGlobalEl = document.getElementById('seg-validation-global');
    dom.segValidationEl = document.getElementById('seg-validation');
    dom.segStatsPanel = document.getElementById('seg-stats-panel');
    dom.segStatsCharts = document.getElementById('seg-stats-charts');
    dom.segFilterBarEl = document.getElementById('seg-filter-bar');
    dom.segFilterRowsEl = document.getElementById('seg-filter-rows');
    dom.segFilterAddBtn = document.getElementById('seg-filter-add-btn');
    dom.segFilterClearBtn = document.getElementById('seg-filter-clear-btn');
    dom.segFilterCountEl = document.getElementById('seg-filter-count');
    dom.segFilterStatusEl = document.getElementById('seg-filter-status');
    dom.segHistoryView = document.getElementById('seg-history-view');
    dom.segHistoryBtn = document.getElementById('seg-history-btn');
    dom.segHistoryBackBtn = document.getElementById('seg-history-back-btn');
    dom.segHistoryStats = document.getElementById('seg-history-stats');
    dom.segHistoryBatches = document.getElementById('seg-history-batches');
    dom.segHistoryFilters = document.getElementById('seg-history-filters');
    dom.segHistoryFilterOps = document.getElementById('seg-history-filter-ops');
    dom.segHistoryFilterCats = document.getElementById('seg-history-filter-cats');
    dom.segHistoryFilterClear = document.getElementById('seg-history-filter-clear');
    dom.segHistorySortTime = document.getElementById('seg-history-sort-time');
    dom.segHistorySortQuran = document.getElementById('seg-history-sort-quran');
    dom.segSavePreview = document.getElementById('seg-save-preview');
    dom.segSavePreviewCancel = document.getElementById('seg-save-preview-cancel');
    dom.segSavePreviewConfirm = document.getElementById('seg-save-preview-confirm');
    dom.segSavePreviewStats = document.getElementById('seg-save-preview-stats');
    dom.segSavePreviewBatches = document.getElementById('seg-save-preview-batches');

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
        localStorage.setItem(LS_KEYS.SEG_AUTOPLAY, state._segAutoPlayEnabled);
    });
    // Save button wired via keyboard handler registration from segments.js
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

    // Load display config
    try {
        const cfgResp = await fetch('/api/seg/config');
        if (cfgResp.ok) {
            const cfg = await cfgResp.json();
            const root = document.documentElement.style;
            if (cfg.seg_font_size) root.setProperty('--seg-font-size', cfg.seg_font_size);
            if (cfg.seg_word_spacing) root.setProperty('--seg-word-spacing', cfg.seg_word_spacing);
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
        }
    } catch (_) { /* use CSS defaults */ }

    await surahInfoReady;
    state.segChapterSS = new SearchableSelect(dom.segChapterSelect);

    // Wire cache panel buttons
    document.getElementById('seg-prepare-btn')?.addEventListener('click', () => _prepareAudio(dom.segReciterSelect.value));
    document.getElementById('seg-delete-cache-btn')?.addEventListener('click', () => _deleteAudioCache(dom.segReciterSelect.value));

    loadSegReciters();
});

// ---------------------------------------------------------------------------
// Registration API for Phase 7/8 modules (segments.js calls these)
// ---------------------------------------------------------------------------

/**
 * Register handlers from the remaining segments.js code.
 * Called from segments.js after all functions are defined.
 */
export function registerSegHandlers(handlers) {
    // Event delegation handlers (edit operations)
    if (handlers.startRefEdit) registerHandler('startRefEdit', handlers.startRefEdit);
    if (handlers.enterEditWithBuffer) registerHandler('enterEditWithBuffer', handlers.enterEditWithBuffer);
    if (handlers.mergeAdjacent) registerHandler('mergeAdjacent', handlers.mergeAdjacent);
    if (handlers.deleteSegment) registerHandler('deleteSegment', handlers.deleteSegment);
    if (handlers.playErrorCardAudio) registerHandler('playErrorCardAudio', handlers.playErrorCardAudio);
    if (handlers.ensureContextShown) registerHandler('ensureContextShown', handlers.ensureContextShown);
    if (handlers._isWrapperContextShown) registerHandler('_isWrapperContextShown', handlers._isWrapperContextShown);

    // Keyboard handlers (save, undo, edit)
    if (handlers.onSegSaveClick) registerKeyboardHandler('onSegSaveClick', handlers.onSegSaveClick);
    if (handlers.hideSavePreview) registerKeyboardHandler('hideSavePreview', handlers.hideSavePreview);
    if (handlers.confirmSaveFromPreview) registerKeyboardHandler('confirmSaveFromPreview', handlers.confirmSaveFromPreview);
    if (handlers.exitEditMode) registerKeyboardHandler('exitEditMode', handlers.exitEditMode);
    if (handlers.confirmTrim) registerKeyboardHandler('confirmTrim', handlers.confirmTrim);
    if (handlers.confirmSplit) registerKeyboardHandler('confirmSplit', handlers.confirmSplit);
    if (handlers.startRefEdit) registerKeyboardHandler('startRefEdit', handlers.startRefEdit);

    // Save button
    if (handlers.onSegSaveClick) {
        dom.segSaveBtn?.addEventListener('click', handlers.onSegSaveClick);
    }

    // History view handlers
    if (handlers.showHistoryView) dom.segHistoryBtn?.addEventListener('click', handlers.showHistoryView);
    if (handlers.hideHistoryView) dom.segHistoryBackBtn?.addEventListener('click', handlers.hideHistoryView);
    if (handlers.clearHistoryFilters) dom.segHistoryFilterClear?.addEventListener('click', handlers.clearHistoryFilters);
    if (handlers.setHistorySort) {
        dom.segHistorySortTime?.addEventListener('click', () => handlers.setHistorySort('time'));
        dom.segHistorySortQuran?.addEventListener('click', () => handlers.setHistorySort('quran'));
    }
    if (handlers.hideSavePreview) dom.segSavePreviewCancel?.addEventListener('click', handlers.hideSavePreview);
    if (handlers.confirmSaveFromPreview) dom.segSavePreviewConfirm?.addEventListener('click', handlers.confirmSaveFromPreview);

    // Data handlers (validation, stats, history rendering)
    registerDataHandlers({
        renderValidationPanel: handlers.renderValidationPanel,
        renderStatsPanel: handlers.renderStatsPanel,
        renderEditHistoryPanel: handlers.renderEditHistoryPanel,
        captureValPanelState: handlers.captureValPanelState,
        restoreValPanelState: handlers.restoreValPanelState,
    });

    // Playback handlers
    registerPlaybackHandlers({
        stopErrorCardAudio: handlers.stopErrorCardAudio,
    });

    // Waveform handlers (edit-mode draw functions)
    registerWaveformHandlers({
        drawSplitWaveform: handlers.drawSplitWaveform,
        drawTrimWaveform: handlers.drawTrimWaveform,
    });
}
