<script lang="ts">
    /**
     * Dashboard-scoped persistent BottomPlayer.
     *
     * Owns the dashPort, binds the <audio> element via attachElement,
     * subscribes to player-context for source changes, drives controls
     * via dashPort, and updates positionMs / isPlaying via port event
     * subscriptions. Sticky at the bottom of the Dashboard tab; the
     * App-shell `hidden` cascade hides it when the Dashboard tab is
     * inactive (transport keeps its position; explicit play required
     * on tab return).
     *
     * Slice I+K of phase 6.
     */
    import { onDestroy, onMount } from 'svelte';

    import { fetchSurahsForDelivery } from '../../api/audio-surahs';
    import { dashPort } from '../../playback/dash-port';
    import {
        loadPersistedSlice,
        persistSlice,
        playerContext,
        setIsPlaying,
        setPosition,
        setSpeed,
        setSurah,
    } from '../../stores/player-context';
    import ReciterPicker from '../picker/ReciterPicker.svelte';
    import PlayerControls from './PlayerControls.svelte';
    import PlayerMetaChip from './PlayerMetaChip.svelte';
    import PlayerProgress from './PlayerProgress.svelte';
    import SpeedPopover from './SpeedPopover.svelte';
    import SurahPopover from './SurahPopover.svelte';

    let audioEl: HTMLAudioElement | null = null;
    let urls: Record<string, string> = {};
    let lastDeliverySlug: string | null = null;
    let lastSurahNum: number | null = null;
    let surahPopoverOpen = false;
    let speedPopoverOpen = false;
    let pickerOpen = false;

    onMount(() => {
        dashPort.attachElement(audioEl);
        // Replay persisted speed if any.
        const slice = loadPersistedSlice();
        if (slice.speed && slice.speed !== 1) setSpeed(slice.speed);
        dashPort.setPlaybackRate(slice.speed);

        const unsubPlay = dashPort.onPlay(() => setIsPlaying(true));
        const unsubPause = dashPort.onPause(() => setIsPlaying(false));
        const unsubLoad = dashPort.onLoad(() => {
            const dur = audioEl?.duration ?? 0;
            setPosition(0, Number.isFinite(dur) ? dur * 1000 : 0);
        });
        const unsubTime = dashPort.onTimeUpdate((fileMs) => {
            setPosition(fileMs, audioEl?.duration ? audioEl.duration * 1000 : undefined);
        });

        return () => {
            unsubPlay();
            unsubPause();
            unsubLoad();
            unsubTime();
            dashPort.attachElement(null);
        };
    });

    onDestroy(() => {
        dashPort.pause();
    });

    // Source swap on context change.
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

        if (delivery.slug !== lastDeliverySlug) {
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

        if (surahNum !== lastSurahNum || delivery.slug !== lastDeliverySlug) {
            const url = urls[String(surahNum)];
            if (url) {
                dashPort.setSource({ audioUrl: url, reciter: delivery.slug, vbr: false });
                dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
                if (wasPlaying) dashPort.play();
            }
            lastSurahNum = surahNum;
        }
    }

    function togglePlay(): void {
        if ($playerContext.isPlaying) dashPort.pause();
        else dashPort.play();
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
        const all = Object.keys(urls).map(Number).sort((a, b) => a - b);
        const idx = all.indexOf(ctx.surahNum);
        if (idx > 0) setSurah(all[idx - 1]!);
    }
    function nextSurah(): void {
        const ctx = $playerContext;
        if (ctx.surahNum === null) return;
        const all = Object.keys(urls).map(Number).sort((a, b) => a - b);
        const idx = all.indexOf(ctx.surahNum);
        if (idx >= 0 && idx < all.length - 1) setSurah(all[idx + 1]!);
    }

    function onSurahChange(ev: CustomEvent<number>): void {
        setSurah(ev.detail);
        surahPopoverOpen = false;
    }

    function onSpeedChange(rate: number): void {
        setSpeed(rate);
        dashPort.setPlaybackRate(rate);
        speedPopoverOpen = false;
        persistSlice({
            deliverySlug: lastDeliverySlug,
            surahNum: lastSurahNum,
            speed: rate,
        });
    }

    function onSeekFromBar(ev: CustomEvent<number>): void {
        dashPort.seek(ev.detail);
    }

    function onPickerSelect(
        ev: CustomEvent<{ kind: 'reciter'; reciter: import('../../types/public-state').PublicReciter; delivery: import('../../types/public-state').PublicDelivery | null }>,
    ): void {
        const { reciter, delivery } = ev.detail;
        if (!delivery) return;
        playerContext.update((s) => ({
            ...s,
            reciter,
            delivery,
            surahNum: s.surahNum ?? 1,
            positionMs: 0,
        }));
    }

    $: surahNums = Object.keys(urls).map(Number).sort((a, b) => a - b);
    $: canPrev = $playerContext.surahNum !== null && surahNums.indexOf($playerContext.surahNum) > 0;
    $: canNext = $playerContext.surahNum !== null
        && surahNums.indexOf($playerContext.surahNum) >= 0
        && surahNums.indexOf($playerContext.surahNum) < surahNums.length - 1;
</script>

<div class="player">
    <PlayerMetaChip
        reciter={$playerContext.reciter}
        delivery={$playerContext.delivery}
        on:open={() => (pickerOpen = true)}
    />

    <div class="center">
        <PlayerControls
            isPlaying={$playerContext.isPlaying}
            canStepBack={canPrev}
            canStepForward={canNext}
            on:toggle={togglePlay}
            on:seekBack={seekBack}
            on:seekForward={seekForward}
            on:prev={prevSurah}
            on:next={nextSurah}
        />
        <PlayerProgress
            positionMs={$playerContext.positionMs}
            durationMs={$playerContext.durationMs}
            on:seek={onSeekFromBar}
        />
    </div>

    <div class="right">
        <div class="surah-trigger-wrap">
            <button
                type="button"
                class="surah-trigger"
                on:click={() => (surahPopoverOpen = !surahPopoverOpen)}
                disabled={surahNums.length === 0}
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
        <SpeedPopover
            value={$playerContext.speed}
            open={speedPopoverOpen}
            on:toggle={() => (speedPopoverOpen = !speedPopoverOpen)}
            on:change={(e) => onSpeedChange(e.detail)}
        />
    </div>

    <audio bind:this={audioEl} preload="metadata" />
</div>

{#if pickerOpen}
    <ReciterPicker
        open={pickerOpen}
        mode="modal"
        title="Switch reciter"
        on:select={onPickerSelect}
        on:close={() => (pickerOpen = false)}
    />
{/if}

<style>
    .player {
        position: sticky;
        bottom: 0;
        left: 0;
        right: 0;
        height: var(--player-h, 72px);
        background: var(--panel);
        border-top: 1px solid var(--border-default);
        display: grid;
        grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);
        align-items: center;
        padding: 0 var(--s-4);
        gap: var(--s-4);
        z-index: 20;
    }
    .center {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        min-width: 320px;
    }
    .right {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: var(--s-2);
    }
    .surah-trigger-wrap {
        position: relative;
    }
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
        padding: var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 30;
    }
    audio { display: none; }
</style>
