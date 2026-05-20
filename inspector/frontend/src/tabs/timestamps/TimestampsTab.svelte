<script lang="ts">
    /**
     * TimestampsTab — composition shell for the Timestamps tab.
     *
     * Owns:
     *   - Reciter/chapter/verse cascade (manifest fetch + shard slice + store writes).
     *   - Config fetch → CSS custom-property bindings on the root div.
     *   - Lookahead pre-rolls (`nextRandomSame` / `nextRandomAny`) for instant random.
     *   - Autoplay-on-active-tab on first load.
     *   - Delegating to subcomponents: TimestampsControls, TimestampsAudio,
     *     TimestampsKeyboard, TimestampsShortcutsGuide.
     *   - Passing display-update callbacks to UnifiedDisplay / AnimationDisplay /
     *     TimestampsWaveform (imperative 60fps highlight path).
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';

    import {
        addBookmark,
        bookmarks,
        isBookmarked,
        removeBookmark,
    } from '../../lib/stores/bookmarks';
    import { pendingTsNavigation } from '../../lib/stores/navigation';
    import type { TsConfigResponse, TsDataResponse } from '../../lib/types/api';
    import type { TsReciter } from '../../lib/types/domain';
    import { getActiveTab } from '../../lib/utils/active-tab';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady } from '../../lib/utils/surah-info';
    import AnimationDisplay from './components/AnimationDisplay.svelte';
    import TimestampsAudio from './components/TimestampsAudio.svelte';
    import TimestampsControls from './components/TimestampsControls.svelte';
    import TimestampsKeyboard from './components/TimestampsKeyboard.svelte';
    import TimestampsShortcutsGuide from './components/TimestampsShortcutsGuide.svelte';
    import TimestampsViewControls from './components/TimestampsViewControls.svelte';
    import TimestampsWaveform from './components/TimestampsWaveform.svelte';
    import UnifiedDisplay from './components/UnifiedDisplay.svelte';
    import {
        assembleVerseFromShard,
        audioUrlFor,
        catalogReciterRows,
        chapterVerseRefs,
        getRandomTarget,
        loadCatalog,
        loadChapterShard,
        loadConfig,
        loadDk,
        loadManifest,
        loadQpc,
        loadVbrChapters,
    } from './services/ts_client';
    import {
        granularity,
        showLetters,
        showPhonemes,
        TS_GRANULARITIES,
        TS_VIEW_MODES,
        tsConfig,
        viewMode,
    } from './stores/display';
    import {
        autoAdvancing,
        loopTarget,
        tsPort,
        tsVbrChapters,
    } from './stores/playback';
    import {
        chapters,
        loadedVerse,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        type TsVerseOption,
        verses,
    } from './stores/verse';
    import { setupZoomLifecycle } from './utils/zoom';

    // ---- Local display constants ----
    const TS_EASING_NONE = 'none';
    const TS_EASING_DEFAULT = 'linear';
    const TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX = 800;

    // ---- Component refs ----
    let audioComp: TimestampsAudio;
    let controlsComp: TimestampsControls;
    let viewControlsComp: TimestampsViewControls;
    let unifiedEl: UnifiedDisplay;
    let animDisplayEl: AnimationDisplay;
    let waveformTabEl: TimestampsWaveform;

    // ---- Lookahead pre-rolls ----
    // Each pre-roll is the (reciter, chapter, verseRef) we'd jump to on the
    // matching random click. The shard is already in ts_client's LRU because
    // getRandomTarget loaded it during the pre-roll. Consuming a pre-roll is
    // therefore a dict-lookup-fast operation.
    let nextRandomSame: { reciter: string; chapter: number; verseRef: string } | null = null;
    let nextRandomAny: { reciter: string; chapter: number; verseRef: string } | null = null;

    // ---------------------------------------------------------------------
    // Initial load
    // ---------------------------------------------------------------------

    async function init(): Promise<void> {
        loadConfig().then((cfg) => tsConfig.set(cfg as TsConfigResponse));

        const savedView = localStorage.getItem(LS_KEYS.TS_VIEW_MODE);
        if (savedView === TS_VIEW_MODES.ANALYSIS || savedView === TS_VIEW_MODES.ANIMATION) {
            viewMode.set(savedView);
            if (savedView === TS_VIEW_MODES.ANALYSIS) {
                const sL = localStorage.getItem(LS_KEYS.TS_SHOW_LETTERS);
                const sP = localStorage.getItem(LS_KEYS.TS_SHOW_PHONEMES);
                if (sL !== null) showLetters.set(sL === 'true');
                if (sP !== null) showPhonemes.set(sP === 'true');
            } else {
                const sG = localStorage.getItem(LS_KEYS.TS_GRANULARITY);
                if (sG === TS_GRANULARITIES.WORDS || sG === TS_GRANULARITIES.CHARACTERS) {
                    granularity.set(sG);
                }
            }
        }

        await surahInfoReady;
        await loadReciters();

        // A bookmark click (pendingTsNavigation) owns the first verse load —
        // skip the random auto-pick so we don't load a verse then immediately
        // replace it. The reactive consumer below handles the actual load.
        if (navHandled || get(pendingTsNavigation)) return;

        // Autoplay on first load only when this tab is the active one — a
        // browser deep-link or refresh while the Segments tab is up should
        // still start paused. The eventual audio.play() is wrapped so a
        // policy denial leaves the UI primed-paused without console noise.
        const autoplay = getActiveTab() === 'timestamps';

        // First-load auto-pick: if we have a persisted reciter, let the
        // reciter-change path auto-load a random verse from it. Otherwise
        // load a random verse from any reciter.
        const savedReciter = localStorage.getItem(LS_KEYS.TS_RECITER);
        const rs = get(reciters);
        const validSaved = savedReciter && rs.some((r) => r.slug === savedReciter)
            ? savedReciter
            : null;
        if (!validSaved && savedReciter) {
            // Drop the stale slug so we don't keep hammering 404 endpoints
            // every reload. The user picks a fresh reciter from the list.
            localStorage.removeItem(LS_KEYS.TS_RECITER);
        }
        if (validSaved) {
            selectedReciter.set(validSaved);
            await onReciterChange(validSaved, autoplay);
        } else {
            await loadRandomTimestamp(null, autoplay);
        }
    }

    async function loadReciters(): Promise<void> {
        // D20 Track B: the catalog endpoint enriches names; the manifest is
        // the source of truth for which reciters actually have published
        // timestamps in the bucket. Intersect against manifest reciter keys
        // so the dropdown only lists reciters the user can actually play.
        try {
            const cfg = await loadConfig();
            if (cfg.catalog_url) {
                const [catalog, manifest] = await Promise.all([
                    loadCatalog(),
                    loadManifest(),
                ]);
                const ready = new Set(Object.keys(manifest.reciters));
                const rs: TsReciter[] = catalogReciterRows(catalog)
                    .filter((row) => ready.has(row.slug))
                    .map((row) => ({
                        slug: row.slug,
                        name: row.name_en,
                        audio_source: row.source,
                    }));
                rs.sort((a, b) => a.name.localeCompare(b.name));
                reciters.set(rs);
                return;
            }
        } catch (e) {
            console.warn('Catalog load failed; falling back to manifest:', e);
        }

        try {
            const m = await loadManifest();
            const rs: TsReciter[] = Object.entries(m.reciters).map(([slug, b]) => ({
                slug,
                name: b.name_en,
                audio_source: b.source ?? '',
            }));
            // Sort by display name for deterministic dropdown order.
            rs.sort((a, b) => a.name.localeCompare(b.name));
            reciters.set(rs);
        } catch (e) {
            console.error('Error loading manifest:', e);
        }
    }

    // ---------------------------------------------------------------------
    // Reciter / chapter / verse cascade
    // ---------------------------------------------------------------------

    async function onReciterChange(reciter: string, autoplayOverride?: boolean): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.TS_RECITER, reciter);
        chapters.set([]);
        selectedChapter.set('');
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        tsVbrChapters.set(new Set());
        if (!reciter) return;

        try {
            const m = await loadManifest();
            const block = m.reciters[reciter];
            if (block) {
                chapters.set(block.ts_chapters);
            }
        } catch (e) {
            console.error('Error reading manifest for reciter:', e);
        }

        // Auto-load a random verse from this reciter so the tab always has
        // something on screen after a reciter change.
        await loadRandomTimestamp(reciter, autoplayOverride ?? false);
    }

    async function onChapterChange(chapter: string): Promise<void> {
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        const reciter = get(selectedReciter);
        if (!reciter || !chapter) return;
        await populateVersesFor(reciter, parseInt(chapter, 10));
    }

    /** Populate the verses store from a chapter shard. Caches on ts_client's
     *  shard LRU so subsequent verse picks within the chapter are free. */
    async function populateVersesFor(reciter: string, chapter: number): Promise<void> {
        try {
            const shard = await loadChapterShard(reciter, chapter);
            const meta = shard._meta;
            const refs = chapterVerseRefs(shard);
            const opts: TsVerseOption[] = refs.map((ref) => {
                const [s, a] = ref.split('-', 1)[0]!.split(':');
                const surahN = parseInt(s ?? '0', 10);
                const ayahN = parseInt(a ?? '0', 10);
                return { ref, audio_url: audioUrlFor(meta, surahN, ayahN) };
            });
            verses.set(opts);
        } catch (e) {
            console.error('Error loading chapter shard:', e);
            verses.set([]);
        }
    }

    async function onVerseChange(verseRef: string): Promise<void> {
        const reciter = get(selectedReciter);
        const chapter = get(selectedChapter);
        if (!reciter || !chapter || verseRef === '') return;
        await loadTimestampVerse(reciter, parseInt(chapter, 10), verseRef);
    }

    async function loadTimestampVerse(
        reciter: string,
        chapter: number,
        verseRef: string,
    ): Promise<void> {
        document.body.classList.add('loading');
        try {
            const [shard, qpc, dk] = await Promise.all([
                loadChapterShard(reciter, chapter),
                loadQpc(),
                loadDk(),
            ]);
            tsVbrChapters.set(new Set(await loadVbrChapters(reciter)));
            const data = assembleVerseFromShard(reciter, shard, verseRef, qpc, dk);
            if (!data) {
                alert('Error: verse not found in shard');
                return;
            }
            ingestVerseData(data);
        } catch (e) {
            console.error('Error loading timestamp verse:', e);
            alert('Failed to load verse');
        } finally {
            document.body.classList.remove('loading');
        }
    }

    export async function loadRandomTimestamp(
        reciter: string | null = null,
        autoplay: boolean = true,
    ): Promise<void> {
        document.body.classList.add('loading');
        try {
            const target = reciter
                ? consumePreroll('same') ?? await getRandomTarget({ reciter })
                : consumePreroll('any') ?? await getRandomTarget();
            if (!target) {
                console.warn('No timestamp data available');
                return;
            }

            const [shard, qpc, dk] = await Promise.all([
                loadChapterShard(target.reciter, target.chapter),
                loadQpc(),
                loadDk(),
            ]);
            tsVbrChapters.set(new Set(await loadVbrChapters(target.reciter)));
            const data = assembleVerseFromShard(target.reciter, shard, target.verseRef, qpc, dk);
            if (!data) {
                console.error('Random target verse missing from shard:', target);
                return;
            }

            const reciterChanged = get(selectedReciter) !== data.reciter;
            if (reciterChanged) {
                selectedReciter.set(data.reciter);
                localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
                try {
                    const m = await loadManifest();
                    chapters.set(m.reciters[data.reciter]?.ts_chapters ?? []);
                } catch {
                    chapters.set([]);
                }
            }
            if (reciterChanged || get(selectedChapter) !== String(data.chapter)) {
                selectedChapter.set(String(data.chapter));
                await populateVersesFor(data.reciter, data.chapter);
            }

            ingestVerseData(data, autoplay);
        } catch (e) {
            console.error('Error loading random timestamp:', e);
        } finally {
            document.body.classList.remove('loading');
            // Refresh both pre-rolls in parallel — fire-and-forget; the cache
            // they leave behind makes the next click instant.
            primePrerolls();
        }
    }

    // ---------------------------------------------------------------------
    // Bookmark deep-link: load a SPECIFIC verse with a RANDOM published
    // reciter and autoplay. Mirrors loadRandomTimestamp's reciter/chapter
    // store-setting but pins the verseRef to the bookmarked verse.
    // ---------------------------------------------------------------------

    let navHandled = false;

    function shuffle<T>(arr: T[]): T[] {
        for (let i = arr.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [arr[i], arr[j]] = [arr[j]!, arr[i]!];
        }
        return arr;
    }

    export async function loadVerseRandomReciter(
        surah: number,
        ayah: number,
        autoplay: boolean = true,
    ): Promise<void> {
        document.body.classList.add('loading');
        const verseRef = `${surah}:${ayah}`;
        try {
            const m = await loadManifest();
            const candidates = shuffle(
                Object.keys(m.reciters).filter((slug) =>
                    m.reciters[slug]?.ts_chapters?.includes(surah),
                ),
            );
            const [qpc, dk] = await Promise.all([loadQpc(), loadDk()]);
            for (const reciter of candidates.slice(0, 6)) {
                try {
                    const shard = await loadChapterShard(reciter, surah);
                    if (!chapterVerseRefs(shard).includes(verseRef)) continue;
                    tsVbrChapters.set(new Set(await loadVbrChapters(reciter)));
                    const data = assembleVerseFromShard(reciter, shard, verseRef, qpc, dk);
                    if (!data) continue;
                    selectedReciter.set(data.reciter);
                    localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
                    chapters.set(m.reciters[data.reciter]?.ts_chapters ?? []);
                    selectedChapter.set(String(data.chapter));
                    await populateVersesFor(data.reciter, data.chapter);
                    ingestVerseData(data, autoplay);
                    return;
                } catch {
                    // Shard 404 / assemble miss — try the next reciter.
                    continue;
                }
            }
            // No published reciter has this exact verse — fall back to random
            // so the tab still shows something rather than an empty state.
            console.warn(`No reciter found for ${verseRef}; falling back to random`);
            await loadRandomTimestamp(null, autoplay);
        } catch (e) {
            console.error('Error loading bookmarked verse:', e);
        } finally {
            document.body.classList.remove('loading');
            primePrerolls();
        }
    }

    function consumePendingNav(nav: { surah: number; ayah: number; autoplay: boolean }): void {
        navHandled = true;
        pendingTsNavigation.set(null);
        void loadVerseRandomReciter(nav.surah, nav.ayah, nav.autoplay);
    }

    /** Consume the matching pre-roll if it exists, otherwise return null. */
    function consumePreroll(
        kind: 'same' | 'any',
    ): { reciter: string; chapter: number; verseRef: string } | null {
        if (kind === 'same') {
            const r = get(selectedReciter);
            if (nextRandomSame && nextRandomSame.reciter === r) {
                const t = nextRandomSame;
                nextRandomSame = null;
                return t;
            }
            return null;
        }
        const t = nextRandomAny;
        nextRandomAny = null;
        return t;
    }

    /** Re-roll both pre-rolls. Their shards are pre-fetched into the LRU
     *  by `getRandomTarget` itself, so consuming the pre-roll is dict-fast. */
    function primePrerolls(): void {
        const reciter = get(selectedReciter) || null;
        if (reciter) {
            getRandomTarget({ reciter })
                .then((t) => { nextRandomSame = t; })
                .catch(() => { nextRandomSame = null; });
        } else {
            nextRandomSame = null;
        }
        getRandomTarget()
            .then((t) => { nextRandomAny = t; })
            .catch(() => { nextRandomAny = null; });
    }

    function ingestVerseData(data: TsDataResponse, autoplay: boolean = true): void {
        const tsSegOffset = data.time_start_ms / 1000;
        const tsSegEnd = data.time_end_ms / 1000;

        loadedVerse.set({ data, tsSegOffset, tsSegEnd });
        selectedReciter.set(data.reciter);
        selectedChapter.set(String(data.chapter));
        selectedVerse.set(data.verse_ref);

        // Route per-surah audio through audio-proxy so the bucket-mounted
        // file (deployed NFS or local FUSE auto-mount) is served via
        // sendfile + Range/304. Falls through to a CDN stream-through inside
        // the proxy when the chapter isn't prefetched. Sending the browser
        // straight at the CDN URL wastes the prefetch and bills upstream.
        const playUrl = (data.audio_category === 'by_surah_audio'
            && data.audio_url
            && !data.audio_url.startsWith('/api/'))
            ? `/api/seg/audio-proxy/${data.reciter}?url=${encodeURIComponent(data.audio_url)}`
            : data.audio_url;
        tsPort.setSource({
            audioUrl: data.audio_url,
            cbrSrc: playUrl,
            reciter: data.reciter,
            vbr: get(tsVbrChapters).has(data.chapter),
        });
        // Auto-next reaches here right after AudioRange.`_pauseAndFlush` ramped
        // the gain to 0. The eventual `setRange→_uncut` lifting it back to 1
        // runs in a microtask AFTER `audioComp.load` synchronously kicks off
        // `audio.play()`, so the new verse plays silent for ~5 ms — long
        // enough to look "stuck paused" if the browser also rejects the
        // play() (autoplay policy). Lift the cut on the same tick as the
        // load so the next play() sees gain=1 immediately.
        tsPort.uncut();
        audioComp?.load(playUrl, tsSegOffset, autoplay);
        autoAdvancing.set(false);
        // Verse change invalidates any active loop target.
        loopTarget.set(null);
    }

    function clearDisplay(): void {
        loadedVerse.set(null);
    }

    // ---------------------------------------------------------------------
    // Nav
    // ---------------------------------------------------------------------

    export function navigateVerse(delta: number): void {
        const vs = get(verses);
        const sel = get(selectedVerse);
        const idx = vs.findIndex((v) => v.ref === sel);
        const newIdx = idx + delta;
        if (newIdx < 0 || newIdx >= vs.length) {
            autoAdvancing.set(false);
            return;
        }
        const next = vs[newIdx];
        if (!next) return;
        selectedVerse.set(next.ref);
        onVerseChange(next.ref);
    }

    // ---------------------------------------------------------------------
    // Highlight tick — called by TimestampsAudio on each rAF frame
    // ---------------------------------------------------------------------

    function onTick(): void {
        if (get(viewMode) === TS_VIEW_MODES.ANIMATION) {
            if (animDisplayEl) animDisplayEl.updateHighlights();
        } else {
            if (unifiedEl) unifiedEl.updateHighlights();
        }
        if (waveformTabEl) waveformTabEl.drawOverlays();
    }

    // ---------------------------------------------------------------------
    // Reactive: CSS vars + nav button state
    // ---------------------------------------------------------------------

    $: cfg = $tsConfig;
    $: highlightColor = cfg?.anim_highlight_color ?? '#f0a500';
    $: wordDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_word_transition_duration}s`
            : '0s';
    $: charDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_char_transition_duration}s`
            : '0s';
    $: easing =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE ? cfg.anim_transition_easing : TS_EASING_DEFAULT;
    $: wordTransition = `opacity ${wordDur} ${easing}`;
    $: charTransition = `opacity ${charDur} ${easing}`;

    $: segmentSelectedIdx = $verses.findIndex((v) => v.ref === $selectedVerse);
    $: prevDisabled = segmentSelectedIdx <= 0;
    $: nextDisabled = segmentSelectedIdx < 0 || segmentSelectedIdx >= $verses.length - 1;

    // Bookmark deep-link consumer: fires on mount (if a click set it before the
    // tab mounted) and on every later bookmark click while the tab stays mounted.
    $: if ($pendingTsNavigation) consumePendingNav($pendingTsNavigation);

    // Current verse → bookmarkable surah:ayah (strip any compound-ref suffix).
    $: currentVerseKey = (() => {
        const ref = $selectedVerse;
        if (!ref) return '';
        const head = ref.split('-')[0] ?? ref;
        const [s, a] = head.split(':');
        const surah = parseInt(s ?? '', 10);
        const ayah = parseInt(a ?? '', 10);
        return surah && ayah ? `${surah}:${ayah}` : '';
    })();
    $: bookmarkedCurrent = currentVerseKey ? isBookmarked($bookmarks, currentVerseKey) : false;

    function toggleVerseBookmark(): void {
        if (!currentVerseKey) return;
        if (bookmarkedCurrent) {
            removeBookmark(currentVerseKey);
        } else {
            const [s, a] = currentVerseKey.split(':');
            addBookmark(parseInt(s ?? '', 10), parseInt(a ?? '', 10));
        }
    }

    // ---------------------------------------------------------------------
    // Mount
    // ---------------------------------------------------------------------

    onMount(() => {
        // Wire waveform-zoom reset triggers (loop exit, verse change). Idempotent
        // — internal `_wired` guard makes it safe to call on every mount even if
        // TimestampsTab.svelte ever gets remounted (e.g. tab swap teardown).
        setupZoomLifecycle();
        init();
    });
