<script lang="ts">
    /**
     * AudioElement — minimal `<audio>` primitive.
     *
     * Wraps a single HTMLAudioElement, forwards standard lifecycle events,
     * and exposes a safePlay() wrapper. Consumed by AudioPlayer.svelte and
     * the Timestamps / Segments tab audio controls.
     */

    import { createEventDispatcher } from 'svelte';
    import { safePlay } from '../utils/audio';

    /** Audio source URL. */
    export let src: string | undefined = undefined;
    /** Preload hint. */
    export let preload: 'none' | 'metadata' | 'auto' = 'metadata';
    /** CORS attribute value. null removes the attribute. */
    export let crossorigin: string | null = null;
    /** Optional DOM id forwarded to the underlying <audio> element. */
    export let id: string | undefined = undefined;
    /** Show native browser controls (play/pause/scrubber). */
    export let controls = false;

    /** The raw HTMLAudioElement — use `bind:this={audio}` at call site. */
    let audio: HTMLAudioElement;

    const dispatch = createEventDispatcher<{
        play:          { audio: HTMLAudioElement; event: Event };
        pause:         { audio: HTMLAudioElement; event: Event };
        ended:         { audio: HTMLAudioElement; event: Event };
        timeupdate:    { audio: HTMLAudioElement; event: Event };
        loadedmetadata:{ audio: HTMLAudioElement; event: Event };
        error:         { audio: HTMLAudioElement; event: Event };
        abort:         { audio: HTMLAudioElement; event: Event };
        seeking:       { audio: HTMLAudioElement; event: Event };
        seeked:        { audio: HTMLAudioElement; event: Event };
        playing:       { audio: HTMLAudioElement; event: Event };
    }>();

    /** Plays the audio element via safePlay() (swallows AbortError). */
    export async function play(): Promise<void> {
        safePlay(audio);
    }

    /** Pauses the audio element. */
    export function pause(): void {
        audio.pause();
    }

    /** Returns the underlying HTMLAudioElement. May be null during initial
     *  render; safe to call inside onMount of the parent or after the
     *  component dispatches any event. */
    export function element(): HTMLAudioElement {
        return audio;
    }
</script>

<audio
    bind:this={audio}
    {src}
    {preload}
    crossorigin={crossorigin ?? null}
    {id}
    {controls}
    on:play={e => dispatch('play', { audio, event: e })}
    on:pause={e => dispatch('pause', { audio, event: e })}
    on:ended={e => dispatch('ended', { audio, event: e })}
    on:timeupdate={e => dispatch('timeupdate', { audio, event: e })}
    on:loadedmetadata={e => dispatch('loadedmetadata', { audio, event: e })}
    on:error={e => dispatch('error', { audio, event: e })}
    on:abort={e => dispatch('abort', { audio, event: e })}
    on:seeking={e => dispatch('seeking', { audio, event: e })}
    on:seeked={e => dispatch('seeked', { audio, event: e })}
    on:playing={e => dispatch('playing', { audio, event: e })}
></audio>
