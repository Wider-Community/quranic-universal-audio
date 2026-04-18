<script lang="ts">
    /**
     * SegmentsTab — top-level Svelte component for the Segments tab.
     *
     * Owns reciter/chapter/verse dropdowns, filter bar, navigation banner,
     * segment list rendering, CSS-var config, and tab-level keyboard shortcuts.
     * Mounts validation, history, and save-preview panels as Svelte children.
     */

    import { get } from 'svelte/store';
    import { onMount, tick } from 'svelte';

    import { isDirty, isDirtyStore } from '../../lib/stores/segments/dirty';
    import { shouldHandleKey } from '../../lib/utils/keyboard-guard';
    import { cycleSpeedStore } from '../../lib/utils/speed-control';
    import { attachImperativeCardListeners } from '../../lib/utils/segments/imperative-card-click';
    import { _deleteAudioCache, _prepareAudio } from '../../lib/utils/segments/audio-cache-ui';
    import {
        exitEditMode,
    } from '../../lib/utils/segments/edit-common';
    import { confirmSplit } from '../../lib/utils/segments/edit-split';
    import { confirmTrim } from '../../lib/utils/segments/edit-trim';
    import { startRefEdit } from '../../lib/utils/segments/edit-reference';
    import { showHistoryView } from '../../lib/utils/segments/history-actions';
    import { onSegPlayClick, playFromSegment } from '../../lib/utils/segments/playback';
    import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from '../../lib/utils/segments/save-actions';
    import { _restoreFilterView } from '../../lib/utils/segments/navigation-actions';
    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import { fetchJson, fetchJsonOrNull } from '../../lib/api';
    import {
        getChapterSegments,
        segAllData,
        segAllReciters,
        segCurrentIdx,
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
    import { segValidation } from '../../lib/stores/segments/validation';
    import { savedFilterView } from '../../lib/stores/segments/navigation';
    import { segConfig as segConfigStore } from '../../lib/stores/segments/config';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady, surahOptionText } from '../../lib/utils/surah-info';
    import type { SegReciter } from '../../types/domain';

    import { reloadCurrentReciter } from '../../lib/utils/segments/reciter-actions';
    import { loadChapterData } from '../../lib/utils/segments/chapter-actions';
    import HistoryPanel from './history/HistoryPanel.svelte';
    import { editMode } from '../../lib/stores/segments/edit';
    import {
        activeAudioSource,
        playbackSpeed,
        segAudioElement,
        segListElement,
    } from '../../lib/stores/segments/playback';
    import { historyData } from '../../lib/stores/segments/history';
    import { savePreviewVisible, saveButtonLabel } from '../../lib/stores/segments/save';
    import { getValCardAudioOrNull } from '../../lib/utils/segments/error-card-audio';
    import ValidationPanel from './validation/ValidationPanel.svelte';
    import EditOverlay from './edit/EditOverlay.svelte';
    import FiltersBar from './FiltersBar.svelte';
    import SegmentsList from './SegmentsList.svelte';
    import SegmentsAudioControls from './SegmentsAudioControls.svelte';
    import StatsPanel from './StatsPanel.svelte';
    import SavePreview from './save/SavePreview.svelte';

    // Audio element ref exposed from SegmentsAudioControls via bind:audioEl.
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

    // Reactive dependency tracking for derived UI updates.
    $: void $segAllReciters;
    $: void $activeFilters;
    $: void $displayedSegments;
    $: void $segIndexMap;
    $: void $savedFilterView;
    $: void $segValidation;

    // History button visibility — driven by the raw history payload.
    $: historyBtnHidden = !$historyData || !$historyData.batches || $historyData.batches.length === 0;

    // Save button enabled when there are unsaved edits.
    $: saveBtnDisabled = !$isDirtyStore;

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
            segConfigStore.set({
                validationCategories: cfg.validation_categories ?? null,
                muqattaatVerses: cfg.muqattaat_verses ? new Set(cfg.muqattaat_verses.map(([s, a]) => `${s}:${a}`)) : null,
                qalqalaLetters: cfg.qalqala_letters ? new Set(cfg.qalqala_letters) : null,
                standaloneRefs: cfg.standalone_refs ? new Set(cfg.standalone_refs.map(([s, a, w]) => `${s}:${a}:${w}`)) : null,
                standaloneWords: cfg.standalone_words ? new Set(cfg.standalone_words) : null,
                lcDefaultThreshold: cfg.low_conf_default_threshold ?? 80,
                showBoundaryPhonemes: cfg.show_boundary_phonemes ?? true,
                accordionContext: cfg.accordion_context ?? null,
                trimPadLeft: cfg.trim_pad_left ?? 500,
                trimPadRight: cfg.trim_pad_right ?? 500,
                trimDimAlpha: cfg.trim_dim_alpha ?? 0.45,
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
        await reloadCurrentReciter();
    }

    function onChapterSelectChange(e: CustomEvent<string>): void {
        const v = e.detail;
        selectedChapter.set(v);
        onChapterChange(v);
    }

    async function onChapterChange(chapter: string): Promise<void> {
        const reciter = get(selectedReciter);
        await loadChapterData(reciter, chapter);
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

        await tick();
        const listEl = get(segListElement);
        if (listEl) listEl.scrollTop = saved.scrollTop;
    }

    // Chapter-index helper for imperative code — keep the cached map hot
    // after chapter changes so getChapterSegments() called later returns
    // the same refs renderSegList saw.
    $: if ($segAllData) {
        void getChapterSegments($selectedChapter || 0);
    }

    // Keep the audio element's playback rate in sync with the store.
    $: if (segAudioEl) segAudioEl.playbackRate = $playbackSpeed;

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
                const valAudio = getValCardAudioOrNull();
                const mainAudio = get(segAudioElement);
                const el = (get(activeAudioSource) === 'error' && valAudio) ? valAudio : mainAudio;
                if (!el) break;
                el.currentTime = Math.max(0, el.currentTime - 3);
                break;
            }
            case 'ArrowRight': {
                e.preventDefault();
                const valAudio = getValCardAudioOrNull();
                const mainAudio = get(segAudioElement);
                const el = (get(activeAudioSource) === 'error' && valAudio) ? valAudio : mainAudio;
                if (!el) break;
                el.currentTime = Math.min(el.duration || 0, el.currentTime + 3);
                break;
            }
            case 'ArrowUp': {
                e.preventDefault();
                const displayed = get(displayedSegments);
                if (!displayed || displayed.length === 0) break;
                const curIdx = get(segCurrentIdx);
                const curPos = displayed.findIndex(s => s.index === curIdx);
                const prevPos = curPos > 0 ? curPos - 1 : 0;
                const prev = displayed[prevPos];
                if (prev) playFromSegment(prev.index, prev.chapter);
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                const displayed = get(displayedSegments);
                if (!displayed || displayed.length === 0) break;
                const curIdx = get(segCurrentIdx);
                const curPos = displayed.findIndex(s => s.index === curIdx);
                const nextPos = curPos >= 0 && curPos < displayed.length - 1 ? curPos + 1 : (curPos === -1 ? 0 : curPos);
                const nxt = displayed[nextPos];
                if (nxt) playFromSegment(nxt.index, nxt.chapter);
                break;
            }
            case 'Period':
            case 'Comma': {
                e.preventDefault();
                const rate = cycleSpeedStore(playbackSpeed, e.code === 'Period' ? 'up' : 'down', LS_KEYS.SEG_SPEED);
                const valAudio = getValCardAudioOrNull();
                if (valAudio) valAudio.playbackRate = rate;
                break;
            }
            case 'KeyJ': {
                e.preventDefault();
                const listEl = get(segListElement);
                const row = listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${get(segCurrentIdx)}"]`);
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
                if (get(savePreviewVisible)) {
                    e.preventDefault();
                    hideSavePreview();
                } else if (get(editMode)) {
                    e.preventDefault();
                    exitEditMode();
                } else if (get(savedFilterView)) {
                    e.preventDefault();
                    _restoreFilterView();
                }
                break;

            case 'Enter':
                if (get(savePreviewVisible)) {
                    e.preventDefault();
                    confirmSaveFromPreview();
                } else {
                    const mode = get(editMode);
                    const curIdx = get(segCurrentIdx);
                    if (mode && curIdx >= 0) {
                        e.preventDefault();
                        const displayed = get(displayedSegments);
                        const seg = displayed
                            ? displayed.find(s => s.index === curIdx)
                            : null;
                        if (seg) {
                            if (mode === 'trim') confirmTrim(seg);
                            else if (mode === 'split') confirmSplit(seg);
                        }
                    }
                }
                break;

            case 'KeyE': {
                const curIdx = get(segCurrentIdx);
                if (get(editMode) || curIdx < 0) break;
                e.preventDefault();
                const listEl = get(segListElement);
                const row = listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${curIdx}"]`) ?? null;
                const displayed = get(displayedSegments);
                const seg = displayed
                    ? displayed.find(s => s.index === curIdx)
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
    // Mount
    // ---------------------------------------------------------------------

    onMount(async () => {
        // Delegated click + canvas-scrub listeners for imperative card containers.
        attachImperativeCardListeners();

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
            <button
                id="seg-save-btn"
                class="btn btn-save"
                disabled={saveBtnDisabled}
                on:click={onSegSaveClick}
            >{$saveButtonLabel}</button>
            <button
                id="seg-history-btn"
                class="btn btn-history"
                hidden={historyBtnHidden}
                on:click={showHistoryView}
            >History</button>
        </div>
    </div>

    <div class="seg-cache-panel" id="seg-cache-bar" hidden>
        <div class="seg-cache-actions">
            <button
                id="seg-prepare-btn"
                class="btn seg-cache-download-btn"
                hidden
                on:click={() => _prepareAudio($selectedReciter)}
            >Download All Audio</button>
            <button
                id="seg-delete-cache-btn"
                class="btn seg-cache-delete-btn"
                hidden
                on:click={() => _deleteAudioCache($selectedReciter)}
            >Delete Cache</button>
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

    <StatsPanel />

    <HistoryPanel />

    <SavePreview />

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
