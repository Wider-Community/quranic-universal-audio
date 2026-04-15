/**
 * Segments tab entry point — wires imperative Wave 6-10 modules together.
 *
 * Wave 5 note: SegmentsTab.svelte now owns reciter/chapter/verse selection,
 * filter bar, navigation banner, segment list rendering, and CSS-var config.
 * This file retains DOM-ref acquisition + event-delegation / keyboard /
 * audio / save / history wiring for modules that Waves 6-10 will rewrite.
 *
 * MUST not fire module-top-level DOM access (S2-B07): every DOM read /
 * addEventListener call lives inside the DOMContentLoaded handler.
 */

// Validation / history modules (imports for side-effect registration)
// Note: './stats' removed — StatsPanel.svelte now owns stats rendering (Wave 8b).
import './validation/index';

import { selectedChapter } from '../lib/stores/segments/chapter';
import { LS_KEYS } from '../lib/utils/constants';
import { mustGet } from '../shared/dom';
// Edit modules
import { enterEditWithBuffer, exitEditMode, registerEditDrawFns,registerEditModes } from './edit/common';
import { deleteSegment } from './edit/delete';
import { mergeAdjacent } from './edit/merge';
import { startRefEdit } from './edit/reference';
import { confirmSplit, drawSplitWaveform,enterSplitMode } from './edit/split';
import { confirmTrim, drawTrimWaveform,enterTrimMode } from './edit/trim';
import { _handleSegCanvasMousedown, handleSegRowClick, registerAllSegEventHandlers } from './event-delegation';
import { showHistoryView } from './history/index';
import { handleSegKeydown, registerAllSegKeyboardHandlers } from './keyboard';
import { _deleteAudioCache,_prepareAudio } from './playback/audio-cache';
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
// DOMContentLoaded — SegmentsTab.svelte has mounted by this point (Svelte
// synchronous `new App()` in main.ts runs BEFORE DOMContentLoaded fires
// because ES module scripts are defer-loaded). All seg-* IDs in the markup
// are visible to `mustGet` calls below.
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
    // Initialize DOM references (Wave 6-10 consumers read these off `dom.*`).
    dom.segReciterSelect = mustGet<HTMLSelectElement>('seg-reciter-select');
    // Note: no #seg-chapter-select in the DOM — SearchableSelect (Svelte) owns
    // chapter selection now. Wave 6+ imperative code that needs "current
    // chapter" reads the `selectedChapter` store (via the SegmentsTab bridge,
    // state.* is mirrored there) or queries the store directly.
    // Provide a shim that mimics the old `<select>` so callers reading
    // `dom.segChapterSelect.value` still work during the Wave 5-10 interim.
    dom.segChapterSelect = _makeChapterSelectShim();
    dom.segVerseSelect = mustGet<HTMLSelectElement>('seg-verse-select');
    dom.segListEl = mustGet<HTMLDivElement>('seg-list');
    // dom.segAudioEl, dom.segPlayBtn, dom.segAutoPlayBtn, dom.segPlayStatus are
    // assigned by SegmentsAudioControls.svelte onMount (Wave 6a). By the time
    // this DOMContentLoaded handler runs, Svelte has already mounted synchronously
    // (main.ts is type="module" → defer; Svelte new App() runs before DCL fires),
    // so the component's onMount has fired and all four dom.* refs are set.
    dom.segSpeedSelect = mustGet<HTMLSelectElement>('seg-speed-select');
    dom.segSaveBtn = mustGet<HTMLButtonElement>('seg-save-btn');
    dom.segValidationGlobalEl = mustGet<HTMLDivElement>('seg-validation-global');
    dom.segValidationEl = mustGet<HTMLDivElement>('seg-validation');
    // dom.segStatsPanel / dom.segStatsCharts removed: StatsPanel.svelte owns
    // these elements reactively via $segStats store (Wave 8b).
    dom.segFilterBarEl = mustGet<HTMLDivElement>('seg-filter-bar');
    dom.segFilterRowsEl = mustGet<HTMLDivElement>('seg-filter-rows');
    dom.segFilterAddBtn = mustGet<HTMLButtonElement>('seg-filter-add-btn');
    dom.segFilterClearBtn = mustGet<HTMLButtonElement>('seg-filter-clear-btn');
    dom.segFilterCountEl = mustGet<HTMLElement>('seg-filter-count');
    dom.segFilterStatusEl = mustGet<HTMLElement>('seg-filter-status');
    dom.segHistoryView = mustGet<HTMLDivElement>('seg-history-view');
    dom.segHistoryBtn = mustGet<HTMLButtonElement>('seg-history-btn');
    // Wave 10: HistoryPanel.svelte owns the interior of #seg-history-view
    // (toolbar, stats, filter pills, batches list). The back button + filter
    // clear + sort toggles are reactive inside HistoryPanel/HistoryFilters;
    // their DOM refs are no longer needed by imperative code. segHistoryStats
    // / segHistoryBatches are left typed on `dom` for now (reading sites are
    // either orphan modules — history/filters.ts, history/rendering.ts
    // default-arg — or removed). They remain unset and any new reader would
    // error loudly, which is the correct posture during migration.
    dom.segSavePreview = mustGet<HTMLDivElement>('seg-save-preview');
    dom.segSavePreviewCancel = mustGet<HTMLButtonElement>('seg-save-preview-cancel');
    dom.segSavePreviewConfirm = mustGet<HTMLButtonElement>('seg-save-preview-confirm');
    dom.segSavePreviewStats = mustGet<HTMLDivElement>('seg-save-preview-stats');
    dom.segSavePreviewBatches = mustGet<HTMLDivElement>('seg-save-preview-batches');

    // Restore persisted speed. Autoplay state + button class restored by
    // SegmentsAudioControls.svelte onMount (Wave 6a). Audio event listeners
    // (play/pause/ended/timeupdate) and play/autoplay button click handlers
    // have moved there too.
    const _savedSegSpeed = localStorage.getItem(LS_KEYS.SEG_SPEED);
    if (_savedSegSpeed) dom.segSpeedSelect.value = _savedSegSpeed;

    dom.segSpeedSelect.addEventListener('change', () => {
        const rate = parseFloat(dom.segSpeedSelect.value);
        dom.segAudioEl.playbackRate = rate;
        if (state.valCardAudio) state.valCardAudio.playbackRate = rate;
        localStorage.setItem(LS_KEYS.SEG_SPEED, dom.segSpeedSelect.value);
    });

    document.addEventListener('keydown', handleSegKeydown);

    // Delegated event listeners for segment card actions (Wave-7 edit scope).
    [dom.segListEl, dom.segValidationEl, dom.segValidationGlobalEl, dom.segHistoryView, dom.segSavePreview].forEach(el => {
        el.addEventListener('click', handleSegRowClick);
        el.addEventListener('mousedown', _handleSegCanvasMousedown);
    });

    // Register event delegation + keyboard handlers.
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

    // History view handlers (Wave 10: HistoryPanel owns back/filter/sort
    // interactions declaratively via the history store; only the external
    // "Open History" button stays imperative because it lives outside the
    // panel and drives the show transition + sibling-hide cross-tab logic).
    dom.segHistoryBtn?.addEventListener('click', showHistoryView);

    // Save preview handlers
    dom.segSavePreviewCancel?.addEventListener('click', () => hideSavePreview());
    dom.segSavePreviewConfirm?.addEventListener('click', confirmSaveFromPreview);

    // Wire cache panel buttons (Wave-6 audio-cache scope).
    const prepareBtn = document.getElementById('seg-prepare-btn');
    const deleteBtn = document.getElementById('seg-delete-cache-btn');
    prepareBtn?.addEventListener('click', () => _prepareAudio(dom.segReciterSelect.value));
    deleteBtn?.addEventListener('click', () => _deleteAudioCache(dom.segReciterSelect.value));
});

