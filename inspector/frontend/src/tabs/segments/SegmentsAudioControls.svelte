<script lang="ts">
    /**
     * SegmentsAudioControls — audio element + speed control + play/pause +
     * auto-play toggle for the Segments tab.
     *
     * Uses AudioPlayer which composes AudioElement + SpeedControl and handles
     * the pending-metadata guard internally. Continuous-play + segment-end
     * clamping logic stays here.
     *
     * Invariant: the speed <select> keeps id="seg-speed-select" so the
     * imperative modules (playback/index.ts, keyboard.ts, edit/common.ts) that
     * reference dom.segSpeedSelect continue to resolve via getElementById.
     *
     * The <audio> element's id "seg-audio-player" is preserved inside
     * AudioElement (via AudioPlayer) for audio-cache.ts and keyboard.ts.
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';
    import { autoPlayEnabled } from '../../lib/stores/segments/playback';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { dom, state } from '../../lib/segments-state';
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

    // Keep audioEl prop in sync with the underlying HTMLAudioElement.
    // Svelte 4 bind: on a prop propagates child→parent when the child mutates it.
    $: audioEl = _player?.element() ?? null;

    // Bind:this target for the play button — assigned to dom.segPlayBtn.
    let playBtn: HTMLButtonElement;
    // Bind:this target for the autoplay button — assigned to dom.segAutoPlayBtn.
    let autoPlayBtn: HTMLButtonElement;
    // Bind:this target for the play status span — assigned to dom.segPlayStatus.
    let playStatusEl: HTMLElement;

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
        state._segAutoPlayEnabled = next;
        state._segContinuousPlay = next;
        localStorage.setItem(LS_KEYS.SEG_AUTOPLAY, String(next));
    }

    // -------------------------------------------------------------------------
    // Mount: assign dom refs + wire audio listeners
    // -------------------------------------------------------------------------

    onMount(() => {
        const el = _player.element()!;
        dom.segAudioEl    = el;
        dom.segPlayBtn    = playBtn;
        dom.segAutoPlayBtn = autoPlayBtn;
        dom.segPlayStatus  = playStatusEl;

        state._segAutoPlayEnabled = get(autoPlayEnabled);

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
         keyboard.ts resolve it via document.getElementById / mustGet. -->
    <AudioPlayer
        bind:this={_player}
        audioId="seg-audio-player"
        lsSpeedKey={LS_KEYS.SEG_SPEED}
        speedSelectId="seg-speed-select"
        controls={false}
        showSpeedControl={true}
    />
    <button
        id="seg-play-btn"
        class="btn"
        disabled
        bind:this={playBtn}
        on:click={handlePlayClick}
    >Play</button>
    <button
        id="seg-autoplay-btn"
        class={autoPlayClass}
        title="Auto-play consecutive segments"
        bind:this={autoPlayBtn}
        on:click={handleAutoPlayToggle}
    >Auto-play</button>
    <span id="seg-play-status" class="seg-play-status" bind:this={playStatusEl}></span>
</div>
