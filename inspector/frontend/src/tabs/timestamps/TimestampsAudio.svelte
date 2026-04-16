<script lang="ts">
    import { get } from 'svelte/store';
    import { createEventDispatcher } from 'svelte';

    import AudioPlayer from '../../lib/components/AudioPlayer.svelte';
    import { createAnimationLoop } from '../../lib/utils/animation';
    import { LS_KEYS } from '../../lib/utils/constants';
    import {
        autoAdvancing,
        autoMode,
        currentTime,
    } from '../../lib/stores/timestamps/playback';
    import { viewMode } from '../../lib/stores/timestamps/display';
    import { loadedVerse } from '../../lib/stores/timestamps/verse';

    // ---- Props ----
    /** Disabled state of the Prev button. */
    export let prevDisabled: boolean = true;
    /** Disabled state of the Next button. */
    export let nextDisabled: boolean = true;

    // ---- Component ref ----
    let _player: AudioPlayer;

    const dispatch = createEventDispatcher<{
        prev: void;
        next: void;
        tick: void;
        autoNext: void;
        autoRandom: void;
        error: void;
    }>();

    // ---- Public API ----

    /** Return the underlying HTMLAudioElement (null before mount). */
    export function element(): HTMLAudioElement | null {
        return _player?.element() ?? null;
    }

    /** Load a URL, seek to atTime and begin playback. */
    export async function load(url: string | null | undefined, atTime?: number): Promise<void> {
        await _player?.load(url, atTime);
    }

    /** Cycle playback speed up or down. */
    export function cycleSpeed(direction: 'up' | 'down'): void {
        _player?.cycleSpeed(direction);
    }

    // ---- Animation frame loop ----
    const _animLoop = createAnimationLoop(() => {
        _tick();
    });

    function _tick(): void {
        const audio = _player?.element();
        if (!audio) return;
        currentTime.set(audio.currentTime);
        dispatch('tick');
    }

    // ---- Audio event handlers ----

    function onPlay(): void {
        _animLoop.start();
    }

    function onPause(): void {
        _animLoop.stop();
        _tick();
    }

    function onEnded(): void {
        _animLoop.stop();
    }

    function onTimeUpdate(): void {
        const audio = _player?.element();
        if (!audio) return;
        const lv = get(loadedVerse);
        if (!lv) return;

        if (lv.tsSegEnd > 0 && audio.currentTime >= lv.tsSegEnd) {
            audio.pause();
            audio.currentTime = lv.tsSegEnd;
            if (!get(autoAdvancing)) {
                const mode = get(autoMode);
                if (mode === 'next') {
                    autoAdvancing.set(true);
                    dispatch('autoNext');
                } else if (mode === 'random') {
                    autoAdvancing.set(true);
                    dispatch('autoRandom');
                }
            }
        }
        if (audio.paused) _tick();
    }

    function onError(): void {
        const audio = _player?.element();
        if (!audio) return;
        const err = audio.error;
        const code = err ? err.code : 0;
        const msgs: Record<number, string> = {
            1: 'aborted',
            2: 'network error',
            3: 'decode error',
            4: 'unsupported format',
        };
        console.error('Audio load error:', msgs[code] || `code ${code}`, audio.src);
        autoAdvancing.set(false);
        dispatch('error');
    }
</script>

<div class="audio-controls">
    <button class="btn btn-nav" disabled={prevDisabled}
        title="Previous verse ([)" on:click={() => dispatch('prev')}>&#9664; Prev</button>
    <AudioPlayer
        bind:this={_player}
        controls
        lsSpeedKey={LS_KEYS.TS_SPEED}
        on:play={onPlay}
        on:pause={onPause}
        on:ended={onEnded}
        on:timeupdate={onTimeUpdate}
        on:error={onError}
    />
    <button class="btn btn-nav" disabled={nextDisabled}
        title="Next verse (])" on:click={() => dispatch('next')}>Next &#9654;</button>
</div>
