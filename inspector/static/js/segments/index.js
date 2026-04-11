/**
 * Segments tab entry point -- DOMContentLoaded, event wiring, config loading.
 * Wires the extracted foundation modules together and registers handlers
 * for event delegation and keyboard shortcuts.
 */

import { state, dom, setClassifyFn } from './state.js';
import { LS_KEYS } from '../shared/constants.js';
import { surahInfoReady } from '../shared/surah-info.js';
import { SearchableSelect } from '../shared/searchable-select.js';
import { _classifySegCategories } from './categories.js';
import { loadSegReciters, onSegReciterChange, onSegChapterChange } from './data.js';
import { applyFiltersAndRender, addSegFilterCondition, clearAllSegFilters } from './filters.js';
import { startSegAnimation, stopSegAnimation, onSegPlayClick, onSegTimeUpdate, onSegAudioEnded } from './playback.js';
import { handleSegRowClick, _handleSegCanvasMousedown, registerHandler } from './event-delegation.js';
import { handleSegKeydown, registerKeyboardHandler } from './keyboard.js';
import { _prepareAudio, _deleteAudioCache } from './audio-cache.js';
import { registerWaveformHandlers } from './waveform.js';

// Phase 7 edit modules
import { enterEditWithBuffer, exitEditMode, registerEditModes, registerEditDrawFns } from './edit-common.js';
import { startRefEdit } from './edit-reference.js';
import { enterTrimMode, confirmTrim, drawTrimWaveform } from './edit-trim.js';
import { enterSplitMode, confirmSplit, drawSplitWaveform } from './edit-split.js';
import { mergeAdjacent } from './edit-merge.js';
import { deleteSegment } from './edit-delete.js';
import { onSegSaveClick, hideSavePreview, confirmSaveFromPreview } from './save.js';

// Phase 8 modules
import { renderValidationPanel, captureValPanelState, restoreValPanelState } from './validation.js';
import { renderStatsPanel } from './stats.js';
import { renderEditHistoryPanel, showHistoryView, hideHistoryView } from './history.js';
import { clearHistoryFilters, setHistorySort } from './history-filters.js';
import { playErrorCardAudio, stopErrorCardAudio } from './error-card-audio.js';
import { ensureContextShown, _isWrapperContextShown } from './error-cards.js';

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

    // Register event delegation handlers (edit operations)
    registerHandler('startRefEdit', startRefEdit);
    registerHandler('enterEditWithBuffer', enterEditWithBuffer);
    registerHandler('mergeAdjacent', mergeAdjacent);
    registerHandler('deleteSegment', deleteSegment);
    registerHandler('playErrorCardAudio', playErrorCardAudio);
    registerHandler('ensureContextShown', ensureContextShown);
    registerHandler('_isWrapperContextShown', _isWrapperContextShown);

    // Register keyboard handlers
    registerKeyboardHandler('onSegSaveClick', onSegSaveClick);
    registerKeyboardHandler('hideSavePreview', hideSavePreview);
    registerKeyboardHandler('confirmSaveFromPreview', confirmSaveFromPreview);
    registerKeyboardHandler('exitEditMode', exitEditMode);
    registerKeyboardHandler('confirmTrim', confirmTrim);
    registerKeyboardHandler('confirmSplit', confirmSplit);
    registerKeyboardHandler('startRefEdit', startRefEdit);

    // Save button
    dom.segSaveBtn.addEventListener('click', onSegSaveClick);

    // History view handlers
    dom.segHistoryBtn?.addEventListener('click', showHistoryView);
    dom.segHistoryBackBtn?.addEventListener('click', hideHistoryView);
    dom.segHistoryFilterClear?.addEventListener('click', clearHistoryFilters);
    dom.segHistorySortTime?.addEventListener('click', () => setHistorySort('time'));
    dom.segHistorySortQuran?.addEventListener('click', () => setHistorySort('quran'));

    // Save preview handlers
    dom.segSavePreviewCancel?.addEventListener('click', hideSavePreview);
    dom.segSavePreviewConfirm?.addEventListener('click', confirmSaveFromPreview);

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
