<script lang="ts">
    /**
     * AudioPlayer — composable audio player wrapper.
     *
     * Composes AudioElement (thin <audio> primitive) with SpeedControl and
     * exposes a load(url, atTime?) method that handles the pending-metadata
     * guard and same-src short-circuit. Not consumed until Ph2 adopts it in
     * TimestampsTab and SegmentsAudioControls.
     *
     * Named slots: before | after | extras (for caller-injected controls).
     */

    import { createEventDispatcher } from 'svelte';

    import AudioElement from './AudioElement.svelte';
    import SpeedControl from './SpeedControl.svelte';

    /** Audio source URL. Caller may also use the load() method for precise control. */
    export let src: string | null | undefined = undefined;
    /** Preload hint forwarded to the underlying <audio> element. */
    export let preload: 'none' | 'metadata' | 'auto' = 'metadata';
    /** Show native browser controls. */
    export let controls: boolean = true;
    /** localStorage key used by SpeedControl to persist the chosen playback rate. */
    export let lsSpeedKey: string = '';
    /** Whether to render the SpeedControl widget below the audio element. */
    export let showSpeedControl: boolean = true;

    // Internal refs
    let _audioEl: AudioElement;
    let _speedCtrl: SpeedControl;
    let _pendingOnMeta: ((ev: Event) => void) | null = null;

    const dispatch = createEventDispatcher<{
        loadedmetadata: { audio: HTMLAudioElement; event: Event };
        play:           { audio: HTMLAudioElement; event: Event };
        pause:          { audio: HTMLAudioElement; event: Event };
        ended:          { audio: HTMLAudioElement; event: Event };
        timeupdate:     { audio: HTMLAudioElement; event: Event };
        error:          { audio: HTMLAudioElement; event: Event };
        seeking:        { audio: HTMLAudioElement; event: Event };
    }>();

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /** Return the underlying HTMLAudioElement (null before mount). */
    export function element(): HTMLAudioElement | null {
        return _audioEl?.element() ?? null;
    }

    /**
     * Load a URL and start playback.
     *
     * - If url is null/undefined: clears the src and calls load().
     * - If src is unchanged (same-src): seeks to atTime and plays immediately.
     * - If src changed: registers a one-shot loadedmetadata handler that
     *   seeks to atTime and starts playback once metadata is ready.
     */
    export async function load(url: string | null | undefined, atTime?: number): Promise<void> {
        const audio = element();
        if (!audio) return;

        // Cancel any pending metadata handler from a previous load
        if (_pendingOnMeta) {
            audio.removeEventListener('loadedmetadata', _pendingOnMeta);
            _pendingOnMeta = null;
        }

        if (!url) {
            audio.removeAttribute('src');
            audio.load();
            return;
        }

        const same = audio.src === url || audio.src === location.origin + url;
        if (!same) {
            const seekTo = atTime ?? 0;
            const onMeta = (): void => {
                audio.removeEventListener('loadedmetadata', onMeta);
                if (_pendingOnMeta === onMeta) _pendingOnMeta = null;
                audio.currentTime = seekTo;
                audio.play().catch(() => {/* AbortError on rapid src change */});
            };
            _pendingOnMeta = onMeta;
            audio.addEventListener('loadedmetadata', onMeta);
            audio.src = url;
        } else {
            if (atTime !== undefined) audio.currentTime = atTime;
            audio.play().catch(() => {/* AbortError on interrupted play() */});
        }
    }

    /** Cycle playback speed up or down via the SpeedControl widget. */
    export function cycleSpeed(direction: 'up' | 'down'): void {
        _speedCtrl?.cycle(direction);
    }

    // -----------------------------------------------------------------------
    // Event forwarding from AudioElement
    // -----------------------------------------------------------------------

    function fwd(name: keyof typeof dispatch, detail: { audio: HTMLAudioElement; event: Event }): void {
        dispatch(name, detail);
    }
</script>

<slot name="before" />

<AudioElement
    bind:this={_audioEl}
    src={src ?? undefined}
    {preload}
    {controls}
    on:loadedmetadata={e => fwd('loadedmetadata', e.detail)}
    on:play={e => fwd('play', e.detail)}
    on:pause={e => fwd('pause', e.detail)}
    on:ended={e => fwd('ended', e.detail)}
    on:timeupdate={e => fwd('timeupdate', e.detail)}
    on:error={e => fwd('error', e.detail)}
    on:seeking={e => fwd('seeking', e.detail)}
/>

{#if showSpeedControl}
    <SpeedControl
        bind:this={_speedCtrl}
        audioElement={element()}
        lsKey={lsSpeedKey}
    />
{/if}

<slot name="after" />
<slot name="extras" />
