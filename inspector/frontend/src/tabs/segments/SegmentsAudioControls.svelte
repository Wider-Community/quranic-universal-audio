<script lang="ts">
    /**
     * SegmentsAudioControls — audio element + speed <select> + play/pause +
     * auto-play toggle for the Segments tab.
     *
     * Uses AudioPlayer for the underlying <audio> element; the speed <select>
     * is rendered inline and writes to the `playbackSpeed` store. A reactive
     * subscriber mirrors the store onto the audio element's playbackRate.
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';
    import {
        autoPlayEnabled,
        continuousPlay,
        playbackSpeed,
        playButtonLabel,
        playStatusText,
        segAudioElement,
    } from '../../lib/stores/segments/playback';
    import { LS_KEYS } from '../../lib/utils/constants';
    import {
        onSegAudioEnded,
        onSegPlayClick,
        onSegTimeUpdate,
        startSegAnimation,
        stopSegAnimation,
    } from '../../lib/utils/segments/playback';
    import { stopErrorCardAudio } from '../../lib/utils/segments/error-card-audio';
    import AudioPlayer from '../../lib/components/AudioPlayer.svelte';

    // ---- Exported prop: raw HTMLAudioElement exposed to parent via bind:audioEl ----
    // Populated reactively once AudioPlayer mounts and element() returns non-null.
    export let audioEl: HTMLAudioElement | null = null;

    // ---- Internal refs ----
    let _player: AudioPlayer;

    // Keep audioEl prop in sync with the underlying HTMLAudioElement, and
    // publish it to the segAudioElement store.
    $: audioEl = _player?.element() ?? null;
    $: segAudioElement.set(audioEl);

    // Reactive button class driven by the `autoPlayEnabled` store.
    $: autoPlayClass = 'btn ' + ($autoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');

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

    function onSpeedSelectChange(e: Event): void {
        const v = parseFloat((e.currentTarget as HTMLSelectElement).value);
        if (!isNaN(v)) {
            playbackSpeed.set(v);
            localStorage.setItem(LS_KEYS.SEG_SPEED, String(v));
        }
    }

    // Mirror the playbackSpeed store onto the audio element when either changes.
    $: if (audioEl) audioEl.playbackRate = $playbackSpeed;

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
            stopErrorCardAudio();
        };
    });
</script>

<div class="seg-controls">
    <!-- audioId preserves id="seg-audio-player" so audio-cache.ts and
         keyboard.ts resolve it via document.getElementById. -->
    <AudioPlayer
        bind:this={_player}
        audioId="seg-audio-player"
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
            {#each [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5] as s}
                <option value={s}>{s}x</option>
            {/each}
        </select>
    </label>
    <button
        id="seg-play-btn"
        class="btn"
        disabled={!audioEl}
        on:click={handlePlayClick}
    >{$playButtonLabel}</button>
    <button
        id="seg-autoplay-btn"
        class={autoPlayClass}
        title="Auto-play consecutive segments"
        on:click={handleAutoPlayToggle}
    >Auto-play</button>
    <span id="seg-play-status" class="seg-play-status">{$playStatusText}</span>
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
