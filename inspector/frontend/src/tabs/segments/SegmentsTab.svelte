<script lang="ts">
    /**
     * SegmentsTab — top-level Svelte component for the Segments tab.
     *
     * Owns reciter/chapter/verse dropdowns, filter bar, navigation banner,
     * segment list rendering, CSS-var config, and all tab-level event wiring
     * (keyboard shortcuts, save/history/cache button clicks, delegated card
     * clicks on imperative containers, speed control). Mounts validation,
     * history, and save-preview panels as Svelte children.
     *
     * Imperative edit / validation / history / save / playback / waveform
     * modules still read the shared `state.*` + `dom.*` objects; SegmentsTab
     * mirrors Svelte stores into `state.*` below so those modules see
     * consistent values.
     */

    import { get } from 'svelte/store';
    import { onMount, tick } from 'svelte';

    import { isDirty } from '../../lib/stores/segments/dirty';
    import { mustGet } from '../../shared/dom';
    import { shouldHandleKey } from '../../lib/utils/keyboard-guard';
    import { cycleSpeed } from '../../lib/utils/speed-control';
    import { attachImperativeCardListeners } from '../../lib/utils/segments/imperative-card-click';
    import { _deleteAudioCache, _prepareAudio } from '../../lib/utils/segments/audio-cache-ui';
    import { _getEditCanvas } from '../../lib/utils/segments/get-edit-canvas';
    import {
        registerDataLookups,
        registerGetEditCanvas,
        registerWaveformHandlers,
    } from '../../lib/utils/segments/waveform-utils';
    import { onSegReciterChange, registerFetchChapterPeaks, registerStopSegAnimation } from '../../segments/data';
    import {
        exitEditMode,
        registerEditDrawFns,
        registerEditModes,
    } from '../../segments/edit/common';
    import { confirmSplit, drawSplitWaveform, enterSplitMode } from '../../segments/edit/split';
    import { confirmTrim, drawTrimWaveform, enterTrimMode } from '../../segments/edit/trim';
    import { startRefEdit } from '../../segments/edit/reference';
    import { registerOnSegReciterChange, showHistoryView } from '../../segments/history/index';
    import { onSegPlayClick, playFromSegment } from '../../segments/playback/index';
    import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from '../../segments/save';
    import { _restoreFilterView } from '../../segments/navigation';
    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import { fetchJson, fetchJsonOrNull } from '../../lib/api';
    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
        segAllData,
        segAllReciters,
        segData,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        verseOptions,
    } from '../../lib/stores/segments/chapter';
    import {
        activeFilters,
        segIndexMap,
        displayedSegments,
    } from '../../lib/stores/segments/filters';
    import { clearEdit } from '../../lib/stores/segments/edit';
    import { clearStats, segStats, setStats } from '../../lib/stores/segments/stats';
    import { clearValidation, segValidation, setValidation } from '../../lib/stores/segments/validation';
    import { savedFilterView } from '../../lib/stores/segments/navigation';
    import { clearSavePreviewData, hidePreview } from '../../lib/stores/segments/save';
    import { segConfig as segConfigStore } from '../../lib/stores/segments/config';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady, surahOptionText } from '../../lib/utils/surah-info';
    import type { SegReciter } from '../../types/domain';

    // Imperative Wave 6-10 modules — SegmentsTab handles the reciter/
    // chapter fetch cascade directly (inlined from segments/data.ts) so it
    // writes to Svelte stores instead of to dom.segChapterSelect /
    // dom.segVerseSelect which Svelte now owns. Wave 6+ rendering
    // (validation / stats / history) stays imperative and is invoked from
    // here.
    import { _fetchCacheStatus, _rewriteAudioUrls } from '../../lib/utils/segments/audio-cache-ui';
    import { _isCurrentReciterBySurah } from '../../lib/utils/segments/reciter';
    import { setHistoryData, setHistoryVisible } from '../../lib/stores/segments/history';
    import { renderEditHistoryPanel } from '../../segments/history/index';
    import HistoryPanel from './history/HistoryPanel.svelte';
    import { stopSegAnimation } from '../../segments/playback/index';
    import { computeSilenceAfter } from '../../lib/stores/segments/filters';
    import { state } from '../../segments/state';
    import { _fetchChapterPeaksIfNeeded } from '../../lib/utils/segments/waveform-utils';
    import ValidationPanel from './validation/ValidationPanel.svelte';
    import { clearWaveformCache } from '../../lib/utils/waveform-cache';
    import type {
        SegAllResponse,
        SegChaptersResponse,
        SegDataResponse,
        SegEditHistoryResponse,
        SegStatsResponse,
        SegValidateResponse,
    } from '../../types/api';
    import type { Segment } from '../../types/domain';
    import EditOverlay from './edit/EditOverlay.svelte';
    import FiltersBar from './FiltersBar.svelte';
    import SegmentsList from './SegmentsList.svelte';
    import SegmentsAudioControls from './SegmentsAudioControls.svelte';
    import StatsPanel from './StatsPanel.svelte';
    import SavePreview from './save/SavePreview.svelte';

    // Audio element ref exposed from SegmentsAudioControls via bind:audioEl.
    // EditOverlay uses this (S2-D33) instead of document.getElementById.
    let segAudioEl: HTMLAudioElement | null = null;

    // ---- Derived UI state ----
    interface GroupedReciters {
        group: string;
        items: SegReciter[];
    }
    $: groupedReciters = ((): GroupedReciters[] => {
        const grouped: Record<string, SegReciter[]> = {};
        const uncategorized: SegReciter[] = [];
        for (const r of $segAllReciters) {
            const src = r.audio_source || '';
            if (src) {
                if (!grouped[src]) grouped[src] = [];
                grouped[src]!.push(r);
            } else {
                uncategorized.push(r);
            }
        }
        const out: GroupedReciters[] = [];
        for (const src of Object.keys(grouped).sort()) {
            out.push({ group: src, items: grouped[src] ?? [] });
        }
        if (uncategorized.length > 0) out.push({ group: '(uncategorized)', items: uncategorized });
        return out;
    })();

    $: chaptersOptions = $segAllData
        ? (() => {
            // Derive chapter list from segAllData (same source the old dropdown used).
            const chapters = new Set<number>();
            for (const s of $segAllData.segments) {
                if (s.chapter != null) chapters.add(s.chapter);
            }
            return [...chapters].sort((a, b) => a - b).map((ch) => ({
                value: String(ch),
                label: surahOptionText(ch),
            }));
        })()
        : [];

    $: filterBarHidden = $segAllData === null;

    $: segConfig = state; // alias to read TRIM_PAD_LEFT etc. reactively (state is a plain object)
    void segConfig; // silence unused-var

    // ---------------------------------------------------------------------
    // Bridge: sync Svelte stores → state.* for Wave 6+ imperative consumers
    // ---------------------------------------------------------------------

    $: state.segAllData = $segAllData;
    $: state.segData = $segData;
    $: state.segAllReciters = $segAllReciters;
    $: state.segActiveFilters = $activeFilters;
    $: state.segDisplayedSegments = $displayedSegments;
    $: state._segIndexMap = $segIndexMap;
    $: state._segSavedFilterView = $savedFilterView;
    $: state.segValidation = $segValidation; // Wave 8a: store → state bridge for imperative consumers
    // Wave 8b CF (Wave 9): state.segStatsData field deleted — StatsPanel.svelte reads $segStats directly.

    // ---------------------------------------------------------------------
    // Config (CSS vars + edit-mode constants)
    // ---------------------------------------------------------------------

    let cssFontSize: string = '';
    let cssWordSpacing: string = '';

    async function loadSegConfig(): Promise<void> {
        try {
            const cfg = await fetchJsonOrNull<{
                seg_font_size?: string;
                seg_word_spacing?: string;
                trim_pad_left?: number;
                trim_pad_right?: number;
                trim_dim_alpha?: number;
                show_boundary_phonemes?: boolean;
                validation_categories?: string[];
                low_conf_default_threshold?: number;
                muqattaat_verses?: Array<[number, number]>;
                qalqala_letters?: string[];
                standalone_refs?: Array<[number, number, number]>;
                standalone_words?: string[];
                accordion_context?: Record<string, string>;
            }>('/api/seg/config');
            if (!cfg) return;
            if (cfg.seg_font_size) cssFontSize = String(cfg.seg_font_size);
            if (cfg.seg_word_spacing) cssWordSpacing = String(cfg.seg_word_spacing);
            if (cfg.trim_pad_left != null) state.TRIM_PAD_LEFT = cfg.trim_pad_left;
            if (cfg.trim_pad_right != null) state.TRIM_PAD_RIGHT = cfg.trim_pad_right;
            if (cfg.trim_dim_alpha != null) state.TRIM_DIM_ALPHA = cfg.trim_dim_alpha;
            if (cfg.show_boundary_phonemes != null)
                state.SHOW_BOUNDARY_PHONEMES = cfg.show_boundary_phonemes;
            if (cfg.validation_categories) state._validationCategories = cfg.validation_categories;
            if (cfg.low_conf_default_threshold != null)
                state._lcDefaultThreshold = cfg.low_conf_default_threshold;
            if (cfg.muqattaat_verses)
                state._muqattaatVerses = new Set(cfg.muqattaat_verses.map(([s, a]) => `${s}:${a}`));
            if (cfg.qalqala_letters) state._qalqalaLetters = new Set(cfg.qalqala_letters);
            if (cfg.standalone_refs)
                state._standaloneRefs = new Set(
                    cfg.standalone_refs.map(([s, a, w]) => `${s}:${a}:${w}`),
                );
            if (cfg.standalone_words) state._standaloneWords = new Set(cfg.standalone_words);
            if (cfg.accordion_context) state._accordionContext = cfg.accordion_context;
            segConfigStore.set({
                validationCategories: cfg.validation_categories ?? null,
                muqattaatVerses: cfg.muqattaat_verses ? new Set(cfg.muqattaat_verses.map(([s, a]) => `${s}:${a}`)) : null,
                qalqalaLetters: cfg.qalqala_letters ? new Set(cfg.qalqala_letters) : null,
                standaloneRefs: cfg.standalone_refs ? new Set(cfg.standalone_refs.map(([s, a, w]) => `${s}:${a}:${w}`)) : null,
                standaloneWords: cfg.standalone_words ? new Set(cfg.standalone_words) : null,
                lcDefaultThreshold: cfg.low_conf_default_threshold ?? 80,
                showBoundaryPhonemes: cfg.show_boundary_phonemes ?? true,
            });
        } catch {
            /* use CSS defaults */
        }
    }

    // ---------------------------------------------------------------------
    // Reciter / chapter / verse handlers
    // ---------------------------------------------------------------------

    async function loadReciters(): Promise<void> {
        try {
            const rs = await fetchJson<SegReciter[]>('/api/seg/reciters');
            segAllReciters.set(rs);
            const saved = localStorage.getItem(LS_KEYS.SEG_RECITER);
            if (saved) {
                selectedReciter.set(saved);
                await onReciterChange(saved);
            }
        } catch (e) {
            console.error('Error loading seg reciters:', e);
        }
    }

    function onReciterSelectChange(e: Event): void {
        const v = (e.currentTarget as HTMLSelectElement).value;
        selectedReciter.set(v);
        onReciterChange(v);
    }

    async function onReciterChange(reciter: string): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.SEG_RECITER, reciter);

        // Reset selection + per-reciter state.
        selectedChapter.set('');
        selectedVerse.set('');
        activeFilters.set([]);
        savedFilterView.set(null);
        clearPerReciterState();

        if (!reciter) return;

        // Fetch chapters + validate + stats + all + history in parallel.
        const [chResult, valResult, statsResult, allResult, histResult] = await Promise.allSettled([
            fetchJson<SegChaptersResponse>(`/api/seg/chapters/${reciter}`),
            fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`),
            fetchJson<SegStatsResponse>(`/api/seg/stats/${reciter}`),
            fetchJson<SegAllResponse>(`/api/seg/all/${reciter}`),
            fetchJsonOrNull<SegEditHistoryResponse>(`/api/seg/edit-history/${reciter}`),
        ]);

        if (get(selectedReciter) !== reciter) return;
        void chResult; // chapters come from segAllData in Svelte; API response kept to preserve fetch parity

        if (valResult.status === 'fulfilled') {
            setValidation(valResult.value);
            // Wave 8a.2: ValidationPanel.svelte subscribes to $segValidation reactively;
            // no imperative renderValidationPanel call needed.
        } else {
            console.error('Error loading validation:', valResult.reason);
        }

        if (statsResult.status === 'fulfilled') {
            // Wave 8b: StatsPanel.svelte renders reactively via $segStats store.
            if (!statsResult.value.error) setStats(statsResult.value);
        } else {
            console.error('Error loading stats:', statsResult.reason);
        }

        if (allResult.status === 'fulfilled') {
            segAllData.set(allResult.value);
            _rewriteAudioUrls();
            computeSilenceAfter();
            if (_isCurrentReciterBySurah()) _fetchCacheStatus(reciter);
        } else {
            console.error('Error loading all segments:', allResult.reason);
        }

        if (histResult.status === 'fulfilled' && histResult.value) {
            renderEditHistoryPanel(histResult.value);
        }
    }

    /** Clear per-reciter imperative state so validation / stats / history /
     *  save-preview panels reset when the user switches reciter. */
    function clearPerReciterState(): void {
        if (state._waveformObserver) {
            state._waveformObserver.disconnect();
            state._waveformObserver = null;
        }
        segAllData.set(null);
        segData.set(null);
        state.segCurrentIdx = -1;
        state.segDirtyMap.clear();
        state.segOpLog.clear();
        state._pendingOp = null;
        state.segEditMode = null;
        state.segEditIndex = -1;
        clearEdit();

        // Validation panel: Wave 8a.2 — ValidationPanel.svelte reacts to clearValidation()
        // via $segValidation store; no imperative DOM clearing needed.
        clearValidation();

        // Stats panel — Wave 8b: StatsPanel.svelte controls visibility via $segStats store.
        clearStats();

        state._segSavedChains = null;
        const histBtn = document.getElementById('seg-history-btn');
        // Wave 10: HistoryPanel is Svelte-owned — clear reactively (Risk #1).
        setHistoryVisible(false);
        setHistoryData(null);
        const savePrev = document.getElementById('seg-save-preview');
        if (histBtn) (histBtn as HTMLElement).hidden = true;
        if (savePrev) (savePrev as HTMLElement).hidden = true;
        hidePreview();   // notify $savePreviewVisible store
        clearSavePreviewData(); // clear store — SavePreview.svelte empties reactively (Wave 11a)

        state._segPrefetchCache = {};
        state._segContinuousPlay = false;
        state._segPlayEndMs = 0;
        clearWaveformCache();
        if (state._peaksPollTimer) { clearTimeout(state._peaksPollTimer); state._peaksPollTimer = null; }
        state._segPeaksByUrl = null;
        state._observerPeaksQueue = [];
        if (state._observerPeaksTimer) { clearTimeout(state._observerPeaksTimer); state._observerPeaksTimer = null; }
        state._observerPeaksRequested = new Set();

        const cacheBar = document.getElementById('seg-cache-bar');
        if (cacheBar) (cacheBar as HTMLElement).hidden = true;
        if (state._audioCachePollTimer) { clearInterval(state._audioCachePollTimer); state._audioCachePollTimer = null; }

        const saveBtn = document.getElementById('seg-save-btn') as HTMLButtonElement | null;
        const playBtn = document.getElementById('seg-play-btn') as HTMLButtonElement | null;
        const playStatus = document.getElementById('seg-play-status');
        if (saveBtn) saveBtn.disabled = true;
        if (playBtn) playBtn.disabled = true;
        if (playStatus) playStatus.textContent = '';

        stopSegAnimation();
    }

    function onChapterSelectChange(e: CustomEvent<string>): void {
        const v = e.detail;
        selectedChapter.set(v);
        onChapterChange(v);
    }
    // NOTE: imperative callers (navigation.jumpToSegment etc.) that set
    // `dom.segChapterSelect.value = X` via the shim (which sets the
    // selectedChapter store) AND then invoke the imperative
    // onSegChapterChange() from segments/data.ts — they continue to work as
    // before because data.ts reads state.* and writes to state.*. The
    // Svelte bridge then mirrors into the stores. No reactive
    // onChapterChange fires here — we intentionally do NOT subscribe to
    // $selectedChapter to avoid double-fetching on those call paths.

    async function onChapterChange(chapter: string): Promise<void> {
        const reciter = get(selectedReciter);
        selectedVerse.set('');

        const audioEl = document.getElementById('seg-audio-player') as HTMLAudioElement | null;
        const playBtn = document.getElementById('seg-play-btn') as HTMLButtonElement | null;
        if (audioEl) audioEl.src = '';
        if (playBtn) playBtn.disabled = true;
        stopSegAnimation();
        state._segPrefetchCache = {};

        // Wave 8a.2: ValidationPanel.svelte re-derives from $selectedChapter reactively.
        // No imperative renderValidationPanel call needed.

        if (!reciter || !chapter) return;
        if (playBtn) playBtn.disabled = false;

        try {
            const chData = await fetchJson<SegDataResponse>(`/api/seg/data/${reciter}/${chapter}`);
            if (get(selectedReciter) !== reciter || get(selectedChapter) !== chapter) return;
            if (chData.error) return;
            if (_isCurrentReciterBySurah() && chData.audio_url && !chData.audio_url.startsWith('/api/')) {
                chData.audio_url = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(chData.audio_url)}`;
            }

            const chNum = parseInt(chapter);
            // Slice segments into the per-chapter list (Stage-1 behaviour;
            // imperative consumers still read state.segData.segments).
            const all = get(segAllData);
            const chapterSegs: Segment[] = all
                ? all.segments.filter((s) => s.chapter === chNum)
                : [];
            chData.segments = chapterSegs;
            segData.set(chData);
            _fetchChapterPeaksIfNeeded(reciter, chNum);

            if (chData.audio_url && audioEl) {
                audioEl.src = chData.audio_url;
                audioEl.preload = 'metadata';
            }
        } catch (e) {
            console.error('Error loading chapter data:', e);
        }
    }

    function onVerseSelectChange(e: Event): void {
        selectedVerse.set((e.currentTarget as HTMLSelectElement).value);
    }

    // ---------------------------------------------------------------------
    // Saved filter view restore
    // ---------------------------------------------------------------------

    async function onNavigationRestore(): Promise<void> {
        const saved = get(savedFilterView);
        if (!saved) return;
        savedFilterView.set(null);
        activeFilters.set(saved.filters);

        if (saved.chapter !== get(selectedChapter)) {
            selectedChapter.set(saved.chapter);
            await onChapterChange(saved.chapter);
        }
        selectedVerse.set(saved.verse);

        // Scroll the list back to the saved position after the UI re-renders.
        await tick();
        const listEl = document.getElementById('seg-list');
        if (listEl) listEl.scrollTop = saved.scrollTop;
    }

    // Chapter-index helper for imperative code — keep the cached map hot
    // after chapter changes so getChapterSegments() called later returns
    // the same refs renderSegList saw.
    $: if ($segAllData) {
        void getChapterSegments($selectedChapter || 0);
    }

    // ---------------------------------------------------------------------
    // Keyboard shortcuts
    // ---------------------------------------------------------------------

    function handleSegKeydown(e: KeyboardEvent): void {
        if (!shouldHandleKey(e, 'segments')) return;

        switch (e.code) {
            case 'Space':
                e.preventDefault();
                onSegPlayClick();
                break;
            case 'ArrowLeft': {
                e.preventDefault();
                const el = (state._activeAudioSource === 'error' && state.valCardAudio) ? state.valCardAudio : dom.segAudioEl;
                el.currentTime = Math.max(0, el.currentTime - 3);
                break;
            }
            case 'ArrowRight': {
                e.preventDefault();
                const el = (state._activeAudioSource === 'error' && state.valCardAudio) ? state.valCardAudio : dom.segAudioEl;
                el.currentTime = Math.min(el.duration || 0, el.currentTime + 3);
                break;
            }
            case 'ArrowUp': {
                e.preventDefault();
                if (!state.segDisplayedSegments || state.segDisplayedSegments.length === 0) break;
                const curPos = state.segDisplayedSegments.findIndex(s => s.index === state.segCurrentIdx);
                const prevPos = curPos > 0 ? curPos - 1 : 0;
                const prev = state.segDisplayedSegments[prevPos];
                if (prev) playFromSegment(prev.index, prev.chapter);
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                if (!state.segDisplayedSegments || state.segDisplayedSegments.length === 0) break;
                const curPos = state.segDisplayedSegments.findIndex(s => s.index === state.segCurrentIdx);
                const nextPos = curPos >= 0 && curPos < state.segDisplayedSegments.length - 1 ? curPos + 1 : (curPos === -1 ? 0 : curPos);
                const nxt = state.segDisplayedSegments[nextPos];
                if (nxt) playFromSegment(nxt.index, nxt.chapter);
                break;
            }
            case 'Period':
            case 'Comma': {
                e.preventDefault();
                cycleSpeed(dom.segSpeedSelect, dom.segAudioEl, e.code === 'Period' ? 'up' : 'down', LS_KEYS.SEG_SPEED);
                if (state.valCardAudio) state.valCardAudio.playbackRate = parseFloat(dom.segSpeedSelect.value);
                break;
            }
            case 'KeyJ': {
                e.preventDefault();
                const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`);
                if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                break;
            }
            case 'KeyS': {
                if (isDirty()) {
                    e.preventDefault();
                    onSegSaveClick();
                }
                break;
            }
            case 'Escape':
                if (!dom.segSavePreview.hidden) {
                    e.preventDefault();
                    hideSavePreview();
                } else if (state.segEditMode) {
                    e.preventDefault();
                    exitEditMode();
                } else if (state._segSavedFilterView) {
                    e.preventDefault();
                    _restoreFilterView();
                }
                break;

            case 'Enter':
                if (!dom.segSavePreview.hidden) {
                    e.preventDefault();
                    confirmSaveFromPreview();
                } else if (state.segEditMode && state.segCurrentIdx >= 0) {
                    e.preventDefault();
                    const seg = state.segDisplayedSegments
                        ? state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx)
                        : null;
                    if (seg) {
                        if (state.segEditMode === 'trim') confirmTrim(seg);
                        else if (state.segEditMode === 'split') confirmSplit(seg);
                    }
                }
                break;

            case 'KeyE': {
                if (state.segEditMode || state.segCurrentIdx < 0) break;
                e.preventDefault();
                const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`);
                const seg = state.segDisplayedSegments
                    ? state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx)
                    : null;
                if (row && seg) {
                    const refSpan = row.querySelector<HTMLElement>('.seg-text-ref');
                    if (refSpan) startRefEdit(refSpan, seg, row);
                }
                break;
            }
        }
    }

    // ---------------------------------------------------------------------
    // Chapter-select shim
    //
    // Legacy imperative code reads `dom.segChapterSelect.value` (and rarely
    // writes it). SearchableSelect (Svelte) owns the real chapter selector
    // now; this detached <select> element proxies `.value` reads/writes to
    // the `selectedChapter` store. Writes set the store but do NOT trigger a
    // reload — callers that want a full reload must also invoke
    // onChapterChange directly.
    // ---------------------------------------------------------------------
    function _makeChapterSelectShim(): HTMLSelectElement {
        const stub = document.createElement('select');
        Object.defineProperty(stub, 'value', {
            get() {
                return get(selectedChapter);
            },
            set(v: string) {
                selectedChapter.set(v);
            },
        });
        return stub;
    }

    // ---------------------------------------------------------------------
    // Registrations + DOM-ref init (run once at mount)
    // ---------------------------------------------------------------------

    let segmentsInitialized = false;

    function initSegmentRegistrations(): void {
        if (segmentsInitialized) return;
        segmentsInitialized = true;

        // Edit-mode wiring (breaks edit-common ↔ edit-trim/split cycle).
        registerEditModes(enterTrimMode, enterSplitMode);
        registerEditDrawFns(drawTrimWaveform, drawSplitWaveform);
        registerWaveformHandlers({ drawSplitWaveform, drawTrimWaveform });

        // Break circular deps: data ↔ playback, history ↔ data, waveform ↔ data/rendering.
        registerStopSegAnimation(stopSegAnimation);
        registerOnSegReciterChange(onSegReciterChange);
        registerGetEditCanvas(_getEditCanvas);
        registerFetchChapterPeaks(_fetchChapterPeaksIfNeeded);
        registerDataLookups(getAdjacentSegments, getSegByChapterIndex);
    }

    // ---------------------------------------------------------------------
    // Mount
    // ---------------------------------------------------------------------

    onMount(async () => {
        initSegmentRegistrations();

        // Initialize DOM references. Svelte has already synchronously
        // rendered the markup below, so every seg-* id resolves here.
        dom.segReciterSelect = mustGet<HTMLSelectElement>('seg-reciter-select');
        dom.segChapterSelect = _makeChapterSelectShim();
        dom.segVerseSelect = mustGet<HTMLSelectElement>('seg-verse-select');
        dom.segListEl = mustGet<HTMLDivElement>('seg-list');
        // dom.segAudioEl, dom.segPlayBtn, dom.segAutoPlayBtn, dom.segPlayStatus
        // are assigned by SegmentsAudioControls.svelte onMount.
        dom.segSpeedSelect = mustGet<HTMLSelectElement>('seg-speed-select');
        dom.segSaveBtn = mustGet<HTMLButtonElement>('seg-save-btn');
        dom.segValidationGlobalEl = mustGet<HTMLDivElement>('seg-validation-global');
        dom.segValidationEl = mustGet<HTMLDivElement>('seg-validation');
        dom.segFilterBarEl = mustGet<HTMLDivElement>('seg-filter-bar');
        dom.segFilterRowsEl = mustGet<HTMLDivElement>('seg-filter-rows');
        dom.segFilterAddBtn = mustGet<HTMLButtonElement>('seg-filter-add-btn');
        dom.segFilterClearBtn = mustGet<HTMLButtonElement>('seg-filter-clear-btn');
        dom.segFilterCountEl = mustGet<HTMLElement>('seg-filter-count');
        dom.segFilterStatusEl = mustGet<HTMLElement>('seg-filter-status');
        dom.segHistoryView = mustGet<HTMLDivElement>('seg-history-view');
        dom.segHistoryBtn = mustGet<HTMLButtonElement>('seg-history-btn');
        dom.segSavePreview = mustGet<HTMLDivElement>('seg-save-preview');
        dom.segSavePreviewCancel = mustGet<HTMLButtonElement>('seg-save-preview-cancel');
        dom.segSavePreviewConfirm = mustGet<HTMLButtonElement>('seg-save-preview-confirm');

        // Restore persisted speed.
        const _savedSegSpeed = localStorage.getItem(LS_KEYS.SEG_SPEED);
        if (_savedSegSpeed) dom.segSpeedSelect.value = _savedSegSpeed;

        dom.segSpeedSelect.addEventListener('change', () => {
            const rate = parseFloat(dom.segSpeedSelect.value);
            dom.segAudioEl.playbackRate = rate;
            if (state.valCardAudio) state.valCardAudio.playbackRate = rate;
            localStorage.setItem(LS_KEYS.SEG_SPEED, dom.segSpeedSelect.value);
        });

        // Delegated click + canvas-scrub listeners for imperative card containers.
        attachImperativeCardListeners();

        // Save button
        dom.segSaveBtn.addEventListener('click', onSegSaveClick);

        // History open button (panel-local back/filter interactions live in HistoryPanel).
        dom.segHistoryBtn?.addEventListener('click', showHistoryView);

        // Save preview cancel / confirm
        dom.segSavePreviewCancel?.addEventListener('click', () => hideSavePreview());
        dom.segSavePreviewConfirm?.addEventListener('click', confirmSaveFromPreview);

        // Cache panel buttons
        const prepareBtn = document.getElementById('seg-prepare-btn');
        const deleteBtn = document.getElementById('seg-delete-cache-btn');
        prepareBtn?.addEventListener('click', () => _prepareAudio(dom.segReciterSelect.value));
        deleteBtn?.addEventListener('click', () => _deleteAudioCache(dom.segReciterSelect.value));

        await surahInfoReady;
        await loadSegConfig();
        await loadReciters();
    });
