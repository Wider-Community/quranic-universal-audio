<script lang="ts">
    /** Player transport controls: prev surah · -15s · play|pause · +15s · next surah. */
    import { createEventDispatcher } from 'svelte';

    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';

    import LoadingSpinner from './LoadingSpinner.svelte';

    export let isPlaying = false;
    export let isLoading = false;
    export let canPlay = true;
    export let canStepBack = true;
    export let canStepForward = true;

    const dispatch = createEventDispatcher<{
        prev: void;
        next: void;
        prevHover: void;
        nextHover: void;
        seekBack: void;
        seekForward: void;
        toggle: void;
    }>();

    $: lang = $localeStore;
    $: prevSurahLabel = tr(lang, m.common_player_prev_surah_label());
    $: seekBackLabel = tr(lang, m.common_player_seek_back_label());
    $: seekForwardLabel = tr(lang, m.common_player_seek_forward_label());
    $: nextSurahLabel = tr(lang, m.common_player_next_surah_label());
    $: playToggleLabel = tr(
        lang,
        isLoading
            ? m.common_player_loading_audio_label()
            : isPlaying
              ? m.common_action_pause()
              : m.common_action_play(),
    );
</script>

<div class="controls">
    <button
        type="button"
        class="btn"
        aria-label={prevSurahLabel}
        disabled={!canStepBack}
        on:click={() => dispatch('prev')}
        on:pointerenter={() => dispatch('prevHover')}
        on:focus={() => dispatch('prevHover')}
    >⏮</button>
    <button type="button" class="btn" aria-label={seekBackLabel} on:click={() => dispatch('seekBack')}>«</button>
    <button
        type="button"
        class="btn primary"
        class:loading={isLoading}
        aria-label={playToggleLabel}
        aria-busy={isLoading}
        disabled={!canPlay || isLoading}
        on:click={() => dispatch('toggle')}
    >{#if isLoading}<LoadingSpinner color="var(--accent-fg)" />{:else}{isPlaying ? '⏸' : '▶'}{/if}</button>
    <button type="button" class="btn" aria-label={seekForwardLabel} on:click={() => dispatch('seekForward')}>»</button>
    <button
        type="button"
        class="btn"
        aria-label={nextSurahLabel}
        disabled={!canStepForward}
        on:click={() => dispatch('next')}
        on:pointerenter={() => dispatch('nextHover')}
        on:focus={() => dispatch('nextHover')}
    >⏭</button>
</div>

<style>
    .controls {
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }
    .btn {
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--text-secondary);
        background: transparent;
        border: 0;
        border-radius: 50%;
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .btn:hover:not(:disabled) {
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .btn:disabled { opacity: 0.35; cursor: not-allowed; }
    .btn.primary {
        width: 40px;
        height: 40px;
        background: var(--accent);
        color: var(--accent-fg);
        position: relative;
    }
    .btn.primary:hover {
        background: var(--accent-strong);
        color: var(--accent-fg);
    }
    /* Loading: the shared <LoadingSpinner> replaces the play/pause glyph
     * until the first audible frame (`playing`), so the control reads as
     * "buffering" rather than falsely "playing" during the click/seek →
     * sound gap. */
    .btn.primary.loading {
        cursor: progress;
    }
    /* The .loading disc itself keeps full opacity so the spinner stays
     * legible — override the generic :disabled dim. */
    .btn.primary.loading:disabled {
        opacity: 1;
    }
</style>