</script>

<TimestampsKeyboard
    {audioComp}
    on:navigateVerse={(e) => navigateVerse(e.detail)}
    on:randomAny={() => loadRandomTimestamp()}
    on:randomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
    on:setView={(e) => viewControlsComp?.setView(e.detail)}
    on:toggleModeA={() => viewControlsComp?.toggleModeA()}
    on:toggleModeB={() => viewControlsComp?.toggleModeB()}
    on:scrollActive={() => {
        if (get(viewMode) === TS_VIEW_MODES.ANIMATION) animDisplayEl?.scrollActiveIntoView();
        else unifiedEl?.scrollActiveIntoView();
    }}
    on:cycleSpeed={(e) => controlsComp?.cycleSpeed(e.detail)}
    on:tick={onTick}
/>

<div
    id="timestamps-panel"
    style:--unified-display-max-height="{cfg?.unified_display_max_height ?? TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX}px"
    style:--anim-highlight-color={highlightColor}
    style:--anim-word-transition={wordTransition}
    style:--anim-char-transition={charTransition}
    style:--anim-word-spacing={cfg?.anim_word_spacing ?? ''}
    style:--anim-line-height={cfg?.anim_line_height ?? ''}
    style:--anim-font-size={cfg?.anim_font_size ?? ''}
    style:--analysis-word-font-size={cfg?.analysis_word_font_size ?? ''}
    style:--analysis-letter-font-size={cfg?.analysis_letter_font_size ?? ''}
