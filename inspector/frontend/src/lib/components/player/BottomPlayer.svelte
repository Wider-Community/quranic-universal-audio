<script lang="ts">
    /**
     * Dashboard-scoped persistent BottomPlayer.
     *
     * Pinned to the viewport bottom while the Dashboard tab is active.
     * The App-shell `hidden` cascade hides it when the Dashboard tab is
     * inactive (transport keeps its position; explicit play required on
     * tab return).
     *
     * Owns the dashPort, binds the <audio> element, subscribes to
     * player-context for source changes, drives controls via dashPort,
     * and updates positionMs / isPlaying via port event subscriptions.
     */
    import { onDestroy, onMount } from 'svelte';

    import { clickOutside } from '../../actions/click-outside';
    import { fetchSurahsForDelivery, type SurahEntry } from '../../api/audio-surahs';
    import { ensureAudioContextRunning } from '../../playback/audio-graph';
    import { dashPort } from '../../playback/dash-port';
    import {
        loadPersistedSlice,
        persistSlice,
        playerContext,
        setDuration,
        setIsLoading,
        setIsPlaying,
        setPosition,
        setSpeed,
        setSurah,
    } from '../../stores/player-context';
    import type { PublicDelivery } from '../../types/public-state';
    import { DASHBOARD_SPEEDS } from '../../utils/speed-control';
    import PlayerControls from './PlayerControls.svelte';
    import PlayerMetaChip from './PlayerMetaChip.svelte';
    import PlayerProgress from './PlayerProgress.svelte';
    import SurahPopover from './SurahPopover.svelte';

    let audioEl: HTMLAudioElement | null = null;
    let urls: Record<string, SurahEntry> = {};
    let lastDeliverySlug: string | null = null;
    let lastSurahNum: number | null = null;
    let surahPopoverOpen = false;

    onMount(() => {
        dashPort.attachElement(audioEl);
        const slice = loadPersistedSlice();
        if (slice.speed && slice.speed !== 1) setSpeed(slice.speed);
        dashPort.setPlaybackRate(slice.speed);

        const unsubPlay = dashPort.onPlay(() => setIsPlaying(true));
        const unsubPause = dashPort.onPause(() => setIsPlaying(false));
        const unsubLoad = dashPort.onLoad(() => {
            const dur = audioEl?.duration ?? 0;
            setPosition(0, Number.isFinite(dur) ? dur * 1000 : 0);
            // Swap-complete (canplay): if the user wasn't already in a
            // mid-play buffering stall, this is the moment audio is ready
            // to start. Clear the ring; `playing` will also clear it on
            // the actual audible start as a safety net.
            setIsLoading(false);
        });
        const unsubTime = dashPort.onTimeUpdate((fileMs) => {
            setPosition(fileMs, audioEl?.duration ? audioEl.duration * 1000 : undefined);
        });
        const unsubWaiting = dashPort.onWaiting(() => setIsLoading(true));
        const unsubPlaying = dashPort.onPlaying(() => setIsLoading(false));

        return () => {
            unsubPlay();
            unsubPause();
            unsubLoad();
            unsubTime();
            unsubWaiting();
            unsubPlaying();
            dashPort.attachElement(null);
        };
    });

    onDestroy(() => {
        dashPort.pause();
    });

    $: void reactToContext($playerContext);

    async function reactToContext(ctx: typeof $playerContext): Promise<void> {
        const delivery = ctx.delivery;
        const surahNum = ctx.surahNum;
        if (!delivery || surahNum === null) {
            if (lastDeliverySlug !== null) {
                dashPort.setSource(null);
                lastDeliverySlug = null;
                lastSurahNum = null;
                urls = {};
            }
            return;
        }
        const wasPlaying = ctx.isPlaying;
        const deliverySwitched = delivery.slug !== lastDeliverySlug;
        // True only when switching away from an already-loaded combination
        // (not on initial load from null). Used to auto-play on paused switch.
        const isActiveCombinationSwitch = deliverySwitched && lastDeliverySlug !== null;

        if (deliverySwitched) {
            try {
                urls = await fetchSurahsForDelivery(delivery.source, delivery.slug);
            } catch {
                urls = {};
            }
            lastDeliverySlug = delivery.slug;
            persistSlice({
                deliverySlug: delivery.slug,
                surahNum,
                speed: ctx.speed,
            });
        }

        // Fallback: this combo may not carry the currently-selected surah
        // (default 1 when entering a reciter for the first time, or the
        // user's prior pick carried across a reciter switch). Pick the
        // first available chapter and re-enter via setSurah — the store
        // change retriggers this function with a valid surahNum.
        if (!urls[String(surahNum)]) {
            const available = Object.keys(urls)
                .map(Number)
                .filter(Number.isFinite)
                .sort((a, b) => a - b);
            if (available.length > 0 && available[0] !== surahNum) {
                setSurah(available[0]!);
                return;
            }
        }

        if (surahNum !== lastSurahNum || deliverySwitched) {
            // Stop the previous chapter immediately. Without this, the
            // old MP3 keeps playing until _swapTo writes el.src for the
            // new source — audible as a chunk of the wrong reciter when
            // the user changes combination mid-playback. setIsPlaying(false)
            // flips the glyph to ▶ for the duration of the load (re-flips
            // to ⏸ when `playing` fires on the new source if wasPlaying or
            // isActiveCombinationSwitch).
            if (wasPlaying || isActiveCombinationSwitch) {
                dashPort.pause();
                setIsPlaying(false);
            }
            const entry = urls[String(surahNum)];
            if (entry) {
                const url = entry.url;
                if (entry.via === 'qf_api') {
                    console.log(
                        '[qf-audio] ▶ routed via Quran.Foundation API:',
                        url,
                        '— overrides our link:',
                        entry.originUrl,
                    );
                } else if (entry.via === 'qf_fallback') {
                    console.warn('[qf-audio] API unavailable — using our CDN link:', url);
                }
                const cbrSrc = url.startsWith('/api/')
                    ? url
                    : `/api/seg/audio-proxy/${delivery.slug}?url=${encodeURIComponent(url)}`;
                dashPort.setSource({ audioUrl: url, cbrSrc, reciter: delivery.slug, vbr: false });
                // Seed duration from the manifest so the progress bar shows
                // total length before <audio> fetches MP3 headers (which
                // doesn't happen until play with preload="none").
                if (entry.durationMs && entry.durationMs > 0) {
                    setDuration(entry.durationMs);
                }
                if (wasPlaying || isActiveCombinationSwitch) {
                    setIsLoading(true);
                    await ensureAudioContextRunning();
                    dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
                    dashPort.play();
                }
            }
            lastSurahNum = surahNum;
        }
    }

    async function togglePlay(): Promise<void> {
        if ($playerContext.isPlaying) {
            dashPort.pause();
            return;
        }
        await ensureAudioContextRunning();
        // preload="none" means the element has no buffered media until
        // loadCovering points it at the proxy URL. Browsers ignore play()
        // when src is empty, so we ensure coverage first.
        if (dashPort.source) {
            dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
        }
        // If the element isn't yet at HAVE_FUTURE_DATA (readyState >= 3),
        // play() will be queued until canplay fires. Surface that as a
        // loading state so the user sees the ring instead of an instant
        // pause icon with no audio.
        if (audioEl && audioEl.readyState < 3) {
            setIsLoading(true);
        }
        dashPort.play();
    }

    function seekBack(): void {
        dashPort.seek(Math.max(0, dashPort.currentTimeMs() - 15_000));
    }
    function seekForward(): void {
        dashPort.seek(dashPort.currentTimeMs() + 15_000);
    }

    function prevSurah(): void {
        const ctx = $playerContext;
        if (ctx.surahNum === null) return;
        const idx = surahNums.indexOf(ctx.surahNum);
        if (idx > 0) setSurah(surahNums[idx - 1]!);
    }
    function nextSurah(): void {
        const ctx = $playerContext;
        if (ctx.surahNum === null) return;
        const idx = surahNums.indexOf(ctx.surahNum);
        if (idx >= 0 && idx < surahNums.length - 1) setSurah(surahNums[idx + 1]!);
    }

    function onSurahChange(ev: CustomEvent<number>): void {
        setSurah(ev.detail);
        surahPopoverOpen = false;
    }

    function onSpeedChange(rate: number): void {
        setSpeed(rate);
        dashPort.setPlaybackRate(rate);
        persistSlice({
            deliverySlug: lastDeliverySlug,
            surahNum: lastSurahNum,
            speed: rate,
        });
    }

    function cycleSpeed(): void {
        const cur = $playerContext.speed;
        const idx = DASHBOARD_SPEEDS.findIndex((s) => Math.abs(s - cur) < 0.01);
        const next = DASHBOARD_SPEEDS[(idx + 1) % DASHBOARD_SPEEDS.length] ?? 1;
        onSpeedChange(next);
    }

    /**
     * Download the current chapter, delegating entirely to the browser's
     * download manager — a transient <a download> click, no fetch/blob.
     * Targets the real CDN file (entry.originUrl when routed via QF, else
     * entry.url) through the same-origin audio-proxy with `download=1`, which
     * adds `Content-Disposition: attachment` so the response saves instead of
     * streaming inline.
     */
    function downloadSurah(): void {
        const ctx = $playerContext;
        const delivery = ctx.delivery;
        const surahNum = ctx.surahNum;
        if (!delivery || surahNum === null) return;
        const entry = urls[String(surahNum)];
        if (!entry) return;

        const cdnUrl = entry.originUrl ?? entry.url;
        const filename = `${delivery.slug}-${String(surahNum).padStart(3, '0')}.mp3`;
        const href = cdnUrl.startsWith('/api/')
            ? cdnUrl
            : `/api/seg/audio-proxy/${delivery.slug}`
              + `?url=${encodeURIComponent(cdnUrl)}&download=1&chapter=${surahNum}`;

        const a = document.createElement('a');
        a.href = href;
        a.download = filename;
        a.rel = 'noopener';
        document.body.appendChild(a);
        a.click();
        a.remove();
    }

    function onSeekFromBar(ev: CustomEvent<number>): void {
        dashPort.seek(ev.detail);
    }

    function onCombinationSelect(ev: CustomEvent<PublicDelivery>): void {
        const d = ev.detail;
        playerContext.update((s) => ({
            ...s,
            delivery: d,
            positionMs: 0,
        }));
    }

    // `by_ayah` sidecars key chapters as `"<surah>:<ayah>"`, so `Number("1:1")`
    // → NaN. Filter to finite ints so the popover / prev / next controls never
    // surface "Surah NaN" even if a stray by_ayah delivery slips through.
    $: surahNums = Object.keys(urls).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
    $: canPrev = $playerContext.surahNum !== null && surahNums.indexOf($playerContext.surahNum) > 0;
    $: canNext = $playerContext.surahNum !== null
        && surahNums.indexOf($playerContext.surahNum) >= 0
        && surahNums.indexOf($playerContext.surahNum) < surahNums.length - 1;
    $: canDownload = $playerContext.surahNum !== null
        && !!urls[String($playerContext.surahNum)];
