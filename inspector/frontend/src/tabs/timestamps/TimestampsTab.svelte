<script lang="ts">
    /**
     * TimestampsTab — top-level Svelte component for the Timestamps tab.
     *
     * Replaces the Stage-1 imperative timestamps/index.ts + state.ts + dom
     * plumbing. Owns:
     *   - Reciter/chapter/verse dropdowns (cascaded via the verse store).
     *   - Audio element + speed control + prev/next nav + random buttons.
     *   - View toggle (Analysis / Animation) and mode toggle (Letters/Phonemes
     *     or Words/Characters, context-sensitive).
     *   - Config fetch → CSS var bindings (9 vars from /api/ts/config).
     *   - Keyboard shortcut handler via <svelte:window on:keydown>.
     *   - Analysis view rendering via <UnifiedDisplay>. Animation view and
     *     waveform land in sub-wave 4b.
     *
     * Pattern (for Waves 5-10):
     *   - Stores for tab-scoped state (lib/stores/timestamps/*).
     *   - Props for parent→child; events for child→parent.
     *   - Imperative 60fps highlight updates via bind:this + component methods.
     *   - CSS vars set as `style:` directives on this root div (scoped,
     *     reactive if config ever changes) — NOT on :root.
     */

    import { get } from 'svelte/store';

    import AudioElement from '../../lib/components/AudioElement.svelte';
    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import SpeedControl from '../../lib/components/SpeedControl.svelte';
    import { fetchJson } from '../../lib/api';
    import {
        autoAdvancing,
        autoMode,
        currentTime,
    } from '../../lib/stores/timestamps/playback';
    import {
        granularity,
        showLetters,
        showPhonemes,
        tsConfig,
        viewMode,
    } from '../../lib/stores/timestamps/display';
    import {
        chapters,
        chaptersOptions,
        loadedVerse,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        validationData,
        verses,
        versesOptions,
    } from '../../lib/stores/timestamps/verse';
    import { createAnimationLoop } from '../../lib/utils/animation';
    import { safePlay } from '../../lib/utils/audio';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { shouldHandleKey } from '../../lib/utils/keyboard-guard';
    import { surahInfoReady } from '../../lib/utils/surah-info';
    import type {
        TsChaptersResponse,
        TsConfigResponse,
        TsDataResponse,
        TsRecitersResponse,
        TsValidateResponse,
        TsVersesResponse,
    } from '../../types/api';
    import UnifiedDisplay from './UnifiedDisplay.svelte';

    // ---- Component refs ----
    let audioEl: AudioElement;
    let audioHTMLEl: HTMLAudioElement | null = null;
    let speedCtrl: SpeedControl;
    let unifiedEl: UnifiedDisplay;

    // ---- Pending loadedmetadata handler (for src changes) ----
    let _pendingOnMeta: ((ev: Event) => void) | null = null;

    // ---- Animation frame loop (drives currentTime + highlights) ----
    const _animLoop = createAnimationLoop(() => {
        tick();
    });

    // ---------------------------------------------------------------------
    // Initial load
    // ---------------------------------------------------------------------

    async function init(): Promise<void> {
        // Config → CSS var bindings (reactive via style: on root div)
        fetchJson<TsConfigResponse>('/api/ts/config').then((cfg) => tsConfig.set(cfg));

        // Restore view mode + sub-settings immediately (no dependency on reciters)
        const savedView = localStorage.getItem(LS_KEYS.TS_VIEW_MODE);
        if (savedView === 'analysis' || savedView === 'animation') {
            viewMode.set(savedView);
            if (savedView === 'analysis') {
                const sL = localStorage.getItem(LS_KEYS.TS_SHOW_LETTERS);
                const sP = localStorage.getItem(LS_KEYS.TS_SHOW_PHONEMES);
                if (sL !== null) showLetters.set(sL === 'true');
                if (sP !== null) showPhonemes.set(sP === 'true');
            } else {
                const sG = localStorage.getItem(LS_KEYS.TS_GRANULARITY);
                if (sG === 'words' || sG === 'characters') granularity.set(sG);
            }
        }

        await surahInfoReady;
        await loadReciters();

        // Restore saved reciter
        const savedReciter = localStorage.getItem(LS_KEYS.TS_RECITER);
        if (savedReciter) {
            selectedReciter.set(savedReciter);
            await onReciterChange(savedReciter);
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

    function onReciterSelectChange(e: Event): void {
        const target = e.currentTarget as HTMLSelectElement;
        onReciterChange(target.value);
    }

    function onVerseSelectChange(e: Event): void {
        const target = e.currentTarget as HTMLSelectElement;
        onVerseChange(target.value);
    }

    async function onReciterChange(reciter: string): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.TS_RECITER, reciter);
        // Clear cascading state
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
                !(valResult.value as unknown as { error?: string }).error
            ) {
                validationData.set(valResult.value);
            }
        } catch (e) {
            console.error('Error loading ts reciter data:', e);
        }
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

    export async function loadRandomTimestamp(reciter: string | null = null): Promise<void> {
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

            // Sync reciter if changed (without re-triggering full onReciterChange
            // — we already have chapter/verse data we'll populate directly).
            const reciterChanged = get(selectedReciter) !== data.reciter;
            if (reciterChanged) {
                selectedReciter.set(data.reciter);
                localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
                validationData.set(null);
                // Lightweight chapter fetch without the validate call
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

            ingestVerseData(data);
        } catch (e) {
            console.error('Error loading random timestamp:', e);
        } finally {
            document.body.classList.remove('loading');
        }
    }

    function ingestVerseData(data: TsDataResponse): void {
        const tsSegOffset = data.time_start_ms / 1000;
        const tsSegEnd = data.time_end_ms / 1000;

        loadedVerse.set({ data, tsSegOffset, tsSegEnd });
        selectedReciter.set(data.reciter);
        selectedChapter.set(String(data.chapter));
        selectedVerse.set(data.verse_ref);

        loadAudioAndPlay(data.audio_url, tsSegOffset);
    }

    function clearDisplay(): void {
        loadedVerse.set(null);
    }

    // ---------------------------------------------------------------------
    // Audio lifecycle
    // ---------------------------------------------------------------------

    function loadAudioAndPlay(url: string | null | undefined, segOffset: number): void {
        if (!audioHTMLEl) return;
        // Remove stale listener from previous load
        if (_pendingOnMeta) {
            audioHTMLEl.removeEventListener('loadedmetadata', _pendingOnMeta);
            _pendingOnMeta = null;
        }
        if (!url) {
            audioHTMLEl.removeAttribute('src');
            audioHTMLEl.load();
            return;
        }
        const same =
            audioHTMLEl.src === url || audioHTMLEl.src === location.origin + url;
        if (!same) {
            const onMeta = (): void => {
                if (!audioHTMLEl) return;
                audioHTMLEl.removeEventListener('loadedmetadata', onMeta);
                if (_pendingOnMeta === onMeta) _pendingOnMeta = null;
                audioHTMLEl.currentTime = segOffset;
                autoAdvancing.set(false);
                safePlay(audioHTMLEl);
            };
            _pendingOnMeta = onMeta;
            audioHTMLEl.src = url;
            audioHTMLEl.addEventListener('loadedmetadata', onMeta);
        } else {
            audioHTMLEl.currentTime = segOffset;
            autoAdvancing.set(false);
            safePlay(audioHTMLEl);
        }
    }

    function onAudioLoadedMetadata(): void {
        // No-op for now; sub-wave 4b uses this to trigger waveform decode.
    }

    function onAudioPlay(): void {
        _animLoop.start();
    }

    function onAudioPause(): void {
        _animLoop.stop();
        tick(); // final frame so display reflects the paused position
    }

    function onAudioEnded(): void {
        _animLoop.stop();
    }

    function onAudioTimeUpdate(): void {
        if (!audioHTMLEl) return;
        const lv = get(loadedVerse);
        if (!lv) return;

        // Auto-stop at segment end + auto-advance
        if (lv.tsSegEnd > 0 && audioHTMLEl.currentTime >= lv.tsSegEnd) {
            audioHTMLEl.pause();
            audioHTMLEl.currentTime = lv.tsSegEnd;
            if (!get(autoAdvancing)) {
                const mode = get(autoMode);
                if (mode === 'next') {
                    autoAdvancing.set(true);
                    navigateVerse(+1);
                } else if (mode === 'random') {
                    autoAdvancing.set(true);
                    loadRandomTimestamp();
                }
            }
        }
        // When paused, the animation loop is stopped; still update on seek.
        if (audioHTMLEl.paused) tick();
    }

    function onAudioError(): void {
        if (!audioHTMLEl) return;
        const err = audioHTMLEl.error;
        const code = err ? err.code : 0;
        const msgs: Record<number, string> = {
            1: 'aborted',
            2: 'network error',
            3: 'decode error',
            4: 'unsupported format',
        };
        console.error('Audio load error:', msgs[code] || `code ${code}`, audioHTMLEl.src);
        if (_pendingOnMeta) {
            audioHTMLEl.removeEventListener('loadedmetadata', _pendingOnMeta);
            _pendingOnMeta = null;
        }
        autoAdvancing.set(false);
    }

    // ---------------------------------------------------------------------
    // Per-frame update
    // ---------------------------------------------------------------------

    function tick(): void {
        if (!audioHTMLEl) return;
        currentTime.set(audioHTMLEl.currentTime);
        if (unifiedEl) unifiedEl.updateHighlights();
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
    // View / mode toggles
    // ---------------------------------------------------------------------

    function setView(mode: 'analysis' | 'animation'): void {
        viewMode.set(mode);
        localStorage.setItem(LS_KEYS.TS_VIEW_MODE, mode);
        if (mode === 'analysis') {
            // Reset to analysis defaults: Letters on, Phonemes off
            showLetters.set(true);
            showPhonemes.set(false);
        } else {
            // Animation defaults: Words only
            granularity.set('words');
        }
    }

    function toggleModeA(): void {
        if (get(viewMode) === 'analysis') {
            const nv = !get(showLetters);
            showLetters.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_LETTERS, String(nv));
        } else {
            granularity.set('words');
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, 'words');
        }
    }

    function toggleModeB(): void {
        if (get(viewMode) === 'analysis') {
            const nv = !get(showPhonemes);
            showPhonemes.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_PHONEMES, String(nv));
        } else {
            granularity.set('characters');
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, 'characters');
        }
    }

    function toggleAuto(mode: 'next' | 'random'): void {
        autoMode.update((cur) => (cur === mode ? null : mode));
    }

    // ---------------------------------------------------------------------
    // Keyboard
    // ---------------------------------------------------------------------

    function handleKeydown(e: KeyboardEvent): void {
        if (!shouldHandleKey(e, 'timestamps')) return;
        const audio = audioHTMLEl;
        if (!audio) return;
        const lv = get(loadedVerse);
        const segOffset = lv?.tsSegOffset ?? 0;
        const segEnd = lv?.tsSegEnd ?? 0;

        switch (e.code) {
            case 'Space':
                e.preventDefault();
                if (audio.paused) {
                    if (segEnd > 0 && audio.currentTime >= segEnd) {
                        audio.currentTime = segOffset;
                    }
                    safePlay(audio);
                } else {
                    audio.pause();
                }
                break;
            case 'ArrowLeft':
                e.preventDefault();
                audio.currentTime = Math.max(segOffset, audio.currentTime - 3);
                tick();
                break;
            case 'ArrowRight':
                e.preventDefault();
                audio.currentTime = Math.min(segEnd || audio.duration, audio.currentTime + 3);
                tick();
                break;
            case 'ArrowUp': {
                e.preventDefault();
                const t = audio.currentTime - segOffset;
                const ws = lv?.data.words ?? [];
                let prevStart: number | null = null;
                for (let i = ws.length - 1; i >= 0; i--) {
                    const w = ws[i];
                    if (w && w.start < t - 0.01) {
                        prevStart = w.start;
                        break;
                    }
                }
                audio.currentTime = prevStart !== null ? prevStart + segOffset : segOffset;
                tick();
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                const t = audio.currentTime - segOffset;
                const ws = lv?.data.words ?? [];
                let nextStart: number | null = null;
                for (let i = 0; i < ws.length; i++) {
                    const w = ws[i];
                    if (w && w.start > t + 0.01) {
                        nextStart = w.start;
                        break;
                    }
                }
                audio.currentTime =
                    nextStart !== null ? nextStart + segOffset : segEnd || audio.duration;
                tick();
                break;
            }
            case 'Period':
            case 'Comma':
                e.preventDefault();
                speedCtrl?.cycle(e.code === 'Period' ? 'up' : 'down');
                break;
            case 'KeyR':
                if (e.shiftKey) loadRandomTimestamp();
                else loadRandomTimestamp(get(selectedReciter) || null);
                break;
            case 'KeyA':
                e.preventDefault();
                setView(get(viewMode) === 'analysis' ? 'animation' : 'analysis');
                break;
            case 'KeyL':
                e.preventDefault();
                toggleModeA();
                break;
            case 'KeyP':
                e.preventDefault();
                toggleModeB();
                break;
            case 'BracketLeft':
                navigateVerse(-1);
                break;
            case 'BracketRight':
                navigateVerse(+1);
                break;
            case 'KeyJ':
                e.preventDefault();
                unifiedEl?.scrollActiveIntoView();
                break;
        }
    }

    // ---------------------------------------------------------------------
    // Reactive wiring: store changes → side effects
    // ---------------------------------------------------------------------

    // Derived config → CSS custom properties on the root div
    $: cfg = $tsConfig;
    $: highlightColor = cfg?.anim_highlight_color ?? '#f0a500';
    $: wordDur =
        cfg && cfg.anim_transition_easing !== 'none'
            ? `${cfg.anim_word_transition_duration}s`
            : '0s';
    $: charDur =
        cfg && cfg.anim_transition_easing !== 'none'
            ? `${cfg.anim_char_transition_duration}s`
            : '0s';
    $: easing =
        cfg && cfg.anim_transition_easing !== 'none' ? cfg.anim_transition_easing : 'linear';
    $: wordTransition = `opacity ${wordDur} ${easing}`;
    $: charTransition = `opacity ${charDur} ${easing}`;

    // Prev/next disabled state from current selection
    $: segmentSelectedIdx = $verses.findIndex((v) => v.ref === $selectedVerse);
    $: prevDisabled = segmentSelectedIdx <= 0;
    $: nextDisabled = segmentSelectedIdx < 0 || segmentSelectedIdx >= $verses.length - 1;

    // Grouped reciter options (rendered as native <optgroup>)
    interface GroupedReciters {
        group: string;
        items: Array<{ slug: string; name: string }>;
    }
    $: groupedReciters = ((): GroupedReciters[] => {
        const grouped: Record<string, Array<{ slug: string; name: string }>> = {};
        const uncategorized: Array<{ slug: string; name: string }> = [];
        for (const r of $reciters) {
            const src = r.audio_source || '';
            if (src) {
                if (!grouped[src]) grouped[src] = [];
                grouped[src]!.push({ slug: r.slug, name: r.name });
            } else {
                uncategorized.push({ slug: r.slug, name: r.name });
            }
        }
        const out: GroupedReciters[] = [];
        for (const src of Object.keys(grouped).sort()) {
            out.push({ group: src, items: grouped[src] ?? [] });
        }
        if (uncategorized.length > 0) out.push({ group: '(uncategorized)', items: uncategorized });
        return out;
    })();

    // Initialize on mount
    import { onMount } from 'svelte';
    onMount(() => {
        // Grab the raw HTMLAudioElement via the primitive's element() accessor.
        // Svelte 4 mounts children before parent onMount, so `audioEl` is bound
        // by this point. Assigning triggers the reactive `audioElement` prop
        // forward into SpeedControl.
        audioHTMLEl = audioEl.element();
        init();
    });
