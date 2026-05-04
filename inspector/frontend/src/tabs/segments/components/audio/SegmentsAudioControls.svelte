<script lang="ts">
    /**
     * SegmentsAudioControls — audio element + speed <select> + play/pause +
     * auto-play toggle for the Segments tab.
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';
    import { segData } from '../../stores/chapter';
    import {
        autoPlayEnabled,
        autoScrollEnabled,
        continuousPlay,
        playbackSpeed,
        playButtonLabel,
        segAudioElement,
    } from '../../stores/playback';
    import { LS_KEYS } from '../../../../lib/utils/constants';
    import { SPEEDS } from '../../../../lib/utils/speed-control';
    import {
        onSegAudioEnded,
        onSegPlayClick,
        onSegTimeUpdate,
        startSegAnimation,
        stopSegAnimation,
    } from '../../utils/playback/playback';
    import AudioPlayer from '../../../../lib/components/AudioPlayer.svelte';

    // ---- Exported prop: raw HTMLAudioElement exposed to parent via bind:audioEl ----
    // Populated reactively once AudioPlayer mounts and element() returns non-null.
    export let audioEl: HTMLAudioElement | null = null;

    // ---- Internal refs ----
    let _player: AudioPlayer;

    // Keep audioEl prop in sync with the underlying HTMLAudioElement, and
    // publish it to the segAudioElement store.
    $: audioEl = _player?.element() ?? null;
    $: segAudioElement.set(audioEl);

    // Reactive button classes driven by the toggle stores.
    $: autoPlayClass = 'btn ' + ($autoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');
    $: autoScrollClass = 'btn ' + ($autoScrollEnabled ? 'seg-autoscroll-on' : 'seg-autoscroll-off');

    // -------------------------------------------------------------------------
    // Event handlers
    // -------------------------------------------------------------------------

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

    function onSpeedSelectChange(e: Event): void {
        const v = parseFloat((e.currentTarget as HTMLSelectElement).value);
        if (!isNaN(v)) {
            playbackSpeed.set(v);
            localStorage.setItem(LS_KEYS.SEG_SPEED, String(v));
            if (audioEl) audioEl.playbackRate = v;
        }
    }

    // Seed the audio element's playbackRate from the store once it mounts.
    // Don't mirror $playbackSpeed reactively — a `$: audioEl.playbackRate =
    // $playbackSpeed` block re-runs inside Svelte's update cycle alongside
    // the speed <select>'s re-render, which drops focus onto the select and
    // halts audio playback. All speed writes set audioEl.playbackRate
    // directly at the call site (keyboard.ts, onSpeedSelectChange).
    $: if (audioEl && audioEl.playbackRate === 1 && $playbackSpeed !== 1) {
        audioEl.playbackRate = $playbackSpeed;
    }

    // Ensure the audio element's src reflects the current chapter's audio_url
    // after the normal-content block re-mounts (e.g. leaving history/save
    // preview with a chapter already loaded). Only fires when audioEl is
    // unset, empty, or missing the expected URL; avoids resetting playback
    // on every reactive re-run.
    $: if (audioEl && $segData?.audio_url) {
        const want = $segData.audio_url;
        const cur = audioEl.src;
        if (!cur || (cur !== want && cur !== location.origin + want)) {
            audioEl.src = want;
            audioEl.preload = 'auto';
        }
    }

    // -------------------------------------------------------------------------
    // Mount: wire audio listeners
    // -------------------------------------------------------------------------

    onMount(() => {
        const el = _player.element()!;

        // Seed playbackSpeed from localStorage.
        const stored = localStorage.getItem(LS_KEYS.SEG_SPEED);
        if (stored) {
            const v = parseFloat(stored);
            if (!isNaN(v)) playbackSpeed.set(v);
        }

        el.addEventListener('play', startSegAnimation);
        el.addEventListener('pause', stopSegAnimation);
        el.addEventListener('ended', onSegAudioEnded);
        el.addEventListener('timeupdate', onSegTimeUpdate);

        return () => {
            el.removeEventListener('play', startSegAnimation);
            el.removeEventListener('pause', stopSegAnimation);
            el.removeEventListener('ended', onSegAudioEnded);
            el.removeEventListener('timeupdate', onSegTimeUpdate);
        };
    });
</script>

<div class="seg-controls">
    <AudioPlayer
        bind:this={_player}
        controls={false}
        showSpeedControl={false}
    />
    <label class="speed-label">
        Speed:
        <select
            id="seg-speed-select"
            class="speed-select"
            value={$playbackSpeed}
            on:change={onSpeedSelectChange}
        >
            {#each SPEEDS as s}
                <option value={s}>{s}x</option>
            {/each}
        </select>
    </label>
    <button
        id="seg-play-btn"
        class="btn"
        disabled={!audioEl || !$segData?.audio_url}
        on:click={handlePlayClick}
    >{$playButtonLabel}</button>
    <button
        id="seg-autoplay-btn"
        class={autoPlayClass}
        title="Auto-play consecutive segments"
        on:click={handleAutoPlayToggle}
    >Auto-play</button>
    <button
        id="seg-autoscroll-btn"
        class={autoScrollClass}
        title="Auto-scroll the list to follow the playing segment"
        on:click={handleAutoScrollToggle}
    >Auto-scroll</button>
</div>

<style>
    .speed-label {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 0.9rem;
        color: #ccc;
    }
    .speed-select {
        background: #16213e;
        color: #eee;
        border: 1px solid #333;
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 0.85rem;
        cursor: pointer;
    }
</style>