</script>

<div class="player" class:has-reciter={$playerContext.reciter !== null}>
    <PlayerProgress
        positionMs={$playerContext.positionMs}
        durationMs={$playerContext.durationMs}
        on:seek={onSeekFromBar}
    />

    <div class="row">
        <PlayerMetaChip
            reciter={$playerContext.reciter}
            delivery={$playerContext.delivery}
            on:select={onCombinationSelect}
        />

        <div class="controls">
            <PlayerControls
                isPlaying={$playerContext.isPlaying}
                isLoading={$playerContext.isLoading}
                canPlay={$playerContext.delivery !== null && $playerContext.surahNum !== null}
                canStepBack={canPrev}
                canStepForward={canNext}
                on:toggle={togglePlay}
                on:seekBack={seekBack}
                on:seekForward={seekForward}
                on:prev={prevSurah}
                on:next={nextSurah}
            />
        </div>

        <div class="right">
            <div class="surah-trigger-wrap" use:clickOutside={() => (surahPopoverOpen = false)}>
                <button
                    type="button"
                    class="surah-trigger"
                    on:click={() => (surahPopoverOpen = !surahPopoverOpen)}
                    disabled={surahNums.length === 0}
                    aria-expanded={surahPopoverOpen}
                    aria-haspopup="dialog"
                >
                    {#if $playerContext.surahNum}
                        Surah <span class="num">{$playerContext.surahNum}</span>
                    {:else}
                        Pick surah
                    {/if}
                </button>
                {#if surahPopoverOpen}
                    <div class="surah-pop">
                        <SurahPopover
                            surahNums={surahNums}
                            value={$playerContext.surahNum}
                            on:change={onSurahChange}
                        />
                    </div>
                {/if}
            </div>
            <button
                type="button"
                class="speed-btn"
                on:click={cycleSpeed}
                title="Playback speed"
            >{$playerContext.speed}×</button>
            <button
                type="button"
                class="download-btn"
                on:click={downloadSurah}
                disabled={!canDownload}
                aria-label="Download surah"
                title="Download surah"
            >
                <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    aria-hidden="true"
                >
                    <path d="M12 3v12" />
                    <path d="m7 10 5 5 5-5" />
                    <path d="M5 21h14" />
                </svg>
            </button>
        </div>
    </div>

    <audio bind:this={audioEl} preload="none"></audio>
</div>

<style>
    .player {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: var(--panel);
        border-top: 1px solid var(--border-default);
        padding: 0 var(--s-4) var(--s-2);
        z-index: 110;
        display: flex;
        flex-direction: column;
        box-shadow: 0 -8px 24px oklch(0 0 0 / 0.25);
    }
    .row {
        display: grid;
        grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);
        align-items: center;
        gap: var(--s-4);
        height: calc(var(--player-h, 72px) - 14px);
    }
    .controls {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--s-3);
    }
    .right {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: var(--s-2);
    }
    .surah-trigger-wrap { position: relative; }
    .surah-trigger {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        padding: 4px var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast);
    }
    .surah-trigger:hover:not(:disabled) {
        border-color: var(--border-strong);
        color: var(--text-primary);
    }
    .surah-trigger:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }
    .surah-trigger .num {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .surah-pop {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        right: 0;
        width: min(560px, calc(100vw - var(--s-4) * 2));
        padding: var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 50;
    }
    .speed-btn {
        padding: 4px var(--s-2);
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast);
        min-width: 36px;
        text-align: center;
    }
    .speed-btn:hover {
        border-color: var(--border-strong);
        color: var(--text-primary);
    }
    .download-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        color: var(--text-secondary);
        background: transparent;
        border: 0;
        border-radius: 50%;
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .download-btn:hover:not(:disabled) {
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .download-btn:disabled {
        opacity: 0.35;
        cursor: not-allowed;
    }
    /* state-pill-btn removed: the delivery bucket is rendered inline
     * inside <ReciterChip>'s bottom row now, so keeping a second pill
     * on the right was duplication. The chip already opens the
     * combination picker on click — losing the bucket button doesn't
     * cost a navigation affordance. */
    audio { display: none; }
</style>
