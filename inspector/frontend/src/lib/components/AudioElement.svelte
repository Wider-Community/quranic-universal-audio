<script lang="ts">
    /**
     * AudioElement — minimal `<audio>` primitive.
     *
     * Wraps a single HTMLAudioElement, forwards standard lifecycle events, and
     * exposes a safePlay() wrapper. Provisioned for Waves 4/5/11 consumption.
     *
     * CONSUMERS: do NOT swap the legacy #audio-player / #seg-audio-player /
     * #aud-player elements in existing tab markup yet — that is Wave 4/5/11 work.
     * This component sits unreferenced until then.
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
</script>

<audio
    bind:this={audio}
    {src}
    {preload}
    crossorigin={crossorigin ?? null}
    {id}
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
