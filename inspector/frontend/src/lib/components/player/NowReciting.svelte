<script lang="ts">
    /**
     * Dashboard "now reciting" section — the recitation line animation + ayah
     * filmstrip, pinned directly above the BottomPlayer footer.
     *
     * Shown ONLY while a published reciter is playing (the gate auto-hides it
     * the moment playback switches to an unpublished reciter or clears). Driven
     * by the real `dashPort` transport and `playerContext` store; verse/word
     * timings come from the shared recitation-data loader (kept off `tabs/*`).
     *
     * The display CONTROLS live in this component's handle row — flanking the
     * collapse chip, 3 on each side (upcoming-eye · word/letter · motion |
     * droplet · size− · size+). Config + collapse state are shared via the
     * recitation store; below the handle sit the line + the filmstrip.
     */
    import { tick } from 'svelte';

    import { dashPort } from '../../playback/dash-port';
    import { exitLoop } from '../../playback/loop';
    import {
        AyahFilmstrip,
        ControlIcon,
        RecitationSection,
        type AnimUnit,
        type AyahBoundary,
    } from '../../recitation-animation';
    import { loadChapterRecitation } from '../../recitation-data/load-chapter';
    import {
        cycleMotion,
        cycleUpcoming,
        eyeIconName,
        granIconName,
        motionIconName,
        recitationAvailable,
        recitationAyahs,
        recitationConfigStore,
        recitationFocus,
        recitationOpen,
        setHighlight,
        SIZE_MAX,
        SIZE_MIN,
        sizeDown,
        sizeUp,
        toggleGranularity,
    } from '../../recitation-animation/recitation-settings';
    import {
        addBookmark,
        bookmarkKey,
        bookmarks,
        isBookmarked,
        removeBookmark,
        toggleBookmarksPanel,
    } from '../../stores/bookmarks';
    import { playerContext } from '../../stores/player-context';
    import { progressHoverMs, progressScrubMs } from '../../stores/progress-hover';
    import { activeTab } from '../../utils/active-tab';
    import { TAB_NAMES } from '../../utils/constants';

    let units = $state<AnimUnit[]>([]);
    let ayahs = $state<AyahBoundary[]>([]);
    let rootH = $state(0);
    // Surah:ayah under the playhead — drives the filmstrip bookmark button.
    // Sourced from `recitationFocus`, which TimestampsTab writes from its
    // existing per-frame tick (`focusAt(ms)`). No separate rAF needed; the
    // tab already locates the focus verse for its own use.
    const focusSurah = $derived($recitationFocus?.surah ?? 0);
    const focusAyah = $derived($recitationFocus?.ayah ?? 0);

    let section = $state<{ refresh: () => void } | undefined>(undefined);
    let filmstrip = $state<{ refresh: () => void; showFirstAyah: () => void } | undefined>(undefined);
    let colorInput = $state<HTMLInputElement | undefined>(undefined);

    const config = $derived($recitationConfigStore);
    const near = (a: number, b: number): boolean => Math.abs(a - b) < 0.001;
    const upcomingLabel = $derived(
        near(config.unreachedOpacity, 0.8) ? 'full'
        : near(config.unreachedOpacity, 0) ? 'hidden' : 'dim',
    );

    // ---- published gate + live transport state ----
    const isPublished = $derived(
        $playerContext.reciter !== null
        && $playerContext.delivery?.bucket === 'published'
        && $playerContext.surahNum !== null,
    );
    const reciterSlug = $derived($playerContext.delivery?.slug ?? '');
    const surahNum = $derived($playerContext.surahNum ?? 0);
    const playing = $derived($playerContext.isPlaying);
    const shown = $derived(isPublished && units.length > 0);

    const getTimeMs = (): number => {
        if (!dashPort.window && !playing) return $playerContext.positionMs;
        return dashPort.currentTimeMs();
    };

    // ---- Filmstrip bookmark (Timestamps tab only) ----
    const isTimestamps = $derived($activeTab === TAB_NAMES.TIMESTAMPS);
    const focusKey = $derived(focusSurah && focusAyah ? bookmarkKey(focusSurah, focusAyah) : '');
    const focusBookmarked = $derived(focusKey ? isBookmarked($bookmarks, focusKey) : false);

    function toggleFocusBookmark(): void {
        if (!focusSurah || !focusAyah) return;
        if (focusBookmarked) removeBookmark(focusKey);
        else addBookmark(focusSurah, focusAyah);
    }

    function seek(ms: number): void {
        exitLoop(); // filmstrip / line click is deliberate navigation → drop loop
        dashPort.seek(ms);
        dashPort.play();
        if (!playing) {
            section?.refresh();
            filmstrip?.refresh();
        }
    }

    // Load chapter recitation when the published reciter / surah changes.
    $effect(() => {
        if (!isPublished || !reciterSlug || !surahNum) {
            units = [];
            ayahs = [];
            recitationAyahs.set([]);
            return;
        }
        const slug = reciterSlug;
        const chapter = surahNum;
        const controller = new AbortController();
        void loadChapterRecitation(slug, chapter, controller.signal)
            .then(async (res) => {
                if (controller.signal.aborted) return;
                units = res?.units ?? [];
                ayahs = res?.ayahs ?? [];
                recitationAyahs.set(ayahs);
                await tick();
                if (controller.signal.aborted) return;
                section?.refresh();
                filmstrip?.showFirstAyah();
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    units = [];
                    ayahs = [];
                    recitationAyahs.set([]);
                }
            });
        return () => controller.abort();
    });

    // Publish availability so the footer controls show exactly when shown.
    $effect(() => {
        recitationAvailable.set(shown);
    });

    // Progress-bar drag release while paused. The bar seeks straight through
    // BottomPlayer → dashPort.seek, bypassing our seek() — and with no rAF loop
    // while paused, the line + filmstrip stay on the old position until the next
    // play. Re-center them on the release edge (scrub → null) just like seek()'s
    // paused branch. The seek has already applied synchronously in the pointerup
    // handler by the time this effect flushes, so getTimeMs() reads the new time.
    let wasScrubbing = false;
    $effect(() => {
        const scrubbing = $progressScrubMs != null;
        if (wasScrubbing && !scrubbing && !playing) {
            section?.refresh();
            filmstrip?.refresh();
        }
        wasScrubbing = scrubbing;
    });

    // Reserve scroll-area height under the section (DashboardTab adds it to its
    // padding) so dashboard content isn't hidden behind the fixed strip.
    $effect(() => {
        const h = shown ? rootH : 0;
        document.documentElement.style.setProperty('--now-reciting-h', `${h}px`);
        return () => document.documentElement.style.setProperty('--now-reciting-h', '0px');
    });
