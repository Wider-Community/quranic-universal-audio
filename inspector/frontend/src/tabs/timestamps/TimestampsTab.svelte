<script lang="ts">
    /**
     * TimestampsTab — composition shell for the Timestamps tab.
     *
     * Owns:
     *   - Reciter/chapter/verse cascade (data fetch + store writes).
     *   - Config fetch → CSS custom-property bindings on the root div.
     *   - Delegating to subcomponents: TimestampsControls, TimestampsAudio,
     *     TimestampsKeyboard, TimestampsShortcutsGuide.
     *   - Passing display-update callbacks to UnifiedDisplay / AnimationDisplay /
     *     TimestampsWaveform (imperative 60fps highlight path).
     */

    import { get } from 'svelte/store';
    import { onMount } from 'svelte';

    import { fetchJson } from '../../lib/api';
    import {
        autoAdvancing,
        loopTarget,
    } from './stores/playback';
    import {
        granularity,
        showLetters,
        showPhonemes,
        tsConfig,
        viewMode,
        TS_VIEW_MODES,
        TS_GRANULARITIES,
    } from './stores/display';
    import {
        chapters,
        loadedVerse,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        validationData,
        verses,
    } from './stores/verse';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady } from '../../lib/utils/surah-info';
    import type {
        TsChaptersResponse,
        TsConfigResponse,
        TsDataResponse,
        TsRecitersResponse,
        TsValidateResponse,
        TsVersesResponse,
    } from '../../lib/types/api';

    import AnimationDisplay from './components/AnimationDisplay.svelte';
    import TimestampsAudio from './components/TimestampsAudio.svelte';
    import TimestampsControls from './components/TimestampsControls.svelte';
    import TimestampsKeyboard from './components/TimestampsKeyboard.svelte';
    import TimestampsShortcutsGuide from './components/TimestampsShortcutsGuide.svelte';
    import TimestampsValidationPanel from './components/TimestampsValidationPanel.svelte';
    import TimestampsViewControls from './components/TimestampsViewControls.svelte';
    import TimestampsWaveform from './components/TimestampsWaveform.svelte';
    import UnifiedDisplay from './components/UnifiedDisplay.svelte';
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

    // ---------------------------------------------------------------------
    // Initial load
    // ---------------------------------------------------------------------

    async function init(): Promise<void> {
        fetchJson<TsConfigResponse>('/api/ts/config').then((cfg) => tsConfig.set(cfg));

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
                if (sG === TS_GRANULARITIES.WORDS || sG === TS_GRANULARITIES.CHARACTERS) granularity.set(sG);
            }
        }

        await surahInfoReady;
        await loadReciters();

        // First-load auto-pick: if we have a persisted reciter, let the
        // reciter-change path auto-load a random verse from it. Otherwise
        // load a random verse from any reciter. Both open paused.
        const savedReciter = localStorage.getItem(LS_KEYS.TS_RECITER);
        if (savedReciter) {
            selectedReciter.set(savedReciter);
            await onReciterChange(savedReciter);
        } else {
            await loadRandomTimestamp(null, /* autoplay */ false);
        }
    }

    async function loadReciters(): Promise<void> {
        try {
            const rs = await fetchJson<TsRecitersResponse>('/api/ts/reciters');
            reciters.set(rs);
        } catch (e) {
            console.error('Error loading ts reciters:', e);
        }
    }

    // ---------------------------------------------------------------------
    // Reciter / chapter / verse cascade
    // ---------------------------------------------------------------------

    async function onReciterChange(reciter: string): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.TS_RECITER, reciter);
        chapters.set([]);
        selectedChapter.set('');
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        validationData.set(null);
        if (!reciter) return;

        try {
            const [chapResult, valResult] = await Promise.allSettled([
                fetchJson<TsChaptersResponse>(`/api/ts/chapters/${reciter}`),
                fetchJson<TsValidateResponse>(`/api/ts/validate/${reciter}`),
            ]);
            if (chapResult.status === 'fulfilled' && Array.isArray(chapResult.value)) {
                chapters.set(chapResult.value);
            }
            if (
                valResult.status === 'fulfilled' &&
                !valResult.value.error
            ) {
                validationData.set(valResult.value);
            }
        } catch (e) {
            console.error('Error loading ts reciter data:', e);
        }
        // Auto-load a random verse (paused) from this reciter so the tab
        // always has something on screen after a reciter change.
        await loadRandomTimestamp(reciter, /* autoplay */ false);
    }

    async function onChapterChange(chapter: string): Promise<void> {
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        const reciter = get(selectedReciter);
        if (!reciter || !chapter) return;

        try {
            const data = await fetchJson<TsVersesResponse & { error?: string }>(
                `/api/ts/verses/${reciter}/${chapter}`,
            );
            if (data.error) return;
            verses.set(
                (data.verses || []).map((v) => ({ ref: v.ref, audio_url: v.audio_url || '' })),
            );
        } catch (e) {
            console.error('Error loading ts verses:', e);
        }
    }

    async function jumpToTsVerse(verseKey: string): Promise<void> {
        if (!verseKey || !verseKey.includes(':')) return;
        const chapter = verseKey.split(':')[0] ?? '';

        if (get(selectedChapter) !== chapter) {
            selectedChapter.set(chapter);
            await onChapterChange(chapter);
        }
        selectedVerse.set(verseKey);
        await onVerseChange(verseKey);
    }

    async function onVerseChange(verseRef: string): Promise<void> {
        const reciter = get(selectedReciter);
        const chapter = get(selectedChapter);
        if (!reciter || !chapter || verseRef === '') return;
        await loadTimestampVerse(reciter, verseRef);
    }

    async function loadTimestampVerse(reciter: string, verseRef: string): Promise<void> {
        document.body.classList.add('loading');
        try {
            const data = await fetchJson<TsDataResponse & { error?: string }>(
                `/api/ts/data/${reciter}/${verseRef}`,
            );
            if (data.error) {
                alert('Error: ' + data.error);
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
            const url = reciter
                ? `/api/ts/random/${encodeURIComponent(reciter)}`
                : '/api/ts/random';
            const data = await fetchJson<TsDataResponse & { error?: string }>(url);
            if (data.error) {
                alert('Error: ' + data.error);
                return;
            }

            const reciterChanged = get(selectedReciter) !== data.reciter;
            if (reciterChanged) {
                selectedReciter.set(data.reciter);
                localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
                validationData.set(null);
                try {
                    const chs = await fetchJson<TsChaptersResponse>(
                        `/api/ts/chapters/${encodeURIComponent(data.reciter)}`,
                    );
                    if (Array.isArray(chs)) chapters.set(chs);
                } catch {
                    chapters.set([]);
                }
            }
            if (reciterChanged || get(selectedChapter) !== String(data.chapter)) {
                selectedChapter.set(String(data.chapter));
                try {
                    const vData = await fetchJson<TsVersesResponse>(
                        `/api/ts/verses/${encodeURIComponent(data.reciter)}/${data.chapter}`,
                    );
                    verses.set(
                        (vData.verses || []).map((v) => ({
                            ref: v.ref,
                            audio_url: v.audio_url || '',
                        })),
                    );
                } catch {
                    verses.set([]);
                }
            }

            ingestVerseData(data, autoplay);
        } catch (e) {
            console.error('Error loading random timestamp:', e);
        } finally {
            document.body.classList.remove('loading');
        }
    }

    function ingestVerseData(data: TsDataResponse, autoplay: boolean = true): void {
        const tsSegOffset = data.time_start_ms / 1000;
        const tsSegEnd = data.time_end_ms / 1000;

        loadedVerse.set({ data, tsSegOffset, tsSegEnd });
        selectedReciter.set(data.reciter);
        selectedChapter.set(String(data.chapter));
        selectedVerse.set(data.verse_ref);

        // For per-surah audio (large files) route playback through the local
        // audio-proxy so the Flask layer can disk-cache + Range-serve. The
        // store keeps the raw CDN URL so the peaks endpoint (which itself
        // fetches the URL server-side) doesn't loop through the proxy.
        const playUrl = (data.audio_category === 'by_surah_audio'
            && data.audio_url
            && !data.audio_url.startsWith('/api/'))
            ? `/api/seg/audio-proxy/${data.reciter}?url=${encodeURIComponent(data.audio_url)}`
            : data.audio_url;
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

    <TimestampsValidationPanel onJump={jumpToTsVerse} />

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
