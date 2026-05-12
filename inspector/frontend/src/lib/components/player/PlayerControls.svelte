<script lang="ts">
    /** Player transport controls: prev surah · -15s · play|pause · +15s · next surah. */
    import { createEventDispatcher } from 'svelte';

    export let isPlaying = false;
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
        aria-label={isPlaying ? 'Pause' : 'Play'}
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
    }
    .btn.primary:hover {
        background: var(--accent-strong);
        color: var(--accent-fg);
    }
</style>