</script>

{#if shown}
    <div class="now-reciting" bind:clientHeight={rootH}>
        <!-- Handle row: the recitation display controls flank the collapse chip,
             3 on each side. Left = upcoming-eye · word/letter · filmstrip motion;
             right = highlight droplet · size− · size+. Collapsing hides the
             recitation LINE *and* this settings row (only the chip stays); the
             filmstrip stays. Chevron points up when collapsed (expand), down
             when expanded (collapse). -->
        <div class="nr-handle">
            {#if $recitationOpen}
                <div class="nr-ctrls" role="group" aria-label="Recitation display">
                    <button
                        type="button" class="nr-btn"
                        aria-label="Cycle upcoming text visibility"
                        title={`Upcoming text: ${upcomingLabel}`}
                        onclick={cycleUpcoming}
                    ><ControlIcon name={eyeIconName(config)} size={18} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label="Toggle word / letter"
                        title={config.granularity === 'char' ? 'Letter-by-letter' : 'Word-by-word'}
                        onclick={toggleGranularity}
                    ><ControlIcon name={granIconName(config)} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label="Toggle filmstrip motion"
                        title={config.filmstripMotion === 'snap' ? 'Snap to ayah' : 'Continuous glide'}
                        onclick={cycleMotion}
                    ><ControlIcon name={motionIconName(config)} /></button>
                </div>
            {/if}

            <button
                type="button"
                class="collapse-chip"
                aria-expanded={$recitationOpen}
                title={$recitationOpen ? 'Collapse line' : 'Expand line'}
                onclick={() => recitationOpen.set(!$recitationOpen)}
            >
                <span class="chev" class:open={$recitationOpen} aria-hidden="true">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
                        <path d="m6 9 6 6 6-6" />
                    </svg>
                </span>
            </button>

            {#if $recitationOpen}
                <div class="nr-ctrls" role="group" aria-label="Text size & color">
                    <div class="nr-swatch-wrap">
                        <button
                            type="button" class="nr-btn swatch"
                            aria-label="Highlight color"
                            title="Highlight color"
                            style:color={config.highlightColor}
                            onclick={() => colorInput?.click()}
                        ><ControlIcon name="droplet" /></button>
                        <input
                            bind:this={colorInput}
                            type="color"
                            class="nr-color-input"
                            value={config.highlightColor}
                            oninput={(e) => setHighlight(e.currentTarget.value)}
                            tabindex="-1"
                            aria-hidden="true"
                        />
                    </div>
                    <button
                        type="button" class="nr-btn"
                        aria-label="Decrease text size"
                        title="Smaller text"
                        disabled={config.fontSizePx <= SIZE_MIN}
                        onclick={sizeDown}
                    ><ControlIcon name="size-down" size={16} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label="Increase text size"
                        title="Larger text"
                        disabled={config.fontSizePx >= SIZE_MAX}
                        onclick={sizeUp}
                    ><ControlIcon name="size-up" size={16} /></button>
                </div>
            {/if}
        </div>

        {#if $recitationOpen}
            <RecitationSection
                bind:this={section}
                {units}
                {config}
                {getTimeMs}
                {playing}
                open={true}
                showHeader={false}
                onSeekToWord={seek}
            />
        {/if}

        {#if config.filmstripShow && ayahs.length}
            <div class="strip-wrap">
                {#if isTimestamps}
                    <div class="strip-bm" role="group" aria-label="Bookmarks">
                        <button
                            type="button" class="strip-bm-btn" class:on={focusBookmarked}
                            disabled={!focusKey} aria-pressed={focusBookmarked}
                            title={focusBookmarked ? 'Remove bookmark' : 'Bookmark this verse'}
                            onclick={toggleFocusBookmark}
                        ><ControlIcon name={focusBookmarked ? 'bookmark-filled' : 'bookmark'} size={16} /></button>
                        <button
                            type="button" class="strip-bm-btn"
                            title="Open bookmarks panel" aria-label="Open bookmarks panel"
                            onclick={toggleBookmarksPanel}
                        ><ControlIcon name="bookmarks-panel" size={16} /></button>
                    </div>
                {/if}
                <div class="strip-flex">
                    <AyahFilmstrip
                        bind:this={filmstrip}
                        {ayahs}
                        durationMs={$playerContext.durationMs}
                        {getTimeMs}
                        {playing}
                        {config}
                        hoverMs={$progressHoverMs}
                        scrubMs={$progressScrubMs}
                        onSeek={seek}
                    />
                </div>
            </div>
        {/if}
    </div>
{/if}

<style>
    .now-reciting {
        position: fixed;
        left: 0;
        right: 0;
        bottom: var(--player-h, 92px);
        z-index: 109; /* just under the footer (110) */
        background: var(--panel);
        border-top: 1px solid var(--border-quiet);
        padding: 2px var(--s-4) var(--s-2);
        box-shadow: 0 -6px 18px oklch(0 0 0 / 0.18);
    }
    /* Handle row: display controls flank the collapse chip (3 each side). */
    .nr-handle {
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--s-2);
        min-height: 22px;
    }
    .nr-swatch-wrap {
        position: relative;
        display: inline-flex;
        flex: 0 0 auto;
    }
    .nr-ctrls {
        display: inline-flex;
        align-items: center;
        gap: 1px;
    }
    .nr-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 20px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .nr-btn:hover:not(:disabled) { color: var(--text-primary); background: var(--panel-2); }
    .nr-btn:disabled { opacity: 0.3; cursor: not-allowed; }
    .nr-btn.swatch:hover:not(:disabled) { background: var(--panel-2); filter: brightness(1.12); }
    .nr-color-input {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        margin: 0;
        padding: 0;
        border: 0;
        opacity: 0;
        cursor: pointer;
        pointer-events: none;
    }
    .strip-wrap {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding-top: var(--s-1);
    }
    .strip-flex { flex: 1 1 auto; min-width: 0; }
    .strip-bm {
        display: inline-flex;
        align-items: center;
        gap: 1px;
        flex: 0 0 auto;
    }
    .strip-bm-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 22px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .strip-bm-btn:hover:not(:disabled) { color: var(--text-primary); background: var(--panel-2); }
    .strip-bm-btn.on { color: var(--accent); background: var(--accent-tint); }
    .strip-bm-btn:disabled { opacity: 0.3; cursor: not-allowed; }
    .collapse-chip {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 16px;
        padding: 0;
        color: var(--text-faint);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .collapse-chip:hover {
        color: var(--text-primary);
        background: var(--panel-3, var(--panel-2));
    }
    .chev {
        display: inline-flex;
        transition: transform var(--t-fast) var(--ease-out-quart);
        transform: rotate(180deg); /* collapsed → points up (expand) */
    }
    .chev.open {
        transform: rotate(0deg); /* expanded → points down (collapse) */
    }
</style>