>
    <TimestampsShortcutsGuide />

    <TimestampsControls
        bind:this={controlsComp}
        on:reciterChange={(e) => onReciterChange(e.detail)}
        on:chapterChange={(e) => onChapterChange(e.detail)}
        on:verseChange={(e) => onVerseChange(e.detail)}
    />

    {#if currentVerseKey}
        <div class="ts-bookmark-row">
            <button
                type="button"
                class="ts-bookmark-btn"
                class:active={bookmarkedCurrent}
                title={bookmarkedCurrent ? 'Remove bookmark' : 'Bookmark this verse'}
                on:click={toggleVerseBookmark}
            >
                {bookmarkedCurrent ? '★ Bookmarked' : '☆ Bookmark verse'}
            </button>
        </div>
    {/if}

    <main>
        <TimestampsAudio
            bind:this={audioComp}
            {prevDisabled}
            {nextDisabled}
            on:prev={() => navigateVerse(-1)}
            on:next={() => navigateVerse(+1)}
            on:tick={onTick}
            on:autoNext={() => navigateVerse(+1)}
            on:autoRandomAny={() => loadRandomTimestamp()}
            on:autoRandomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
        />

        <TimestampsViewControls
            bind:this={viewControlsComp}
            on:randomAny={() => loadRandomTimestamp()}
            on:randomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
        />

        <div class="waveform-words-row">
            <TimestampsWaveform bind:this={waveformTabEl} />
            <div hidden={$viewMode === TS_VIEW_MODES.ANIMATION}>
                <UnifiedDisplay bind:this={unifiedEl} />
            </div>
            <div hidden={$viewMode === TS_VIEW_MODES.ANALYSIS}>
                <AnimationDisplay bind:this={animDisplayEl} />
            </div>
        </div>
    </main>
</div>

<style>
    .ts-bookmark-row {
        display: flex;
        justify-content: center;
        margin: 6px 0 2px;
    }
    .ts-bookmark-btn {
        background: #16213e;
        color: #d8def0;
        border: 1px solid #2a3a6a;
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.2s, color 0.2s, border-color 0.2s;
    }
    .ts-bookmark-btn:hover { background: #1c294b; border-color: #4cc9f0; }
    .ts-bookmark-btn.active { color: #f0a500; border-color: #f0a500; }
</style>
