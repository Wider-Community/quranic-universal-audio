<script lang="ts">
    /**
     * SegmentsFooter — unified pinned-bottom bar for the Segments tab.
     *
     * Combines reciter identity + state pill + claim-actions on the left,
     * a 3×2 stacked player cluster in the centre (play · Surah · Ayah |
     * speed · auto-play · auto-scroll), and the save controls on the right.
     * Owns the `<audio>` element and the `segPort` lifecycle — the legacy
     * `SegmentsAudioControls.svelte` is removed.
     *
     * A 4px progress fill across the top of the footer tracks the
     * currently-playing segment via (segPort.currentTimeMs - playStartMs) /
     * (playEndMs - playStartMs).
     *
     * Reads tab-scoped stores directly; mutating coordination (reciter task
     * refresh, chapter load, verse jump, picker change) is bubbled to the
     * parent via events so SegmentsTab stays the single owner of the
     * reciter-task subscription and chapter/verse data fetches.
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import { get } from 'svelte/store';

    import { clickOutside } from '../../../../lib/actions/click-outside';
    import type { ReciterTask } from '../../../../lib/api/reciter-task';
    import ClaimButton from '../../../../lib/components/ClaimButton.svelte';
    import type { CombinationSelection } from '../../../../lib/components/picker/combination-picker-types';
    import CombinationPicker from '../../../../lib/components/picker/CombinationPicker.svelte';
    import SurahPopover from '../../../../lib/components/player/SurahPopover.svelte';
    import ReciterChip from '../../../../lib/components/ReciterChip.svelte';
    import Icon from '../../../../lib/icons/Icon.svelte';
    import type { IconName } from '../../../../lib/icons/index';
    import { editingMode } from '../../../../lib/stores/editing-mode';
    import type { PublicBucket } from '../../../../lib/types/public-state';
    import { LS_KEYS } from '../../../../lib/utils/constants';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';
    import { SPEEDS } from '../../../../lib/utils/speed-control';
    import { autoSaveEnabled, toggleAutoSave } from '../../stores/autosave';
    import {
        livePlayingVerse,
        segData,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        verseOptions,
    } from '../../stores/chapter';
    import { isDirtyStore } from '../../stores/dirty';
    import { historyLoadState, historyVisible } from '../../stores/history';
    import {
        autoPlayEnabled,
        autoScrollEnabled,
        continuousPlay,
        isMainAudioPlaying,
        playbackSpeed,
        playEndMs,
        playStartMs,
        segAudioElement,
        segPort,
        segPortReady,
    } from '../../stores/playback';
    import { saveButtonLabel, savePreviewVisible } from '../../stores/save';
    import { hideHistoryView, showHistoryView } from '../../utils/history/actions';
    import {
        onSegAudioEnded,
        onSegPlayClick,
        onSegTimeUpdate,
        startSegAnimation,
        stopSegAnimation,
    } from '../../utils/playback/playback';
    import { confirmSaveFromPreview, hideSavePreview, onSegSaveClick } from '../../utils/save/actions';

    export let reciterTask: ReciterTask | null = null;
    export let chipActionBusy: '' | 'unclaim' | 'mark' = '';
    export let contextName: string | null = null;
    export let contextNameAr: string | null = null;
    export let contextCountry: string | null = null;
    export let contextBucket: PublicBucket | null = null;
    export let contextRiwayah: string | null = null;
    export let contextStyle: string | null = null;

    const dispatch = createEventDispatcher<{
        reciterChange: {
            slug: string;
            name: string;
            nameAr: string | null;
            country: string | null;
            bucket: PublicBucket;
            riwayah: string;
            style: string;
        };
        chapterChange: string;
        verseJump: string;
        unclaim: void;
        markReady: void;
        claimed: void;
    }>();

    let pickerOpen = false;
    let surahOpen = false;
    let ayahOpen = false;
    let ayahFilterInput: HTMLInputElement | null = null;
    let ayahQuery = '';
    let footerEl: HTMLDivElement | null = null;
    let audioEl: HTMLAudioElement | null = null;

    // Local mirror of `segPort.currentTimeMs()` so the progress bar can
    // be reactive without polling. Written by the onTimeUpdate
    // subscription mounted below.
    let currentMs = 0;

    // ResizeObserver + port-subscription handles live at module scope so
    // the unified teardown in `onMount`'s return can reach them.
    let footerResizeObs: ResizeObserver | null = null;
    let playbackUnsubs: Array<() => void> = [];

    onMount(() => {
        // -------------------------------------------------------------
        // Footer height publication — drives the segments panel's
        // padding-bottom so the list never hides under a taller-than-
        // default footer (the stacked player makes it ~108px).
        // -------------------------------------------------------------
        if (footerEl) {
            const apply = (): void => {
                if (!footerEl) return;
                document.documentElement.style.setProperty(
                    '--seg-footer-actual-h',
                    `${footerEl.offsetHeight}px`,
                );
            };
            apply();
            footerResizeObs = new ResizeObserver(apply);
            footerResizeObs.observe(footerEl);
        }

        // -------------------------------------------------------------
        // <audio> element + segPort wiring (moved from the deleted
        // SegmentsAudioControls.svelte). Seed `playbackSpeed` from
        // localStorage so a 1.25× session persists across reloads.
        // -------------------------------------------------------------
        const stored = localStorage.getItem(LS_KEYS.SEG_SPEED);
        if (stored) {
            const v = parseFloat(stored);
            if (!Number.isNaN(v)) playbackSpeed.set(v);
        }

        if (audioEl) {
            // Legacy mirror — still read by a handful of utils. Cleared in
            // teardown below to keep `get(segAudioElement)` accurate.
            segAudioElement.set(audioEl);
            segPort.attachElement(audioEl);
            segPortReady.set(true);
            playbackUnsubs = [
                segPort.onPlay(startSegAnimation),
                segPort.onPause(stopSegAnimation),
                segPort.onEnded(onSegAudioEnded),
                segPort.onTimeUpdate((fileMs) => {
                    currentMs = fileMs;
                    onSegTimeUpdate(fileMs);
                }),
            ];
        }

        return () => {
            footerResizeObs?.disconnect();
            footerResizeObs = null;
            document.documentElement.style.removeProperty('--seg-footer-actual-h');
            for (const off of playbackUnsubs) off();
            playbackUnsubs = [];
            segPort.attachElement(null);
            segPortReady.set(false);
            segAudioElement.set(null);
        };
    });

    // Seed `segPort.playbackRate` on first ready transition. Reading the
    // port's playbackRate gates the write to once per session — avoids
    // racing with the per-keystroke speed cycle. (Same pattern that lived
    // in SegmentsAudioControls.)
    $: if ($segPortReady && segPort.playbackRate === 1 && $playbackSpeed !== 1) {
        segPort.setPlaybackRate($playbackSpeed);
    }

    $: hasReciter = !!$selectedReciter;
    $: chipMeta = [titleCaseSlug(contextRiwayah), titleCaseSlug(contextStyle)]
        .filter(Boolean)
        .join(' · ');

    // Full 1..114 range — surah availability per reciter would tighten this
    // later if we surface per-reciter chapter manifests in the catalog.
    const allSurahs: number[] = Array.from({ length: 114 }, (_, i) => i + 1);

    $: filteredAyahs = ayahQuery.trim()
        ? $verseOptions.filter((v) => String(v).startsWith(ayahQuery.trim()))
        : $verseOptions;

    $: historyButtonLabel = $historyVisible
        ? 'Back'
        : $historyLoadState === 'loading'
            ? 'History…'
            : 'History';

    // ---- Progress bar -----------------------------------------------
    // % through the currently-playing segment. Falls back to 0 when no
    // range is queued (`playStartMs` and `playEndMs` are both 0 between
    // plays). Reactive on `currentMs` so the rAF-driven onTimeUpdate
    // subscriber drives the fill.
    $: progressPct = (() => {
        const range = $playEndMs - $playStartMs;
        if (range <= 0) return 0;
        const pct = ((currentMs - $playStartMs) / range) * 100;
        return Math.max(0, Math.min(100, pct));
    })();

    $: progressVisible = $playEndMs > 0 && $playStartMs >= 0;

    // ---- Live verse tracking ----------------------------------------
    // The Surah/Ayah cells light up accent-coloured while playback is
    // in flight. Comparing against the *current* selection rather than
    // mutating it preserves the user's manual filter when they jump
    // ahead via the picker (`selectedVerse` and `livePlayingVerse` then
    // diverge — both are visible: the user's pick on the chrome, the
    // playing verse in accent).
    $: surahLive = !!$livePlayingVerse && $isMainAudioPlaying;
    $: ayahLive = surahLive && String($livePlayingVerse?.verse ?? '') === $selectedVerse;

    // ---- Player handlers --------------------------------------------
    function handlePlayClick(): void {
        onSegPlayClick();
    }

    function handleAutoPlayToggle(): void {
        const next = !get(autoPlayEnabled);
        autoPlayEnabled.set(next);
        continuousPlay.set(next);
        localStorage.setItem(LS_KEYS.SEG_AUTOPLAY, String(next));
    }

    function handleAutoScrollToggle(): void {
        const next = !get(autoScrollEnabled);
        autoScrollEnabled.set(next);
        localStorage.setItem(LS_KEYS.SEG_AUTOSCROLL, String(next));
    }

    function cyclePlaybackSpeed(): void {
        const cur = get(playbackSpeed);
        const curIdx = SPEEDS.findIndex((s) => Math.abs(s - cur) < 0.01);
        const idx = curIdx === -1 ? SPEEDS.indexOf(1) : curIdx;
        const next = SPEEDS[(idx + 1) % SPEEDS.length] ?? 1;
        playbackSpeed.set(next);
        localStorage.setItem(LS_KEYS.SEG_SPEED, String(next));
        segPort.setPlaybackRate(next);
    }

    function onProgressClick(ev: MouseEvent): void {
        // Seek within the current segment by clicking the progress bar.
        // Does NOT cross segment boundaries — AudioRange owns that — so
        // a click outside the playing range is clamped to the end.
        if ($playEndMs <= $playStartMs || !$segPortReady) return;
        const target = ev.currentTarget as HTMLElement;
        const rect = target.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (ev.clientX - rect.left) / rect.width));
        const seekMs = $playStartMs + pct * ($playEndMs - $playStartMs);
        segPort.seek(seekMs);
    }

    function onProgressKey(ev: KeyboardEvent): void {
        // Arrow keys nudge the playhead within the segment in 2% steps —
        // the slider exists for finegrained inspection, not full transport.
        if ($playEndMs <= $playStartMs || !$segPortReady) return;
        const range = $playEndMs - $playStartMs;
        const step = range * 0.02;
        if (ev.key === 'ArrowLeft') {
            ev.preventDefault();
            segPort.seek(Math.max($playStartMs, segPort.currentTimeMs() - step));
        } else if (ev.key === 'ArrowRight') {
            ev.preventDefault();
            segPort.seek(Math.min($playEndMs - 1, segPort.currentTimeMs() + step));
        }
    }

    // ---- Picker / event handlers (unchanged from prior footer) ------
    function onPickerSelect(ev: CustomEvent<CombinationSelection>): void {
        const { reciter, delivery } = ev.detail;
        dispatch('reciterChange', {
            slug: delivery.slug,
            name: reciter.name,
            nameAr: reciter.name_ar ?? null,
            country: reciter.country ?? null,
            bucket: delivery.bucket,
            riwayah: delivery.riwayah,
            style: delivery.style,
        });
        pickerOpen = false;
    }

    function onSurahPick(ev: CustomEvent<number>): void {
        surahOpen = false;
        dispatch('chapterChange', String(ev.detail));
    }

    async function openAyah(): Promise<void> {
        if (!$selectedChapter) return;
        ayahQuery = '';
        ayahOpen = true;
        await tick();
        ayahFilterInput?.focus();
    }

    function onAyahPick(v: number): void {
        ayahOpen = false;
        dispatch('verseJump', String(v));
    }

    function onAyahKey(ev: KeyboardEvent): void {
        if (ev.key === 'Enter' && filteredAyahs.length > 0) {
            onAyahPick(filteredAyahs[0]!);
        }
    }

    function onUnclaim(): void {
        if (chipActionBusy) return;
        dispatch('unclaim');
    }
    function onMarkReady(): void {
        if (chipActionBusy) return;
        dispatch('markReady');
    }
    function onClaimed(): void {
        dispatch('claimed');
    }

    function toggleHistory(): void {
        if ($historyVisible) hideHistoryView();
        else showHistoryView();
    }

    $: writeable = $editingMode.kind !== 'view';
    $: showSavePreview = $savePreviewVisible;
    $: saveDisabled = $autoSaveEnabled || !$isDirtyStore;
    $: saveLabel = $isDirtyStore
        ? ($autoSaveEnabled && get(saveButtonLabel) === 'Save' ? 'Saving…' : $saveButtonLabel)
        : 'Saved';

    // Play button glyph: pause when actively playing, play otherwise.
    $: playGlyph = ($isMainAudioPlaying ? 'pause' : 'play') as IconName;
</script>

<div class="segs-footer" class:is-empty={!hasReciter} bind:this={footerEl}>
    <div
        class="progress"
        class:active={progressVisible}
        on:click={onProgressClick}
        on:keydown={onProgressKey}
        role="slider"
        tabindex="0"
        aria-label="Segment playback progress"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={Math.round(progressPct)}
    >
        <div class="fill" style:width="{progressPct}%"></div>
    </div>

    <div class="row">
        <div class="zone zone-identity">
            <button
                type="button"
                class="identity"
                class:placeholder={!hasReciter}
                on:click={() => (pickerOpen = true)}
                aria-haspopup="dialog"
                title={hasReciter ? 'Switch reciter' : 'Pick a reciter'}
            >
                {#if hasReciter && contextName}
                    <ReciterChip
                        name={contextName}
                        nameAr={contextNameAr}
                        country={contextCountry}
                        subline={chipMeta || null}
                        bucket={contextBucket}
                        switchable={true}
                    />
                {:else}
                    <span class="identity-placeholder-label">Pick a reciter</span>
                    <span class="identity-switch" aria-hidden="true">⇄</span>
                {/if}
            </button>

            {#if hasReciter && !showSavePreview}
                <div class="reciter-actions">
                    <ClaimButton
                        slug={$selectedReciter || ''}
                        task={reciterTask}
                        onClaimed={onClaimed}
                    />
                    {#if reciterTask?.predicates.can_mark_ready}
                        <button
                            type="button"
                            class="action ghost-accent"
                            disabled={chipActionBusy !== ''}
                            title="Mark this reciter ready for a maintainer to publish"
                            on:click={onMarkReady}
                        >Mark ready</button>
                    {/if}
                    {#if reciterTask?.predicates.can_release}
                        <button
                            type="button"
                            class="action ghost"
                            disabled={chipActionBusy !== ''}
                            on:click={onUnclaim}
                        >Unclaim</button>
                    {/if}
                </div>
            {/if}
        </div>

        {#if hasReciter}
            <div
                class="zone zone-location"
                use:clickOutside={() => { surahOpen = false; ayahOpen = false; }}
            >
                <div class="player-row">
                    <button
                        type="button"
                        class="speed-cell"
                        class:boosted={$playbackSpeed !== 1}
                        on:click={cyclePlaybackSpeed}
                        title="Playback speed (click to cycle)"
                        aria-label="Playback speed {$playbackSpeed}×"
                    >{$playbackSpeed}×</button>

                    <button
                        type="button"
                        class="pref-cell"
                        class:on={$autoPlayEnabled}
                        aria-pressed={$autoPlayEnabled}
                        title="Auto-play next segment when current ends"
                        on:click={handleAutoPlayToggle}
                    >
                        <Icon name="autoplay" size={16} />
                    </button>

                    <button
                        type="button"
                        class="pref-cell"
                        class:on={$autoScrollEnabled}
                        aria-pressed={$autoScrollEnabled}
                        title="Auto-scroll the list to follow the playing segment"
                        on:click={handleAutoScrollToggle}
                    >
                        <Icon name="autoscroll" size={16} />
                    </button>

                    <button
                        type="button"
                        class="play-cell"
                        disabled={!$segPortReady || !$segData?.audio_url}
                        on:click={handlePlayClick}
                        aria-label={$isMainAudioPlaying ? 'Pause' : 'Play'}
                    >
                        <Icon name={playGlyph} size={14} />
                    </button>

                    <button
                        type="button"
                        class="loc-cell"
                        class:has-value={!!$selectedChapter}
                        class:live={surahLive}
                        on:click={() => { surahOpen = !surahOpen; ayahOpen = false; }}
                        aria-haspopup="dialog"
                        aria-expanded={surahOpen}
                    >
                        <span class="loc-label">Surah</span>
                        {#if $selectedChapter}
                            <span class="loc-value">{$selectedChapter}</span>
                        {:else}
                            <span class="loc-empty">—</span>
                        {/if}
                        <Icon name="caret-down" size={10} />
                    </button>

                    <button
                        type="button"
                        class="loc-cell"
                        class:has-value={!!$selectedVerse}
                        class:live={ayahLive}
                        disabled={!$selectedChapter}
                        on:click={openAyah}
                        aria-haspopup="dialog"
                        aria-expanded={ayahOpen}
                    >
                        <span class="loc-label">Ayah</span>
                        {#if $selectedVerse}
                            <span class="loc-value">{$selectedVerse}</span>
                        {:else}
                            <span class="loc-empty">all</span>
                        {/if}
                        <Icon name="caret-down" size={10} />
                    </button>
                </div>

                {#if surahOpen}
                    <div class="pop pop-surah">
                        <SurahPopover
                            surahNums={allSurahs}
                            value={$selectedChapter ? parseInt($selectedChapter) : null}
                            on:change={onSurahPick}
                        />
                    </div>
                {/if}

                {#if ayahOpen}
                    <div class="pop pop-ayah" role="dialog" aria-label="Ayah picker">
                        <input
                            bind:this={ayahFilterInput}
                            bind:value={ayahQuery}
                            on:keydown={onAyahKey}
                            class="ayah-search"
                            type="text"
                            inputmode="numeric"
                            placeholder="Jump to ayah…"
                            autocomplete="off"
                        />
                        <div class="ayah-grid" role="listbox">
                            {#each filteredAyahs as v (v)}
                                <button
                                    type="button"
                                    class="ayah-cell"
                                    class:active={String(v) === $selectedVerse}
                                    role="option"
                                    aria-selected={String(v) === $selectedVerse}
                                    on:click={() => onAyahPick(v)}
                                >{v}</button>
                            {:else}
                                <div class="empty">No matches</div>
                            {/each}
                        </div>
                    </div>
                {/if}
            </div>
        {:else}
            <div class="zone zone-location empty-spacer" aria-hidden="true"></div>
        {/if}

        <div class="zone zone-save">
            {#if hasReciter}
                {#if showSavePreview}
                    <button class="action ghost" on:click={() => hideSavePreview()}>Cancel</button>
                    <button class="action primary" on:click={confirmSaveFromPreview}>Confirm save</button>
                {:else}
                    <button
                        type="button"
                        class="utility"
                        class:on={$historyVisible}
                        title={$historyVisible ? 'Back to segments' : 'History'}
                        aria-label={historyButtonLabel}
                        on:click={toggleHistory}
                    >
                        {#if $historyVisible}
                            <Icon name="arrow-left" size={14} />
                            <span class="util-label">Back</span>
                        {:else}
                            <Icon name="history" size={14} />
                            <span class="util-label">History</span>
                        {/if}
                    </button>

                    {#if writeable}
                        <div class="save-group">
                            <button
                                type="button"
                                class="autosave-toggle"
                                class:on={$autoSaveEnabled}
                                aria-pressed={$autoSaveEnabled}
                                title={$autoSaveEnabled ? 'Auto-save on — click to disable' : 'Auto-save off — click to enable'}
                                on:click={() => toggleAutoSave(!$autoSaveEnabled)}
                            >
                                <Icon name="bolt" size={12} />
                                <span>Auto</span>
                            </button>

                            <button
                                type="button"
                                class="action save"
                                class:primary={$isDirtyStore && !$autoSaveEnabled}
                                class:saved={!$isDirtyStore}
                                class:auto-busy={$autoSaveEnabled && $isDirtyStore}
                                disabled={saveDisabled}
                                on:click={onSegSaveClick}
                            >
                                {#if !$isDirtyStore}
                                    <span class="save-glyph" aria-hidden="true">✓</span>
                                    <span>Saved</span>
                                {:else if $autoSaveEnabled}
                                    <span class="save-pulse" aria-hidden="true"></span>
                                    <span>Auto-saving…</span>
                                {:else}
                                    <span>{saveLabel}</span>
                                {/if}
                            </button>
                        </div>
                    {/if}
                {/if}
            {/if}
        </div>
    </div>

    <audio bind:this={audioEl} preload="none"></audio>
</div>

{#if pickerOpen}
    <CombinationPicker
        open={pickerOpen}
        title="Switch reciter"
        on:select={onPickerSelect}
        on:close={() => (pickerOpen = false)}
    />
{/if}

<style>
    .segs-footer {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        z-index: 100;
        display: flex;
        flex-direction: column;
        min-height: var(--seg-footer-h, 72px);
        background: var(--panel);
        border-top: 1px solid var(--border-default);
        box-shadow: 0 -8px 24px oklch(0 0 0 / 0.28);
    }

    /* The <audio> element is the source of all playback DOM events. It
       has no visual representation; hidden via display:none keeps the
       intrinsic 0×0 size from contributing to the footer height. */
    audio { display: none; }

    /* Progress fill: 3px hairline at the very top. Visible only when a
       segment range is queued (`active` class). The fill width is set
       inline via `style:width="{pct}%"` so the rAF-driven onTimeUpdate
       subscriber repaints without an animation step. */
    .progress {
        position: relative;
        height: 3px;
        background: var(--canvas-inset);
        cursor: pointer;
        flex-shrink: 0;
    }
    .progress .fill {
        position: absolute;
        inset: 0 auto 0 0;
        background: var(--accent);
        width: 0;
        transition: width 80ms linear;
    }
    .progress:not(.active) .fill { opacity: 0; }

    .row {
        position: relative;
        flex: 1;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-4);
    }

    /* Location (player cluster) is pinned to the true viewport
       horizontal center, decoupled from the side zones' widths. */
    .zone-location {
        position: absolute;
        left: 50%;
        top: 50%;
        transform: translate(-50%, -50%);
    }

    .zone {
        min-width: 0;
        display: flex;
        align-items: center;
    }
    .zone-identity {
        justify-content: flex-start;
        gap: var(--s-3);
        flex-wrap: nowrap;
    }
    .zone-location {
        justify-content: center;
        gap: var(--s-2);
    }
    .zone-save {
        justify-content: flex-end;
        gap: var(--s-2);
        flex-wrap: wrap;
    }
    .empty-spacer { display: none; }

    .reciter-actions {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        flex: 0 0 auto;
    }
    .save-group {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }

    /* ---------- Identity (chip wrapper) ----------
       The interactive button hosts the shared `<ReciterChip>` body.
       Padding + border + hover state live here so the chip itself
       stays presentation-only and can be reused inside non-button
       contexts (catalog rows, dashboard meta). */
    .identity {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        max-width: 100%;
        min-width: 0;
        flex: 0 1 auto;
        padding: 5px var(--s-3) 5px 5px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: inherit;
        cursor: pointer;
        font: inherit;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .identity:hover { border-color: var(--border-strong); background: var(--panel); }
    .identity:focus-visible { outline: none; border-color: var(--accent); }
    .identity.placeholder {
        background: var(--accent-tint-soft);
        border-color: oklch(0.785 0.130 220 / 0.35);
        color: var(--accent);
        padding: 8px var(--s-3);
        gap: var(--s-2);
    }
    .identity.placeholder:hover { background: var(--accent-tint); }

    .identity-placeholder-label {
        font-size: var(--fs-row);
        font-weight: 600;
        color: inherit;
        padding-inline-start: var(--s-2);
    }
    .identity-switch {
        margin-inline-start: var(--s-2);
        color: var(--text-faint);
        font-size: var(--fs-meta);
        transition: color var(--t-fast);
    }
    .identity:hover .identity-switch { color: var(--text-secondary); }
    .identity.placeholder .identity-switch { color: var(--accent); }

    /* ---------- Player row (single-row, container-less) ----------
       Reading order, left-to-right:
         speed pill · auto-play · auto-scroll · ▶ play · Surah · Ayah
       The play button is the only accent-filled element; everything
       else is naked text or icon, no surrounding pill. The cluster
       sits viewport-centered (zone-location's absolute positioning). */
    .player-row {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }

    .player-row > button {
        border: 0;
        background: transparent;
        color: var(--text-secondary);
        border-radius: var(--r-2);
        font-family: var(--font-sans);
        font-size: var(--fs-meta);
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 0;
        transition: background var(--t-fast), color var(--t-fast);
        min-width: 0;
    }
    .player-row > button:hover:not(:disabled) {
        color: var(--text-primary);
    }
    .player-row > button:disabled { opacity: 0.35; cursor: not-allowed; }

    /* Play — the only accent-filled element. Round, slightly larger
       than the icon prefs so it reads as the primary action. */
    .player-row .play-cell {
        background: var(--accent);
        color: var(--accent-fg);
        border-radius: 50%;
        width: 30px;
        height: 30px;
        margin: 0 var(--s-1);
    }
    .player-row .play-cell:hover:not(:disabled) {
        background: var(--accent-strong);
        color: var(--accent-fg);
    }

    /* Pref toggles (auto-play / auto-scroll) — naked square icon
       buttons. Active state tints the icon accent; no background. */
    .player-row .pref-cell {
        width: 26px;
        height: 26px;
        color: var(--text-muted);
    }
    .player-row .pref-cell:hover:not(:disabled) {
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .player-row .pref-cell.on {
        color: var(--accent);
    }
    .player-row .pref-cell.on:hover:not(:disabled) {
        color: var(--accent-strong);
        background: var(--accent-tint);
    }

    /* Speed — text pill, slightly subdued. Goes accent when boosted. */
    .player-row .speed-cell {
        height: 26px;
        padding: 0 7px;
        font-family: var(--font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        color: var(--text-muted);
    }
    .player-row .speed-cell:hover:not(:disabled) {
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .player-row .speed-cell.boosted {
        color: var(--accent);
    }
    .player-row .speed-cell.boosted:hover:not(:disabled) {
        color: var(--accent-strong);
        background: var(--accent-tint);
    }

    /* Location triggers (Surah / Ayah) — text + small caret. Subtle
       outline only on hover; accent tint when the playing segment
       advances past their boundary. */
    .player-row .loc-cell {
        gap: 5px;
        height: 28px;
        padding: 0 8px;
        color: var(--text-secondary);
        font-size: var(--fs-meta);
    }
    /* Label and value share the button's color so the cell reads as one
       unit ("Surah 1"), and so the live-state accent flip recolours both
       spans together without per-span overrides. */
    .player-row .loc-cell .loc-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.07em;
    }
    .player-row .loc-cell .loc-value {
        font-family: var(--font-mono);
        font-size: 11.5px;
        font-variant-numeric: tabular-nums;
    }
    .player-row .loc-cell .loc-empty {
        font-style: italic;
        font-size: 10.5px;
        opacity: 0.65;
    }
    .player-row .loc-cell:hover:not(:disabled) {
        background: var(--panel-2);
        color: var(--text-primary);
    }
    .player-row .loc-cell.has-value { color: var(--text-primary); }
    .player-row .loc-cell.live { color: var(--accent); }

    .pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        padding: var(--s-2);
        z-index: 50;
    }
    /* Clip the surah popover to the player-stack row width (38 + 96 + 96
     * + 4*2 gaps = 238px) so the dropup never sprawls beyond the row it
     * anchors to. The inner SurahPopover is width:100% and clamps to it. */
    .pop-surah {
        left: 50%;
        transform: translateX(-50%);
        width: 238px;
    }
    .pop-ayah {
        left: 50%;
        transform: translateX(-50%);
        width: min(360px, calc(100vw - var(--s-4) * 2));
        display: flex;
        flex-direction: column;
        max-height: min(420px, 60vh);
    }

    .ayah-search {
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        color: var(--text-primary);
        padding: 6px var(--s-2);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        outline: none;
        margin-bottom: var(--s-2);
    }
    .ayah-search:focus { border-color: var(--accent); }
    .ayah-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(44px, 1fr));
        gap: 4px;
        overflow-y: auto;
    }
    .ayah-cell {
        padding: 6px 0;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        font-size: var(--fs-meta);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .ayah-cell:hover {
        border-color: var(--border-strong);
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .ayah-cell.active {
        border-color: var(--accent);
        color: var(--accent);
        background: var(--accent-tint);
    }
    .empty {
        grid-column: 1 / -1;
        padding: var(--s-3);
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }

    /* ---------- Actions ---------- */
    .action {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        transition: background var(--t-fast), border-color var(--t-fast), color var(--t-fast);
    }
    .action:hover:not(:disabled) {
        background: var(--panel);
        border-color: var(--border-strong);
    }
    .action:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    .action.ghost {
        background: transparent;
        color: var(--text-secondary);
    }
    .action.ghost:hover:not(:disabled) {
        background: var(--panel-2);
        color: var(--text-primary);
    }
    .action.ghost-accent {
        background: transparent;
        color: var(--accent);
        border-color: oklch(0.785 0.130 220 / 0.35);
    }
    .action.ghost-accent:hover:not(:disabled) {
        background: var(--accent-tint);
        border-color: var(--accent);
    }
    .action.primary {
        background: var(--accent);
        border-color: var(--accent);
        color: var(--accent-fg);
        font-weight: 500;
    }
    .action.primary:hover:not(:disabled) {
        background: var(--accent-strong);
        border-color: var(--accent-strong);
    }

    .action.save { min-width: 104px; justify-content: center; padding-inline: var(--s-3); }
    .action.save.saved {
        background: transparent;
        border-color: var(--border-quiet);
        color: var(--text-muted);
    }
    .save-glyph { color: oklch(0.78 0.13 155); font-weight: 600; }
    .action.save.auto-busy {
        background: transparent;
        border-color: oklch(0.785 0.130 220 / 0.35);
        color: var(--accent);
    }
    .save-pulse {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
        animation: pulse 1.4s ease-out-quart infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 0.35; }
        50% { opacity: 1; }
    }

    .autosave-toggle {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: transparent;
        border: 1px dashed var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-muted);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .autosave-toggle:hover {
        color: var(--text-primary);
        border-color: var(--border-strong);
    }
    .autosave-toggle.on {
        border-style: solid;
        border-color: oklch(0.785 0.130 220 / 0.45);
        background: var(--accent-tint);
        color: var(--accent);
    }

    .utility {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px var(--s-2);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        color: var(--text-muted);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        transition: color var(--t-fast), background var(--t-fast), border-color var(--t-fast);
    }
    .utility:hover {
        color: var(--text-primary);
        background: var(--panel-2);
        border-color: var(--border-quiet);
    }
    .utility.on {
        color: var(--accent);
        background: var(--accent-tint);
        border-color: oklch(0.785 0.130 220 / 0.35);
    }

    /* ---------- Responsive ---------- */
    @media (max-width: 960px) {
        .row {
            flex-direction: column;
            align-items: stretch;
            gap: var(--s-2);
            padding: var(--s-2) var(--s-3);
        }
        /* Return location to in-flow stacking — absolute positioning would
           collapse it on top of the identity row at narrow widths. */
        .zone-location {
            position: static;
            transform: none;
            justify-content: flex-start;
        }
        .zone-save { justify-content: flex-start; }
        .pop-surah, .pop-ayah {
            left: 0;
            right: 0;
            transform: none;
            width: auto;
        }
    }
    @media (max-width: 540px) {
        .util-label { display: none; }
        .action.save { min-width: 92px; }
    }
</style>
