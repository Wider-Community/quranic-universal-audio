<script lang="ts">
    import { get } from 'svelte/store';
    import { createEventDispatcher, onMount, onDestroy } from 'svelte';

    import AudioPlayer from '../../../lib/components/AudioPlayer.svelte';
    import { AudioRange } from '../../../lib/playback/audio-range';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import {
        autoAdvancing,
        autoMode,
        currentTime,
        loopTarget,
        tsAudioElement,
    } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { buildTimestampsRangeSpec } from '../utils/range-spec';

    // ---- Props ----
    /** Disabled state of the Prev button. */
    export let prevDisabled: boolean = true;
    /** Disabled state of the Next button. */
    export let nextDisabled: boolean = true;

    // ---- Component ref ----
    let _player: AudioPlayer;
    let _range: AudioRange | null = null;

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

    // ---- AudioRange wiring ----

    function _onTick(timeMs: number): void {
        currentTime.set(timeMs / 1000);
        dispatch('tick');
    }

    function _onBoundary(ev: { reason: string }): void {
        if (ev.reason !== 'stop') return;
        // Mirrors the legacy onTimeUpdate auto-advance branch — fires once
        // per verse-end crossing, guarded by autoAdvancing against re-entry.
        if (get(autoAdvancing)) return;
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

    function _disposeRange(): void {
        _range?.dispose();
        _range = null;
    }

    function _ensureRangeForCurrentState(): AudioRange | null {
        const audio = _player?.element();
        if (!audio) return null;
        const spec = buildTimestampsRangeSpec(get(loadedVerse), get(loopTarget));
        if (!spec) return null;
        if (_range) {
            _range.setRange(spec.range);
            _range.setPolicy(spec.policy);
            return _range;
        }
        _range = new AudioRange({
            audioEl: audio,
            range: spec.range,
            policy: spec.policy,
            onTick: _onTick,
            onBoundary: _onBoundary,
        });
        return _range;
    }

    // Re-spec the running range whenever loop or verse state changes — avoids
    // a stale loop window after the user toggles loopTarget mid-playback or
    // navigates verses.
    $: {
        void $loopTarget;
        void $loadedVerse;
        if (_range) _ensureRangeForCurrentState();
    }

    // ---- Audio event handlers ----

    function onPlay(): void {
        // attach (not start) — `_player.load(url, atTime, autoplay)` has
        // already seeked to the verse start and kicked off playback. We only
        // want the boundary-watcher rAF on top.
        const r = _ensureRangeForCurrentState();
        r?.attach();
    }

    function onPause(): void {
        _range?.stop();
        const audio = _player?.element();
        if (audio) currentTime.set(audio.currentTime);
    }

    function onEnded(): void {
        _range?.stop();
    }

    function onTimeUpdate(): void {
        // AudioRange's rAF loop owns boundary enforcement at frame precision.
        // Keep the handler only as a tick when audio is paused (so the playhead
        // store catches a manual seek the rAF doesn't see while paused).
        const audio = _player?.element();
        if (audio?.paused) currentTime.set(audio.currentTime);
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
        _disposeRange();
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
