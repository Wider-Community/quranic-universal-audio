<script lang="ts">
    import { get } from 'svelte/store';
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';

    import AudioPlayer from '../../../lib/components/AudioPlayer.svelte';
    import { createAnimationLoop } from '../../../lib/utils/animation';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import {
        autoAdvancing,
        autoMode,
        currentTime,
        loopTarget,
        tsAudioElement,
    } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';

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
        autoRandomAny: void;
        autoRandomCurrent: void;
        error: void;
    }>();

    // ---- Public API ----

    /** Return the underlying HTMLAudioElement (null before mount). */
    export function element(): HTMLAudioElement | null {
        return _player?.element() ?? null;
    }

    /** Load a URL, seek to atTime and (optionally) begin playback. */
    export async function load(
        url: string | null | undefined,
        atTime?: number,
        autoplay: boolean = true,
    ): Promise<void> {
        await _player?.load(url, atTime, autoplay);
    }

    // ---- Animation frame loop ----
    const _animLoop = createAnimationLoop(() => {
        _tick();
    });

    function _tick(): void {
        const audio = _player?.element();
        if (!audio) return;
        // Loop-boundary check — runs at ~16ms granularity under normal rAF
        // (vs ~250ms for `timeupdate` in Chrome). Overshoot at most one frame,
        // imperceptible even for the shortest phoneme loops. `onTimeUpdate`
        // performs the same check as a safety net if rAF is ever throttled.
        if (_enforceLoop(audio)) return;
        currentTime.set(audio.currentTime);
        dispatch('tick');
    }

    /** Returns true if a loop wrap was applied this frame. */
    function _enforceLoop(audio: HTMLAudioElement): boolean {
        const lt = get(loopTarget);
        if (!lt) return false;
        const lv = get(loadedVerse);
        if (!lv || audio.paused) return false;
        const endAbs = lt.endSec + lv.tsSegOffset;
        if (audio.currentTime >= endAbs) {
            audio.currentTime = lt.startSec + lv.tsSegOffset;
            return true;
        }
        return false;
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

        // While looping, enforce the loop wrap here as a safety net in case
        // rAF is throttled (e.g. background tab). Then skip the verse-end /
        // auto-advance path so a loop whose end aligns with `tsSegEnd`
        // doesn't accidentally trigger Auto Next/Random.
        if (get(loopTarget)) {
            _enforceLoop(audio);
            if (audio.paused) _tick();
            return;
        }

        if (lv.tsSegEnd > 0 && audio.currentTime >= lv.tsSegEnd) {
            audio.pause();
            audio.currentTime = lv.tsSegEnd;
            if (!get(autoAdvancing)) {
                const mode = get(autoMode);
                if (mode === 'next') {
                    autoAdvancing.set(true);
                    dispatch('autoNext');
                } else if (mode === 'random-any') {
                    autoAdvancing.set(true);
                    dispatch('autoRandomAny');
                } else if (mode === 'random-current') {
                    autoAdvancing.set(true);
                    dispatch('autoRandomCurrent');
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

    onMount(() => {
        tsAudioElement.set(_player?.element() ?? null);
    });

    onDestroy(() => {
        tsAudioElement.set(null);
    });
</script>

<div class="audio-controls">
    <button class="btn btn-nav" disabled={prevDisabled}
        title="Previous verse ([)" on:click={() => dispatch('prev')}>&#9664; Prev</button>
    <AudioPlayer
        bind:this={_player}
        controls
        showSpeedControl={false}
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