// ---------------------------------------------------------------------------
// Shim `dom.segChapterSelect` — imperative Wave 6-10 code reads `.value` and
// occasionally writes to it (e.g. navigation.jumpToSegment used to do
// `dom.segChapterSelect.value = String(chapter); onSegChapterChange()`).
// SegmentsTab.svelte owns the real chapter selector (SearchableSelect); this
// shim keeps the Stage-1 API shape so code doesn't panic on `.value` reads.
// The shim reads/writes the `selectedChapter` Svelte store; writes trigger a
// programmatic chapter change via `SegmentsTab.onChapterChange`.
// ---------------------------------------------------------------------------
function _makeChapterSelectShim(): HTMLSelectElement {
    // We construct a detached <select> so consumers still get a real element
    // API. The shim's `value` getter reads from the `selectedChapter` Svelte
    // store; setter writes back. Consumers that iterate options / call
    // `addEventListener('change')` will find nothing — but no Wave 6-10 code
    // does that; only `.value` reads/writes. Verified by grep.
    //
    // IMPORTANT: writes via `dom.segChapterSelect.value = X` set the store
    // but do NOT trigger the Svelte-owned chapter-load flow. Callers that
    // want a full reload must also invoke `SegmentsTab.onChapterChange` — in
    // Wave 5 only `navigation.jumpToSegment` does this, and that function is
    // about to be deleted in this commit cluster (shrink step) since Wave 8
    // (validation) owns the jump flow via its imperative panel.
    const stub = document.createElement('select');
    Object.defineProperty(stub, 'value', {
        get() {
            let v = '';
            selectedChapter.subscribe((x) => { v = x; })();
            return v;
        },
        set(v: string) {
            selectedChapter.set(v);
        },
    });
    return stub;
}
