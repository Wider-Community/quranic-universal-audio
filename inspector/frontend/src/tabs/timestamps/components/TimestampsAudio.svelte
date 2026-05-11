<script lang="ts">
    import { createEventDispatcher, onDestroy,onMount } from 'svelte';
    import { get } from 'svelte/store';

    import AudioPlayer from '../../../lib/components/AudioPlayer.svelte';
    import { AudioRange } from '../../../lib/playback/audio-range';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import {
        autoAdvancing,
        autoMode,
        currentTime,
        loopTarget,
        tsAudioElement,
        tsPort,
        tsPortReady,
    } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { loadTimestampsAudio } from '../utils/audio-load';
    import { buildTimestampsRangeSpec } from '../utils/range-spec';

    // ---- Props ----
    /** Disabled state of the Prev button. */
    export let prevDisabled: boolean = true;
    /** Disabled state of the Next button. */
    export let nextDisabled: boolean = true;

    // ---- Component ref ----
    let _player: AudioPlayer;
    let _range: AudioRange | null = null;
    let _suppressAutoPause = false;
    let _suppressAutoPauseTimer: ReturnType<typeof setTimeout> | null = null;

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
        if (!tsPort.source && url) {
            tsPort.setSource({ audioUrl: url, cbrSrc: url, reciter: null, vbr: false });
        }
        try {
            await loadTimestampsAudio(tsPort, get(loadedVerse), atTime ?? 0, autoplay);
            currentTime.set(tsPort.currentTimeMs() / 1000);
        } finally {
            if (autoplay) _finishAutoPauseSuppressionSoon();
        }
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
        if (!mode) return;
        autoAdvancing.set(true);
        // AudioRange._pauseAndFlush just paused the element on the rAF tick.
        // The eventual audio.play() in ingestVerseData runs after the await
        // chain in loadTimestampVerse / loadRandomTimestamp, by which time
        // Chrome's autoplay policy can deny it (no transient activation
        // surviving across the awaits) — manifests as "next verse loads but
        // audio stays paused". Re-arm playback synchronously here so the
        // element stays in the playing state across the transition;
        // ingestVerseData's audioComp.load then just seeks + no-op-plays.
        // Safe against a stale-range re-attach because onPlay below gates on
        // autoAdvancing, and the loadedVerse reactive block re-attaches the
        // rAF once the new range/policy land.
        _beginAutoPauseSuppression();
        tsPort.play();
        if (mode === 'next') dispatch('autoNext');
        else if (mode === 'random-any') dispatch('autoRandomAny');
        else if (mode === 'random-current') dispatch('autoRandomCurrent');
    }

    function _disposeRange(): void {
        _range?.dispose();
        _range = null;
    }

    function _beginAutoPauseSuppression(): void {
        _suppressAutoPause = true;
        if (_suppressAutoPauseTimer) clearTimeout(_suppressAutoPauseTimer);
        _suppressAutoPauseTimer = setTimeout(() => {
            _suppressAutoPause = false;
            _suppressAutoPauseTimer = null;
        }, 1500);
    }

    function _finishAutoPauseSuppressionSoon(): void {
        if (!_suppressAutoPause) return;
        if (_suppressAutoPauseTimer) clearTimeout(_suppressAutoPauseTimer);
        _suppressAutoPauseTimer = setTimeout(() => {
            _suppressAutoPause = false;
            _suppressAutoPauseTimer = null;
        }, 0);
    }

    function _ensureRangeForCurrentState(): AudioRange | null {
        if (!tsPort.element) return null;
        const spec = buildTimestampsRangeSpec(get(loadedVerse), get(loopTarget));
        if (!spec) return null;
        if (_range) {
            _range.setRange(spec.range);
            _range.setPolicy(spec.policy);
            return _range;
        }
        _range = new AudioRange({
            port: tsPort,
            range: spec.range,
            policy: spec.policy,
            onTick: _onTick,
            onBoundary: _onBoundary,
        });
        return _range;
    }

    // Re-spec the running range whenever loop or verse state changes — avoids
    // a stale loop window after the user toggles loopTarget mid-playback or
    // navigates verses. Also re-attaches the rAF loop when audio is playing
    // — covers the auto-advance path where the `tsPort.play()` re-arm in
    // `_onBoundary` fires its 'play' event while `autoAdvancing` is still true
    // (so `onPlay` skips the attach to avoid a second-boundary trigger), and
    // ingestVerseData's same-URL `audio.play()` is a no-op (no fresh 'play'
    // event). Without this, the loop would stay stopped through the rest of
    // the verse and karaoke ticks would freeze.
    $: {
        void $loopTarget;
        void $loadedVerse;
        if (_range) {
            _ensureRangeForCurrentState();
            if (!tsPort.paused) _range.attach();
        }
    }

    // ---- Audio event handlers ----

    function onPlay(): void {
        // attach (not start) — `loadTimestampsAudio(...)` has already loaded
        // the covering source, seeked to the verse start, and kicked off
        // playback. We only want the boundary-watcher rAF on top.
        //
        // Gate on autoAdvancing: during auto-advance the boundary handler
        // re-arms playback via `tsPort.play()` BEFORE the dispatch chain
        // navigates to the next verse. The resulting 'play' event would
        // otherwise re-attach the rAF here against the OLD range — currentTime
        // is still pinned at the old verse's endMs (where _pauseAndFlush left
        // it), so the loop's first frame would fire the boundary AGAIN and
        // `_pauseAndFlush` would pause the element a second time. By the time
        // ingestVerseData's same-URL `audio.play()` runs, the element is
        // paused with no transient activation to revive it — manifests as
        // "auto-next loads but the audio stays paused".
        // The reactive block above handles re-attach once loadedVerse updates.
        if (get(autoAdvancing)) return;
        const r = _ensureRangeForCurrentState();
        r?.attach();
    }

    function onPause(): void {
        // Auto-next uses an internal boundary pause before re-arming playback
        // and swapping/seeking to the next verse. Browsers can deliver that
        // pause event late; treating it as a user pause stops the next load.
        if (_suppressAutoPause) {
            if (tsPort.element) currentTime.set(tsPort.currentTimeMs() / 1000);
            return;
        }
        _range?.stop();
        if (tsPort.element) currentTime.set(tsPort.currentTimeMs() / 1000);
    }

    function onEnded(): void {
        _range?.stop();
    }

    function onTimeUpdate(): void {
        // AudioRange's rAF loop owns boundary enforcement at frame precision.
        // Keep the handler only as a tick when audio is paused (so the playhead
        // store catches a manual seek the rAF doesn't see while paused).
        if (tsPort.paused) currentTime.set(tsPort.currentTimeMs() / 1000);
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
        _suppressAutoPause = false;
        if (_suppressAutoPauseTimer) {
            clearTimeout(_suppressAutoPauseTimer);
            _suppressAutoPauseTimer = null;
        }
        autoAdvancing.set(false);
        dispatch('error');
    }

    onMount(() => {
        const el = _player?.element() ?? null;
        tsAudioElement.set(el);
        if (el) {
            tsPort.attachElement(el);
            tsPortReady.set(true);
        }
    });

    onDestroy(() => {
        if (_suppressAutoPauseTimer) clearTimeout(_suppressAutoPauseTimer);
        _disposeRange();
        tsAudioElement.set(null);
        tsPort.attachElement(null);
        tsPortReady.set(false);
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
