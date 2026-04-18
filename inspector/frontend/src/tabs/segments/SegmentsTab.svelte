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

    import { isDirtyStore } from '../../lib/stores/segments/dirty';
    import { handleSegmentsKey } from '../../lib/utils/segments/keyboard';
    import { showHistoryView } from '../../lib/utils/segments/history-actions';
    import { onSegSaveClick } from '../../lib/utils/segments/save-actions';
    import { loadSegConfig } from '../../lib/utils/segments/config-loader';
    import { buildGroupedReciters } from '../../lib/utils/grouped-reciters';
    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import { fetchJson } from '../../lib/api';
    import {
        getChapterSegments,
        segAllData,
        segAllReciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        verseOptions,
    } from '../../lib/stores/segments/chapter';
    import { activeFilters } from '../../lib/stores/segments/filters';
    import { savedFilterView } from '../../lib/stores/segments/navigation';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady, surahOptionText } from '../../lib/utils/surah-info';
    import type { SegReciter } from '../../lib/types/domain';

    import { reloadCurrentReciter } from '../../lib/utils/segments/reciter-actions';
    import { loadChapterData } from '../../lib/utils/segments/chapter-actions';
    import HistoryPanel from './history/HistoryPanel.svelte';
    import { segListElement, waveformContainer } from '../../lib/stores/segments/playback';
    import { historyData, historyVisible } from '../../lib/stores/segments/history';
    import { savePreviewVisible, saveButtonLabel } from '../../lib/stores/segments/save';
    import ValidationPanel from './validation/ValidationPanel.svelte';
    import EditOverlay from './edit/EditOverlay.svelte';
    import FiltersBar from './FiltersBar.svelte';
    import SegmentsList from './SegmentsList.svelte';
    import SegmentsAudioControls from './SegmentsAudioControls.svelte';
    import StatsPanel from './StatsPanel.svelte';
    import SavePreview from './save/SavePreview.svelte';
    import AudioCacheBar from './AudioCacheBar.svelte';
    import ShortcutsGuide from './ShortcutsGuide.svelte';

    // Audio element ref exposed from SegmentsAudioControls via bind:audioEl.
    let segAudioEl: HTMLAudioElement | null = null;

    $: groupedReciters = buildGroupedReciters($segAllReciters);
    $: chaptersOptions = $segAllData
        ? [...new Set($segAllData.segments.filter(s => s.chapter != null).map(s => s.chapter as number))]
            .sort((a, b) => a - b)
            .map(ch => ({ value: String(ch), label: surahOptionText(ch) }))
        : [];
    $: filterBarHidden = $segAllData === null;
    $: historyBtnHidden = !$historyData || !$historyData.batches || $historyData.batches.length === 0;
    $: saveBtnDisabled = !$isDirtyStore;

    let cssFontSize: string = '';
    let cssWordSpacing: string = '';

    async function loadReciters(): Promise<void> {
        try {
            const rs = await fetchJson<SegReciter[]>('/api/seg/reciters');
            segAllReciters.set(rs);
            const saved = localStorage.getItem(LS_KEYS.SEG_RECITER);
            if (saved) { selectedReciter.set(saved); await onReciterChange(saved); }
        } catch (e) { console.error('Error loading seg reciters:', e); }
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
        const v = e.detail; selectedChapter.set(v); onChapterChange(v);
    }
    async function onChapterChange(chapter: string): Promise<void> {
        await loadChapterData(get(selectedReciter), chapter);
    }
    function onVerseSelectChange(e: Event): void {
        selectedVerse.set((e.currentTarget as HTMLSelectElement).value);
    }

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

    // Keep chapter-segment cache hot after chapter changes.
    $: if ($segAllData) { void getChapterSegments($selectedChapter || 0); }

    function onKeydown(e: KeyboardEvent): void {
        if (handleSegmentsKey(e)) e.preventDefault();
    }

    onMount(async () => {
        await surahInfoReady;
        const cfg = await loadSegConfig();
        cssFontSize = cfg.fontSize;
        cssWordSpacing = cfg.wordSpacing;
        await loadReciters();
    });
</script>

<svelte:window on:keydown={onKeydown} />

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

    {#if !$historyVisible && !$savePreviewVisible}
        <AudioCacheBar />

        <ShortcutsGuide />

        <StatsPanel />

        <div id="seg-validation-global" class="seg-validation" use:waveformContainer>
            {#if $selectedChapter}
                <ValidationPanel chapter={null} label="All Chapters" />
            {/if}
        </div>
        <div id="seg-validation" class="seg-validation" use:waveformContainer>
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
    {/if}

    <HistoryPanel />

    <SavePreview />
</div>
