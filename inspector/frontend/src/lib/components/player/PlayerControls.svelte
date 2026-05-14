<script lang="ts">
    /** Player transport controls: prev surah · -15s · play|pause · +15s · next surah. */
    import { createEventDispatcher } from 'svelte';

    export let isPlaying = false;
    export let isLoading = false;
    export let canPlay = true;
    export let canStepBack = true;
    export let canStepForward = true;

    const dispatch = createEventDispatcher<{
        prev: void;
        next: void;
        seekBack: void;
        seekForward: void;
        toggle: void;
    }>();
</script>

<div class="controls">
    <button
        type="button"
        class="btn"
        aria-label="Previous surah"
        disabled={!canStepBack}
        on:click={() => dispatch('prev')}
    >⏮</button>
    <button type="button" class="btn" aria-label="Back 15 seconds" on:click={() => dispatch('seekBack')}>«</button>
    <button
        type="button"
        class="btn primary"
        class:loading={isLoading}
        aria-label={isLoading ? 'Loading audio' : isPlaying ? 'Pause' : 'Play'}
        aria-busy={isLoading}
        disabled={!canPlay || isLoading}
        on:click={() => dispatch('toggle')}
    >{isPlaying ? '⏸' : '▶'}</button>
    <button type="button" class="btn" aria-label="Forward 15 seconds" on:click={() => dispatch('seekForward')}>»</button>
    <button
        type="button"
        class="btn"
        aria-label="Next surah"
        disabled={!canStepForward}
        on:click={() => dispatch('next')}
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
    /* Loading: pulse a ring around the play button until audio is ready
     * to play immediately. The play/pause glyph stays visible — only the
     * ring signals "buffering". Ring is a ::before pseudo-element so it
     * doesn't interfere with the click target. */
    .btn.primary.loading {
        cursor: progress;
    }
    /* The .loading disc itself keeps full opacity so the glyph stays
     * legible — override the generic :disabled dim. */
    .btn.primary.loading:disabled {
        opacity: 1;
    }
    .btn.primary.loading::before {
        content: '';
        position: absolute;
        inset: -3px;
        border-radius: 50%;
        border: 2px solid var(--accent);
        animation: player-ring-pulse 1.2s ease-in-out infinite;
        pointer-events: none;
    }
    @keyframes player-ring-pulse {
        0%   { transform: scale(1);    opacity: 0.35; }
        50%  { transform: scale(1.18); opacity: 1; }
        100% { transform: scale(1);    opacity: 0.35; }
    }
    @media (prefers-reduced-motion: reduce) {
        .btn.primary.loading::before {
            animation: none;
            opacity: 0.7;
        }
    }
</style>
