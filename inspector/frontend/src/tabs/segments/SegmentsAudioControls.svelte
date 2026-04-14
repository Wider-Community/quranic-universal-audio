<script lang="ts">
    /**
     * SegmentsAudioControls — audio element + play/pause + auto-play toggle
     * for the Segments tab.
     *
     * Extracted from the `.seg-controls` inline markup in SegmentsTab.svelte
     * and the DOMContentLoaded wiring block in segments/index.ts (lines 118-135).
     *
     * Owns:
     *  - <audio id="seg-audio-player"> with all 4 lifecycle listeners
     *  - Play / Pause button (id="seg-play-btn")
     *  - Auto-play toggle button (id="seg-autoplay-btn")
     *  - Play-status span (id="seg-play-status")
     *
     * Does NOT own:
     *  - Speed select (stays in SegmentsTab toolbar; dom.segSpeedSelect ref
     *    read by playback/index.ts line 39 + index.ts line 125)
     *  - Audio src management (SegmentsTab.onChapterChange sets audioEl.src)
     *
     * Invariant (Rule 7): <audio> keeps id="seg-audio-player" so audio-cache.ts
     * and keyboard.ts can still reach it via mustGet / document.getElementById.
     *
     * Pattern note #8 (hybrid 60fps): audio event listeners fire imperative
     * playback/index.ts functions (onSegTimeUpdate, startSegAnimation, etc.)
     * that update DOM classes directly. The `autoPlayEnabled` store drives only
     * the button class; per-frame highlight state stays on state.*.
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';
    import { autoPlayEnabled } from '../../lib/stores/segments/playback';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { dom, state } from '../../segments/state';
    import {
        onSegAudioEnded,
        onSegPlayClick,
        onSegTimeUpdate,
        startSegAnimation,
        stopSegAnimation,
    } from '../../segments/playback/index';
    import { stopErrorCardAudio } from '../../segments/validation/error-card-audio';

    // Bind:this target — the audio element is assigned to dom.segAudioEl in
    // onMount so all imperative modules that read dom.segAudioEl keep working.
    let audioEl: HTMLAudioElement;
    // Bind:this target for the play button — assigned to dom.segPlayBtn.
    let playBtn: HTMLButtonElement;
    // Bind:this target for the autoplay button — assigned to dom.segAutoPlayBtn.
    let autoPlayBtn: HTMLButtonElement;
    // Bind:this target for the play status span — assigned to dom.segPlayStatus.
    let playStatusEl: HTMLElement;

    // Reactive button class driven by the `autoPlayEnabled` store.
    $: autoPlayClass = 'btn ' + ($autoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');

    // -------------------------------------------------------------------------
    // Event handlers (moved from segments/index.ts DOMContentLoaded)
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
        // Wire dom refs so imperative modules keep working.
        dom.segAudioEl   = audioEl;
        dom.segPlayBtn   = playBtn;
        dom.segAutoPlayBtn = autoPlayBtn;
        dom.segPlayStatus  = playStatusEl;

        // Sync initial state.* field from the store (segments/index.ts used to
        // read localStorage inline; now the store initialises from localStorage,
        // and we mirror into state.* here so playback/index.ts sees a consistent
        // value on first play).
        state._segAutoPlayEnabled = get(autoPlayEnabled);

        // Wire the 4 audio lifecycle listeners (moved from segments/index.ts
        // lines 132-135).
        audioEl.addEventListener('play', startSegAnimation);
        audioEl.addEventListener('pause', stopSegAnimation);
        audioEl.addEventListener('ended', onSegAudioEnded);
        audioEl.addEventListener('timeupdate', onSegTimeUpdate);

        return () => {
            // Cleanup on component destroy (tab hide / unmount).
            audioEl.removeEventListener('play', startSegAnimation);
            audioEl.removeEventListener('pause', stopSegAnimation);
            audioEl.removeEventListener('ended', onSegAudioEnded);
            audioEl.removeEventListener('timeupdate', onSegTimeUpdate);
            stopErrorCardAudio();
        };
    });
</script>

<div class="seg-controls">
    <!-- audio id MUST stay "seg-audio-player" — audio-cache.ts and keyboard.ts
         reach it via document.getElementById / mustGet. -->
    <audio id="seg-audio-player" bind:this={audioEl}></audio>
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