</script>

<svelte:window on:keydown={handleSegKeydown} />

<div
    id="segments-panel-inner"
    style:--seg-font-size={cssFontSize || null}
    style:--seg-word-spacing={cssWordSpacing || null}
>
    <div class="info-bar seg-selector-bar">
        <label>Reciter:
            <select
                id="seg-reciter-select"
                value={$selectedReciter}
                on:change={onReciterSelectChange}
            >
                <option value="">{$segAllReciters.length ? '-- select --' : 'Loading...'}</option>
                {#each groupedReciters as g}
                    <optgroup label={g.group}>
                        {#each g.items as r}
                            <option value={r.slug}>{r.name}</option>
                        {/each}
                    </optgroup>
                {/each}
            </select>
        </label>
        <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
        <label>Chapter:
            <SearchableSelect
                options={chaptersOptions}
                value={$selectedChapter}
                placeholder="--"
                on:change={onChapterSelectChange}
            />
        </label>
        <label>Verse:
            <select
                id="seg-verse-select"
                value={$selectedVerse}
                on:change={onVerseSelectChange}
            >
                <option value="">All</option>
                {#each $verseOptions as v}
                    <option value={String(v)}>{v}</option>
                {/each}
            </select>
        </label>
        <div class="seg-bar-actions">
            <button id="seg-save-btn" class="btn btn-save" disabled>Save</button>
            <button id="seg-history-btn" class="btn btn-history" hidden>History</button>
        </div>
    </div>

    <div class="seg-cache-panel" id="seg-cache-bar" hidden>
        <div class="seg-cache-actions">
            <button id="seg-prepare-btn" class="btn seg-cache-download-btn" hidden>Download All Audio</button>
            <button id="seg-delete-cache-btn" class="btn seg-cache-delete-btn" hidden>Delete Cache</button>
        </div>
        <div id="seg-cache-progress" class="seg-cache-progress" hidden>
            <div class="seg-cache-progress-bar">
                <div id="seg-cache-progress-fill" class="seg-cache-progress-fill"></div>
            </div>
            <span id="seg-cache-progress-text" class="seg-cache-progress-text"></span>
        </div>
        <span id="seg-cache-status" class="seg-cache-status"></span>
    </div>

    <details class="shortcuts-guide">
        <summary class="shortcuts-guide-summary">Shortcuts &amp; Guide</summary>
        <div class="shortcuts-guide-body">
            <div class="sg-col">
                <h4>Playback</h4>
                <dl>
                    <dt>Space</dt><dd>Play / pause</dd>
                    <dt>&larr; / &rarr;</dt><dd>Seek &plusmn;3 s</dd>
                    <dt>&uarr; / &darr;</dt><dd>Prev / next segment</dd>
                    <dt>, / .</dt><dd>Slower / faster playback</dd>
                    <dt>J</dt><dd>Scroll current segment into view</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Editing</h4>
                <dl>
                    <dt>E</dt><dd>Edit reference of current segment</dd>
                    <dt>Enter</dt><dd>Confirm trim / split</dd>
                    <dt>Escape</dt><dd>Cancel trim / split</dd>
                    <dt>S</dt><dd>Save changes</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Segment Actions</h4>
                <dl>
                    <dt>Click row</dt><dd>Play that segment</dd>
                    <dt>Adjust</dt><dd>Drag start/end handles on waveform</dd>
                    <dt>Split</dt><dd>Drag yellow handle to set split point</dd>
                    <dt>Merge &uarr;/&darr;</dt><dd>Combine with adjacent segment</dd>
                    <dt>Delete</dt><dd>Remove segment (with confirmation)</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Other</h4>
                <dl>
                    <dt>Filters</dt><dd>Add conditions to narrow displayed segments</dd>
                    <dt>Validation panel</dt><dd>Browse errors by category, click to jump</dd>
                    <dt>Stats panel</dt><dd>Histograms to judge segmentation quality</dd>
                    <dt>Continuous play</dt><dd>Auto-advances through segments including cross-file</dd>
                </dl>
            </div>
        </div>
    </details>

    <!-- Wave 8b: StatsPanel.svelte replaces imperative renderStatsPanel;
         $segStats store controls visibility. IDs removed — no imperative
         consumers remain for seg-stats-panel / seg-stats-charts. -->
    <StatsPanel />

    <!-- Wave 10: HistoryPanel.svelte owns #seg-history-view reactively via
         the history store. IDs preserved inside the component so legacy
         `dom.segHistoryView` mustGet + delegated click handlers keep working. -->
    <HistoryPanel />

    <!-- Wave 9: SavePreview.svelte — visibility driven by $savePreviewVisible store.
         IDs preserved inside component so mustGet() refs still resolve. -->
    <SavePreview />

    <!-- Wave 8a.2: ValidationPanel.svelte replaces imperative renderValidationPanel.
         IDs seg-validation-global / seg-validation preserved so legacy dom.segValidation*El
         refs (segments/index.ts mustGet, event delegation) still resolve. Svelte content
         replaces the innerHTML; hidden attr removed (ValidationPanel controls visibility).
         Global panel shows all chapters when a chapter is selected.
         When no chapter is selected, only the global (all-chapters) panel shows. -->
    <div id="seg-validation-global" class="seg-validation">
        {#if $selectedChapter}
            <ValidationPanel chapter={null} label="All Chapters" />
        {/if}
    </div>
    <div id="seg-validation" class="seg-validation">
        {#if $selectedChapter}
            <ValidationPanel chapter={parseInt($selectedChapter)} label="Chapter {$selectedChapter}" />
        {:else}
            <ValidationPanel chapter={null} />
        {/if}
    </div>

    <FiltersBar hidden={filterBarHidden} />

    <SegmentsAudioControls bind:audioEl={segAudioEl} />

    <SegmentsList onRestore={onNavigationRestore} />

    <EditOverlay audioElRef={segAudioEl} />
</div>
