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
    import { loadQuranRefs } from '../../lib/refs/quran-refs';
    import { currentUser, loadCurrentUser } from '../../lib/stores/current-user';
    import { setEditingMode, syncEditingMode } from '../../lib/stores/editing-mode';
    import type { SegReciter } from '../../lib/types/domain';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady } from '../../lib/utils/surah-info';
    import { catalogData, loadCatalog } from '../dashboard/stores/catalog-data';
    import EditOverlay from './components/edit/EditOverlay.svelte';
    import FiltersBar from './components/filters/FiltersBar.svelte';
    import SegmentsFooter from './components/footer/SegmentsFooter.svelte';
    import HistoryPanel from './components/history/HistoryPanel.svelte';
    import SegmentsList from './components/list/SegmentsList.svelte';
    import SavePreview from './components/save/SavePreview.svelte';
    import ValidationPanel from './components/validation/ValidationPanel.svelte';
    import ShortcutsGuide from './ShortcutsGuide.svelte';
    import { autoSaveEnabled } from './stores/autosave';
    import {
        getChapterSegments,
        segAllData,
        segAllReciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
    } from './stores/chapter';
    import { dirtyTick,isDirtyStore } from './stores/dirty';
    import { activeFilters } from './stores/filters';
    import { historyVisible } from './stores/history';
    import { savedFilterView } from './stores/navigation';
    import { segAudioElement, segListElement, waveformContainer } from './stores/playback';
    import { savePreviewVisible } from './stores/save';
    import { loadChapterData } from './utils/data/chapter-actions';
    import { loadSegConfig } from './utils/data/config-loader';
    import { reloadCurrentReciter } from './utils/data/reciter-actions';
    import { handleSegmentsKey } from './utils/keyboard';
    import { playFromSegment } from './utils/playback/playback';
    import { executeSave } from './utils/save/actions';

    // Audio element ref published by SegmentsFooter's onMount into the
    // `segAudioElement` store. EditOverlay still wants the raw element as
    // a marker prop, so we subscribe instead of binding directly.
    $: segAudioEl = $segAudioElement;

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
        // Re-resolve the chip's bucket so its StatePill reflects the new
        // state immediately (claim flips awaiting_review → under_review,
        // unclaim flips it back). Without this, the pill stays stale until
        // a manual reload.
        void resolveContextFromSlug(slug);
    }

    // Re-sync editing mode whenever the currentUser store updates (e.g.
    // after sign-in or after access revoke).
    $: setEditingMode(syncEditingMode($currentUser, reciterTask));

    $: filterBarHidden = $segAllData === null;

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
            await loadCatalog(); // idempotent — first caller in any tab pays the cost
            const snap = get(catalogData);
            for (const r of snap.reciters) {
                const d = r.deliveries.find((x) => x.slug === slug);
                if (d) {
                    contextName = r.name;
                    contextNameAr = r.name_ar ?? null;
                    contextCountry = r.country ?? null;
                    contextBucket = d.bucket;
                    contextRiwayah = d.riwayah;
                    contextStyle = d.style;
                    return;
                }
            }
        } catch {
            // Silent fail; chip falls back to slug-less placeholder.
        }
    }

    let contextName: string | null = null;
    let contextNameAr: string | null = null;
    let contextCountry: string | null = null;
    let contextBucket: import('../../lib/types/public-state').PublicBucket | null = null;
    let contextRiwayah: string | null = null;
    let contextStyle: string | null = null;

    function onPickerChange(
        ev: CustomEvent<{
            slug: string;
            name: string;
            bucket: import('../../lib/types/public-state').PublicBucket;
            riwayah: string;
            style: string;
        }>,
    ): void {
        const { slug, name, bucket, riwayah, style } = ev.detail;
        contextName = name;
        contextBucket = bucket;
        contextRiwayah = riwayah;
        contextStyle = style;
        selectedReciter.set(slug);
        _bindTask(slug || null);
        onReciterChange(slug);
    }
    async function onReciterChange(reciter: string): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.SEG_RECITER, reciter);
        await reloadCurrentReciter();
    }
    function onChapterChange(ev: CustomEvent<string>): void {
        const v = ev.detail;
        selectedChapter.set(v);
        void loadChapterData(get(selectedReciter), v);
    }
    async function _loadChapter(chapter: string): Promise<void> {
        await loadChapterData(get(selectedReciter), chapter);
    }
    function onVerseJump(ev: CustomEvent<string>): void {
        const v = ev.detail;
        if (!v) return;
        const chStr = get(selectedChapter);
        const chapter = parseInt(chStr);
        if (!chapter) return;
        const segs = getChapterSegments(chapter);
        const prefix = `${chapter}:${v}:`;
        const first = segs.find((s) => s.matched_ref?.startsWith(prefix));
        if (first) {
            // Reflect the jump target in the footer's Ayah trigger so the
            // user can see what they jumped to (vs. the original UI which
            // snapped back to "All" immediately and forgot the selection).
            selectedVerse.set(v);
            playFromSegment(first.index, first.chapter ?? chapter);
        }
    }

    async function onNavigationRestore(): Promise<void> {
        const saved = get(savedFilterView);
        if (!saved) return;
        savedFilterView.set(null);
        activeFilters.set(saved.filters);

        if (saved.chapter !== get(selectedChapter)) {
            selectedChapter.set(saved.chapter);
            await _loadChapter(saved.chapter);
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
        // Fire-and-forget the 2.4 MB quran-refs bundle that only Segments
        // consumers (SegmentRow, ReferenceEditor, split/merge/auto-fix) need.
        // Idempotent — reciter-actions awaits this same promise before
        // hydrating per-segment matched_text.
        void loadQuranRefs();
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

    <!-- StatsPanel transitively imports chart.js (~85 KB br). Lazy-load so
         the charts chunk only ships when a maintainer/owner actually views
         the Segments tab — Dashboard / non-admin visitors never pay this cost. -->
    {#if $currentUser.role === 'maintainer' || $currentUser.role === 'owner'}
        {#await import('./components/stats/StatsPanel.svelte') then mod}
            <svelte:component this={mod.default} />
        {/await}
    {/if}

    {#if !$historyVisible && !$savePreviewVisible}
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

        <SegmentsList onRestore={onNavigationRestore} />

        <EditOverlay audioElRef={segAudioEl} />
    {/if}

    <HistoryPanel />

    <SavePreview />

    <SegmentsFooter
        {reciterTask}
        {chipActionBusy}
        {contextName}
        {contextBucket}
        {contextRiwayah}
        {contextStyle}
        on:reciterChange={onPickerChange}
        on:chapterChange={onChapterChange}
        on:verseJump={onVerseJump}
        on:unclaim={_unclaim}
        on:markReady={_markReady}
        on:claimed={_refreshTask}
    />
</div>

<style>
    /* Reserve space below the pinned SegmentsFooter so the list, validation
       panels, and edit overlay never disappear behind it on scroll. The
       footer min-height is `--seg-footer-h` (60px); add a token cushion. */
    #segments-panel-inner {
        padding-bottom: calc(var(--seg-footer-actual-h, var(--seg-footer-h, 60px)) + var(--s-3));
    }
</style>
