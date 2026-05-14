<script lang="ts">
    /**
     * SegmentsTab — top-level Svelte component for the Segments tab.
     *
     * Owns reciter/chapter/verse dropdowns, filter bar, navigation banner,
     * segment list rendering, CSS-var config, and tab-level keyboard shortcuts.
     * Mounts validation, history, and save-preview panels as Svelte children.
     */

    import { onMount, tick } from 'svelte';
    import { get, type Readable } from 'svelte/store';

    import { fetchJson } from '../../lib/api';
    import { markReady, release } from '../../lib/api/claims-client';
    import { getReciterTaskStore, type ReciterTask,refreshReciterTask } from '../../lib/api/reciter-task';
    import ClaimButton from '../../lib/components/ClaimButton.svelte';
    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import { currentUser, loadCurrentUser } from '../../lib/stores/current-user';
    import {
        editingMode,
        setEditingMode,
        syncEditingMode,
    } from '../../lib/stores/editing-mode';
    import type { SegReciter } from '../../lib/types/domain';
    import { LS_KEYS, PLACEHOLDER_SELECT } from '../../lib/utils/constants';
    import { buildGroupedReciters, reciterGroupsToOptions } from '../../lib/utils/grouped-reciters';
    import { surahInfoReady, surahOptionText } from '../../lib/utils/surah-info';
    import SegmentsAudioControls from './components/audio/SegmentsAudioControls.svelte';
    import EditOverlay from './components/edit/EditOverlay.svelte';
    import FiltersBar from './components/filters/FiltersBar.svelte';
    import ReciterContextChip from './components/header/ReciterContextChip.svelte';
    import HistoryPanel from './components/history/HistoryPanel.svelte';
    import SegmentsList from './components/list/SegmentsList.svelte';
    import SavePreview from './components/save/SavePreview.svelte';
    import StatsPanel from './components/stats/StatsPanel.svelte';
    import ValidationPanel from './components/validation/ValidationPanel.svelte';
    import ShortcutsGuide from './ShortcutsGuide.svelte';
    import { autoSaveEnabled, toggleAutoSave } from './stores/autosave';
    import {
        getChapterSegments,
        segAllData,
        segAllReciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        verseOptions,
    } from './stores/chapter';
    import { dirtyTick,isDirtyStore } from './stores/dirty';
    import { activeFilters } from './stores/filters';
    import { historyLoadState, historyVisible } from './stores/history';
    import { savedFilterView } from './stores/navigation';
    import { segListElement, waveformContainer } from './stores/playback';
    import { saveButtonLabel,savePreviewVisible } from './stores/save';
    import { loadChapterData } from './utils/data/chapter-actions';
    import { loadSegConfig } from './utils/data/config-loader';
    import { reloadCurrentReciter } from './utils/data/reciter-actions';
    import { hideHistoryView,showHistoryView } from './utils/history/actions';
    import { handleSegmentsKey } from './utils/keyboard';
    import { playFromSegment } from './utils/playback/playback';
    import { confirmSaveFromPreview, executeSave,hideSavePreview, onSegSaveClick } from './utils/save/actions';

    // Audio element ref exposed from SegmentsAudioControls via bind:audioEl.
    let segAudioEl: HTMLAudioElement | null = null;

    // Reciter-task subscription: bound to the selected reciter. The store
    // self-polls every 30 s while subscribed; we replace the binding when
    // the user switches reciter so only one task is polled at a time.
    let reciterTaskStore: Readable<ReciterTask | null> | null = null;
    let reciterTask: ReciterTask | null = null;
    let _taskUnsubscribe: (() => void) | null = null;

    function _bindTask(slug: string | null) {
        if (_taskUnsubscribe) {
            _taskUnsubscribe();
            _taskUnsubscribe = null;
        }
        reciterTaskStore = slug ? getReciterTaskStore(slug) : null;
        reciterTask = null;
        if (reciterTaskStore) {
            _taskUnsubscribe = reciterTaskStore.subscribe((v) => {
                reciterTask = v;
                setEditingMode(syncEditingMode($currentUser, v));
            });
        } else {
            setEditingMode(syncEditingMode($currentUser, null));
        }
    }

    // Refresh task immediately after a state-mutating action; the polling
    // tick still fires every 30 s but acting users shouldn't wait for it.
    async function _refreshTask() {
        const slug = get(selectedReciter);
        if (!slug) return;
        const fresh = await refreshReciterTask(slug);
        reciterTask = fresh;
        setEditingMode(syncEditingMode($currentUser, fresh));
        // /api/me's active_claim derives from state — pull a fresh copy too.
        void loadCurrentUser();
    }

    // Re-sync editing mode whenever the currentUser store updates (e.g.
    // after sign-in or after access revoke).
    $: setEditingMode(syncEditingMode($currentUser, reciterTask));

    $: groupedReciters = buildGroupedReciters($segAllReciters);
    $: reciterSelectOptions = reciterGroupsToOptions(groupedReciters);
    $: verseSelectOptions = $verseOptions.map((v) => ({ value: String(v), label: String(v) }));
    // Jump-trigger state: resets immediately after use so SearchableSelect shows placeholder
    let verseJump = '';
    $: chaptersOptions = $segAllData
        ? [...new Set($segAllData.segments.filter(s => s.chapter != null).map(s => s.chapter as number))]
            .sort((a, b) => a - b)
            .map(ch => ({ value: String(ch), label: surahOptionText(ch) }))
        : [];
    $: filterBarHidden = $segAllData === null;
    $: historyBtnHidden = !$selectedReciter;
    $: historyBtnLabel = $historyVisible
        ? '← Back'
        : $historyLoadState === 'loading'
            ? 'History...'
            : 'History';
    $: saveBtnDisabled = !$isDirtyStore;

    // Inline header actions — Unclaim and Mark-ready operate on the
    // active claim's slug. We don't need busy spinners here; the network
    // round-trip refreshes the task and the UI flips accordingly.
    let chipActionBusy: '' | 'unclaim' | 'mark' = '';
    async function _unclaim(): Promise<void> {
        const slug = $selectedReciter;
        if (!slug || chipActionBusy) return;
        chipActionBusy = 'unclaim';
        try {
            await release(slug);
            await _refreshTask();
        } catch { /* toast already surfaced */ }
        finally { chipActionBusy = ''; }
    }
    async function _markReady(): Promise<void> {
        const slug = $selectedReciter;
        if (!slug || chipActionBusy) return;
        chipActionBusy = 'mark';
        try {
            await markReady(slug);
            await _refreshTask();
        } catch { /* toast already surfaced */ }
        finally { chipActionBusy = ''; }
    }

    let cssFontSize: string = '';
    let cssWordSpacing: string = '';

    async function loadReciters(): Promise<void> {
        try {
            const rs = await fetchJson<SegReciter[]>('/api/seg/reciters');
            segAllReciters.set(rs);
            const saved = localStorage.getItem(LS_KEYS.SEG_RECITER);
            const validSaved = saved && rs.some((r) => r.slug === saved) ? saved : null;
            if (!validSaved && saved) {
                // Drop the stale slug so we don't keep hammering 404 endpoints
                // every reload. The user picks a fresh reciter from the list.
                localStorage.removeItem(LS_KEYS.SEG_RECITER);
            }
            if (validSaved) {
                selectedReciter.set(validSaved);
                _bindTask(validSaved);
                await onReciterChange(validSaved);
                void resolveContextFromSlug(validSaved);
            }
        } catch (e) { console.error('Error loading seg reciters:', e); }
    }

    async function resolveContextFromSlug(slug: string): Promise<void> {
        try {
            const { fetchPublicReciters } = await import('../../lib/api/public-reciters');
            const page = await fetchPublicReciters({ limit: 500 });
            for (const r of page.reciters) {
                const d = r.deliveries.find((x) => x.slug === slug);
                if (d) {
                    contextName = r.name;
                    contextBucket = r.primary_bucket;
                    return;
                }
            }
        } catch {
            // Silent fail; chip falls back to slug-less placeholder.
        }
    }

    let contextName: string | null = null;
    let contextBucket: import('../../lib/types/public-state').PublicBucket | null = null;

    function onReciterSelectChange(v: string): void {
        selectedReciter.set(v);
        _bindTask(v || null);
        onReciterChange(v);
    }

    function onPickerChange(
        ev: CustomEvent<{ slug: string; name: string; bucket: import('../../lib/types/public-state').PublicBucket }>,
    ): void {
        const { slug, name, bucket } = ev.detail;
        contextName = name;
        contextBucket = bucket;
        onReciterSelectChange(slug);
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
    function onVerseSelectChange(v: string): void {
        // Reset immediately so the SearchableSelect snaps back to placeholder
        // ("All") — this is a jump-and-play trigger, not a filter toggle.
        verseJump = '';
        if (!v) return;
        const chStr = get(selectedChapter);
        const chapter = parseInt(chStr);
        if (!chapter) return;
        const segs = getChapterSegments(chapter);
        const prefix = `${chapter}:${v}:`;
        const first = segs.find((s) => s.matched_ref?.startsWith(prefix));
        if (first) playFromSegment(first.index, first.chapter ?? chapter);
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

    let autoSaveTimer: ReturnType<typeof setTimeout> | null = null;
    $: if ($autoSaveEnabled && $dirtyTick > 0 && $isDirtyStore) {
        if (autoSaveTimer) clearTimeout(autoSaveTimer);
        autoSaveTimer = setTimeout(() => {
            if ($isDirtyStore) {
                void executeSave(true);
            }
        }, 1000); // 1s debounce
    }

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
    <ShortcutsGuide />

    <div class="seg-context-block">
        <ReciterContextChip
            currentSlug={$selectedReciter || null}
            currentName={contextName}
            currentBucket={contextBucket}
            on:change={onPickerChange}
        >
            {#if $selectedReciter}
                {#if reciterTask?.predicates.can_release}
                    <button
                        type="button"
                        class="seg-btn lg"
                        disabled={chipActionBusy !== ''}
                        on:click={_unclaim}
                    >Unclaim</button>
                {/if}
                {#if reciterTask?.predicates.can_mark_ready}
                    <button
                        type="button"
                        class="seg-btn lg primary"
                        disabled={chipActionBusy !== ''}
                        title="Mark this reciter ready for a maintainer to publish"
                        on:click={_markReady}
                    >Mark ready</button>
                {/if}
                <ClaimButton
                    slug={$selectedReciter}
                    task={reciterTask}
                    onClaimed={_refreshTask}
                />
            {/if}
        </ReciterContextChip>
    </div>

    <div class="info-bar seg-selector-bar">
        <!-- svelte-ignore a11y-label-has-associated-control -->
        <label>Surah:
            <SearchableSelect
                options={chaptersOptions}
                value={$selectedChapter}
                placeholder="--"
                on:change={onChapterSelectChange}
            />
        </label>
        <!-- svelte-ignore a11y-label-has-associated-control -->
        <label>Ayah:
            <SearchableSelect
                options={verseSelectOptions}
                value={verseJump}
                placeholder="All"
                on:change={(e) => onVerseSelectChange(e.detail)}
            />
        </label>
        <div class="seg-bar-actions">
            {#if $savePreviewVisible}
                <button id="seg-save-preview-cancel" class="seg-btn" on:click={() => hideSavePreview()}>Cancel</button>
                <button id="seg-save-preview-confirm" class="seg-btn primary" on:click={confirmSaveFromPreview}>Confirm Save</button>
            {:else if $editingMode.kind !== 'view'}
                <!--
                    Save + Auto-Save only visible when the user has write
                    rights on this reciter (active reviewer OR maintainer/
                    owner admin-bypass). The backend lock decorator is
                    authoritative; this is the UX layer hiding noise from
                    users who can't act on it.
                -->
                <div class="seg-toggle" role="group" aria-label="Auto-save">
                    <button
                        type="button"
                        class="opt"
                        class:on={!$autoSaveEnabled}
                        on:click={() => toggleAutoSave(false)}
                    >Auto-save off</button>
                    <button
                        type="button"
                        class="opt"
                        class:on={$autoSaveEnabled}
                        on:click={() => toggleAutoSave(true)}
                    >On</button>
                </div>
                <button
                    id="seg-save-btn"
                    class="seg-btn {$isDirtyStore ? 'primary' : 'success'}"
                    disabled={$autoSaveEnabled || saveBtnDisabled}
                    on:click={onSegSaveClick}
                >
                    {#if $isDirtyStore}
                        {$autoSaveEnabled && $saveButtonLabel === 'Save' ? 'Saving…' : $saveButtonLabel}
                    {:else}
                        ✓ Saved
                    {/if}
                </button>
            {/if}
            <button
                id="seg-history-btn"
                class="seg-btn"
                hidden={historyBtnHidden && !$historyVisible}
                on:click={$historyVisible ? hideHistoryView : showHistoryView}
            >{historyBtnLabel}</button>
        </div>
    </div>

    {#if !$historyVisible && !$savePreviewVisible}
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
