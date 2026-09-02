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
     * collapse chip (silent policy · word/letter · upcoming-eye | size− · size+). The filmstrip
     * motion (glide) toggle sits on the filmstrip itself, right of the bookmark
     * buttons. Config + collapse state are shared via the recitation store; below
     * the handle sit the line + the filmstrip.
     */
    import { tick } from 'svelte';

    import { i18n } from '$lib/i18n/locale.svelte';
    import * as m from '$lib/paraglide/messages';

    import { ensureDashCovering } from '../../playback/dash-covering';
    import { dashPort } from '../../playback/dash-port';
    import { exitLoop } from '../../playback/loop';
    import {
        AyahFilmstrip,
        buildFilmstripModel,
        buildSortedIntervals,
        type CellMissing,
        ControlIcon,
        findActiveAt,
        RecitationSection,
        type AnimUnit,
        type AyahBoundary,
    } from '../../recitation-animation';
    import { type ChapterCoverage, loadChapterRecitation } from '../../recitation-data/load-chapter';
    import {
        cycleMotion,
        cycleUpcoming,
        eyeIconName,
        granIconName,
        motionIconName,
        recitationAvailable,
        recitationAyahAt,
        recitationAyahs,
        recitationConfigStore,
        recitationFocus,
        recitationOpen,
        recitationSilentOmit,
        SIZE_MAX,
        SIZE_MIN,
        sizeDown,
        sizeUp,
        toggleGranularity,
        toggleSilentOmit,
    } from '../../recitation-animation/recitation-settings';
    import {
        loadShapedGlyphs,
        type ShapedGlyphFixture,
    } from '../../recitation-animation/shaped-glyphs';
    import { accentVarText } from '../../utils/accent-override';
    import { theme$ } from '../../stores/theme.svelte';
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
    let coverage = $state<ChapterCoverage | undefined>(undefined);
    let shapedGlyphs = $state<ShapedGlyphFixture | undefined>(undefined);
    let rootH = $state(0);
    // The verse currently under the playhead + its coverage status, reported by
    // the filmstrip — drives the contextual "missing words" pill.
    let activeCell = $state<{ ayah: number; missing: CellMissing } | null>(null);
    // Surah:ayah under the playhead — drives the filmstrip bookmark button.
    // Sourced from `recitationFocus`, which TimestampsTab writes from its
    // existing per-frame tick (`focusAt(ms)`). No separate rAF needed; the
    // tab already locates the focus verse for its own use.
    const focusSurah = $derived($recitationFocus?.surah ?? 0);
    const focusAyah = $derived($recitationFocus?.ayah ?? 0);

    let section = $state<{ refresh: () => void } | undefined>(undefined);
    let filmstrip = $state<{ refresh: () => void; showFirstAyah: () => void } | undefined>(undefined);

    const config = $derived($recitationConfigStore);
    // Recitation-correct cell geometry + per-verse word fractions, rebuilt once
    // per chapter. Duration-weighted: the cell bar fills to the recited word's
    // share of the verse's spoken time. `coverage` inserts placeholder cells for
    // fully-missing verses + tags incomplete ones.
    const filmstripModel = $derived(buildFilmstripModel(units, 'duration', coverage));

    // Contextual pill: shown only while the selected/active verse is itself
    // missing words (never a standing badge). Fully-missing verses can't be
    // active (filmstrip skips them), so this only ever fires for `words`.
    const activeMissingWords = $derived(
        activeCell?.missing === 'words'
            ? (coverage?.missingWords.get(activeCell.ayah) ?? [])
            : null,
    );

    // Recitation locator over the full-coverage units — resolves the ayahKey
    // being RECITED at a time (covers re-takes), published for the footer seek
    // buttons so prev/next anchor on the actual verse, not canonical-start order.
    const sortedIntervals = $derived(buildSortedIntervals(units));
    $effect(() => {
        const u = units;
        const sorted = sortedIntervals;
        if (!u.length) {
            recitationAyahAt.set(null);
            return;
        }
        recitationAyahAt.set((ms: number): string | null => {
            const h = findActiveAt(u, sorted, ms / 1000, -1);
            return h ? (u[h.unitIdx]?.ayahKey ?? null) : null;
        });
        return () => recitationAyahAt.set(null);
    });

    const near = (a: number, b: number): boolean => Math.abs(a - b) < 0.001;
    const upcomingLabel = $derived(
        (i18n.locale,
        near(config.unreachedOpacity, 1)
            ? m.common_player_upcoming_state_full()
            : near(config.unreachedOpacity, 0)
              ? m.common_player_upcoming_state_hidden()
              : m.common_player_upcoming_state_dim()),
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
        ensureDashCovering(ms);
        dashPort.seek(ms);
        dashPort.play();
        if (!playing) {
            section?.refresh();
            filmstrip?.refresh();
        }
    }

    // Speculative prewarm on filmstrip ayah-cell hover. The hovered ayah is in
    // the CURRENT chapter (already the bound source), so a `prewarm()` warms its
    // decoder + canplay if the chapter hasn't played yet — a no-op (fast-path
    // reuse) once it has, and a no-op for VBR. Cheap to call per cell.
    function warmCurrentChapter(): void {
        void dashPort.prewarm();
    }

    // Load chapter recitation when the published reciter / surah changes.
    $effect(() => {
        if (!isPublished || !reciterSlug || !surahNum) {
            units = [];
            ayahs = [];
            coverage = undefined;
            shapedGlyphs = undefined;
            activeCell = null;
            recitationAyahs.set([]);
            return;
        }
        const slug = reciterSlug;
        const chapter = surahNum;
        const controller = new AbortController();
        void Promise.all([
            loadChapterRecitation(slug, chapter, controller.signal),
            // Shaped geometry is a teleprompter enhancement. A missing static
            // asset must not suppress the independently loaded filmstrip/cell
            // timeline; LineAnimation retains its native-text fallback.
            loadShapedGlyphs(chapter, controller.signal).catch(() => undefined),
        ])
            .then(async ([res, glyphs]) => {
                if (controller.signal.aborted) return;
                shapedGlyphs = glyphs;
                units = res?.units ?? [];
                ayahs = res?.ayahs ?? [];
                coverage = res?.coverage;
                activeCell = null;
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
                    coverage = undefined;
                    shapedGlyphs = undefined;
                    activeCell = null;
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
    <div class="now-reciting" bind:clientHeight={rootH} style={accentVarText(config.highlightColor, $theme$)}>
        <!-- Handle row: the recitation display controls flank the collapse chip.
             Left = silent policy · word/letter · upcoming-eye; right = size− · size+. Collapsing
             hides the recitation LINE *and* this settings row (only the chip
             stays); the filmstrip stays. Chevron points up when collapsed
             (expand), down when expanded (collapse). -->
        <div class="nr-handle">
            {#if activeMissingWords}
                <span
                    class="nr-missing-pill"
                    title={activeMissingWords.length
                        ? m.common_player_missing_words_list({ words: activeMissingWords.join(', ') })
                        : m.common_player_missing_words_none()}
                >{m.common_player_missing_words_pill()}</span>
            {/if}
            {#if $recitationOpen}
                <div class="nr-ctrls" role="group" aria-label={m.common_player_recitation_display_group()}>
                    <button
                        type="button" class="nr-btn nr-btn--silent"
                        aria-pressed={$recitationSilentOmit}
                        aria-label={m.common_player_silent_omit_label()}
                        title={$recitationSilentOmit
                            ? m.common_player_silent_omit_on_title()
                            : m.common_player_silent_omit_off_title()}
                        onclick={toggleSilentOmit}
                    ><ControlIcon name={$recitationSilentOmit ? 'silent-omit' : 'silent-cohighlight'} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label={m.common_player_granularity_toggle_label()}
                        title={config.granularity === 'char' ? m.common_player_granularity_char_title() : m.common_player_granularity_word_title()}
                        onclick={toggleGranularity}
                    ><ControlIcon name={granIconName(config)} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label={m.common_player_upcoming_visibility_label()}
                        title={m.common_player_upcoming_text_title({ state: upcomingLabel })}
                        onclick={cycleUpcoming}
                    ><ControlIcon name={eyeIconName(config)} size={18} /></button>
                </div>
            {/if}

            <button
                type="button"
                class="collapse-chip"
                aria-expanded={$recitationOpen}
                title={$recitationOpen ? m.common_player_collapse_line_title() : m.common_player_expand_line_title()}
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
                <div class="nr-ctrls" role="group" aria-label={m.common_player_text_size_group()}>
                    <button
                        type="button" class="nr-btn"
                        aria-label={m.common_player_size_down_label()}
                        title={m.common_player_size_down_title()}
                        disabled={config.fontSizePx <= SIZE_MIN}
                        onclick={sizeDown}
                    ><ControlIcon name="size-down" size={16} /></button>
                    <button
                        type="button" class="nr-btn"
                        aria-label={m.common_player_size_up_label()}
                        title={m.common_player_size_up_title()}
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
                {shapedGlyphs}
                omitSilentHighlights={$recitationSilentOmit}
                open={true}
                showHeader={false}
                onSeekToWord={seek}
            />
        {/if}

        {#if config.filmstripShow && filmstripModel.cells.length}
            <div class="strip-wrap">
                <div class="strip-bm" role="group" aria-label={m.common_player_filmstrip_controls_group()}>
                    {#if isTimestamps}
                        <button
                            type="button" class="strip-bm-btn" class:on={focusBookmarked}
                            disabled={!focusKey} aria-pressed={focusBookmarked}
                            title={focusBookmarked ? m.common_player_bookmark_remove_title() : m.common_player_bookmark_add_title()}
                            onclick={toggleFocusBookmark}
                        ><ControlIcon name={focusBookmarked ? 'bookmark-filled' : 'bookmark'} size={16} /></button>
                        <button
                            type="button" class="strip-bm-btn"
                            title={m.common_player_bookmarks_panel_open()} aria-label={m.common_player_bookmarks_panel_open()}
                            onclick={toggleBookmarksPanel}
                        ><ControlIcon name="bookmarks-panel" size={16} /></button>
                    {/if}
                    <button
                        type="button" class="strip-bm-btn"
                        aria-label={m.common_player_motion_toggle_label()}
                        title={config.filmstripMotion === 'snap' ? m.common_player_motion_snap_title() : m.common_player_motion_glide_title()}
                        onclick={cycleMotion}
                    ><ControlIcon name={motionIconName(config)} size={16} /></button>
                </div>
                <div class="strip-flex">
                    <AyahFilmstrip
                        bind:this={filmstrip}
                        {units}
                        model={filmstripModel}
                        durationMs={$playerContext.durationMs}
                        {getTimeMs}
                        {playing}
                        {config}
                        hoverMs={$progressHoverMs}
                        scrubMs={$progressScrubMs}
                        onSeek={seek}
                        onHoverPrewarm={warmCurrentChapter}
                        missingWordsByAyah={coverage?.missingWords}
                        onActiveCell={(info) => { activeCell = info; }}
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
    /* Contextual "missing words" pill — anchored to the handle's left edge so it
       doesn't shift the centered controls. Red-tinted; shown only while the
       active verse is incomplete. */
    .nr-missing-pill {
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        display: inline-flex;
        align-items: center;
        padding: 1px 7px;
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--state-missing-fg);
        background: var(--state-missing-bg);
        border: 1px solid var(--state-missing-border);
        border-radius: var(--r-1);
        white-space: nowrap;
        cursor: default;
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
    .nr-btn:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 1px;
    }
    .nr-btn:disabled { opacity: 0.3; cursor: not-allowed; }
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