</script>

<svelte:window on:keydown={handleKeydown} />

<div
    id="timestamps-panel"
    style:--unified-display-max-height="{cfg?.unified_display_max_height ?? 800}px"
    style:--anim-highlight-color={highlightColor}
    style:--anim-word-transition={wordTransition}
    style:--anim-char-transition={charTransition}
    style:--anim-word-spacing={cfg?.anim_word_spacing ?? ''}
    style:--anim-line-height={cfg?.anim_line_height ?? ''}
    style:--anim-font-size={cfg?.anim_font_size ?? ''}
    style:--analysis-word-font-size={cfg?.analysis_word_font_size ?? ''}
    style:--analysis-letter-font-size={cfg?.analysis_letter_font_size ?? ''}
>
    <div class="info-bar">
        <label>Reciter:
            <select
                id="ts-reciter-select"
                bind:value={$selectedReciter}
                on:change={onReciterSelectChange}
            >
                <option value="">{$reciters.length ? '-- select --' : 'Loading...'}</option>
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
                options={$chaptersOptions}
                bind:value={$selectedChapter}
                placeholder="--"
                on:change={(e) => onChapterChange(e.detail)}
            />
        </label>
        <label>Verse:
            <select
                id="ts-segment-select"
                bind:value={$selectedVerse}
                on:change={onVerseSelectChange}
            >
                <option value="">--</option>
                {#each $versesOptions as v}
                    <option value={v.value}>{v.label}</option>
                {/each}
            </select>
        </label>
        <div class="ts-random-group">
            <button class="btn" title="Random verse from any reciter"
                on:click={() => loadRandomTimestamp()}>🎲 Any Reciter</button>
            <button class="btn" title="Random verse from current reciter"
                on:click={() => loadRandomTimestamp($selectedReciter || null)}>🎲 Current Reciter</button>
        </div>
    </div>

    <details class="shortcuts-guide">
        <summary class="shortcuts-guide-summary">Shortcuts &amp; Guide</summary>
        <div class="shortcuts-guide-body">
            <div class="sg-col">
                <h4>Playback</h4>
                <dl>
                    <dt>Space</dt><dd>Play / pause</dd>
                    <dt>&larr; / &rarr;</dt><dd>Seek &plusmn;3 s</dd>
                    <dt>&uarr; / &darr;</dt><dd>Jump to prev / next word boundary</dd>
                    <dt>, / .</dt><dd>Slower / faster playback</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Navigation</h4>
                <dl>
                    <dt>[ / ]</dt><dd>Prev / next verse</dd>
                    <dt>R</dt><dd>Random verse (current reciter)</dd>
                    <dt>Shift+R</dt><dd>Random verse (any reciter)</dd>
                    <dt>J</dt><dd>Scroll active word into view</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Display</h4>
                <dl>
                    <dt>A</dt><dd>Toggle Analysis / Animation view</dd>
                    <dt>L</dt><dd>Toggle letters (analysis) or words mode (animation)</dd>
                    <dt>P</dt><dd>Toggle phonemes (analysis) or letters mode (animation)</dd>
                </dl>
            </div>
            <div class="sg-col">
                <h4>Interactions</h4>
                <dl>
                    <dt>Click word</dt><dd>Seek to that word's start time</dd>
                    <dt>Click waveform</dt><dd>Seek to that position</dd>
                    <dt>Auto Next / Random</dt><dd>Auto-advance when verse ends</dd>
                </dl>
            </div>
        </div>
    </details>

    <!-- Validation panel placeholder (sub-wave 4b) -->
    <div id="ts-validation" class="seg-validation" hidden={$validationData === null}></div>

    <main>
        <div class="audio-controls">
            <button class="btn btn-nav" disabled={prevDisabled}
                title="Previous verse ([)" on:click={() => navigateVerse(-1)}>&#9664; Prev</button>
            <AudioElement
                bind:this={audioEl}
                id="audio-player"
                controls
                on:loadedmetadata={onAudioLoadedMetadata}
                on:play={onAudioPlay}
                on:pause={onAudioPause}
                on:ended={onAudioEnded}
                on:timeupdate={onAudioTimeUpdate}
                on:error={onAudioError}
            />
            <button class="btn btn-nav" disabled={nextDisabled}
                title="Next verse (])" on:click={() => navigateVerse(+1)}>Next &#9654;</button>
            <SpeedControl bind:this={speedCtrl} audioElement={audioHTMLEl} lsKey={LS_KEYS.TS_SPEED} />
        </div>

        <div class="ts-view-controls">
            <div class="ts-view-toggle">
                <button class="ts-view-btn" class:active={$viewMode === 'analysis'}
                    on:click={() => setView('analysis')}>Analysis</button>
                <button class="ts-view-btn" class:active={$viewMode === 'animation'}
                    on:click={() => setView('animation')}>Animation</button>
            </div>
            <div class="ts-mode-toggle">
                <button class="ts-mode-btn"
                    class:active={$viewMode === 'analysis' ? $showLetters : $granularity === 'words'}
                    on:click={toggleModeA}>
                    {$viewMode === 'analysis' ? 'Letters' : 'Words'}
                </button>
                <button class="ts-mode-btn"
                    class:active={$viewMode === 'analysis' ? $showPhonemes : $granularity === 'characters'}
                    on:click={toggleModeB}>
                    {$viewMode === 'analysis' ? 'Phonemes' : 'Letters'}
                </button>
            </div>
            <div class="ts-auto-toggles">
                <button class="ts-auto-btn" class:active={$autoMode === 'next'}
                    title="Auto-advance to next verse" on:click={() => toggleAuto('next')}>Auto Next</button>
                <button class="ts-auto-btn" class:active={$autoMode === 'random'}
                    title="Auto-load random verse (any reciter)" on:click={() => toggleAuto('random')}>Auto Random</button>
            </div>
        </div>

        <div class="waveform-words-row">
            <!-- Waveform canvas — full implementation in sub-wave 4b -->
            <div class="visualization">
                <canvas id="waveform-canvas"></canvas>
                <div class="phoneme-labels" id="phoneme-labels"></div>
            </div>
            <UnifiedDisplay bind:this={unifiedEl} />
            <!-- Animation display — full implementation in sub-wave 4b -->
            <div id="animation-display" class="anim-window" hidden={$viewMode === 'analysis'}></div>
        </div>
    </main>
</div>
