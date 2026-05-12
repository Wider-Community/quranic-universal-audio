<script lang="ts">
    /**
     * ReciterRow — single catalog row primitive. Used by both
     * `CatalogTable` (dashboard) and `ReciterPicker` (modal).
     *
     * - `compact`  — single line, hover row, no expansion.
     * - `expanded` — same row with the inline deliveries table beneath.
     *
     * Slug never rendered in the DOM (PUBLIC contract).
     */
    import { createEventDispatcher } from 'svelte';

    import type { PublicDelivery, PublicReciter } from '../types/public-state';
    import CoveragePill from './CoveragePill.svelte';
    import DeliveriesTable from './DeliveriesTable.svelte';
    import StatePill from './StatePill.svelte';

    export let reciter: PublicReciter;
    export let mode: 'compact' | 'expanded' = 'compact';
    /** When true the play button is rendered. */
    export let showPlay = true;

    const dispatch = createEventDispatcher<{
        click: void;
        play: void;
        playDelivery: PublicDelivery;
        toggleDeliveries: void;
    }>();

    function onPlay(ev: Event): void {
        ev.stopPropagation();
        dispatch('play');
    }

    function onDeliveryChip(ev: Event): void {
        ev.stopPropagation();
        dispatch('toggleDeliveries');
    }

    function onDeliveryPlay(ev: CustomEvent<PublicDelivery>): void {
        dispatch('playDelivery', ev.detail);
    }
</script>

<div
    class="row"
    class:expanded={mode === 'expanded'}
    role="button"
    tabindex="0"
    on:click={() => dispatch('click')}
    on:keydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            dispatch('click');
        }
    }}
>
    {#if showPlay}
        <button
            type="button"
            class="play"
            aria-label="Play"
            on:click={onPlay}
        >▶</button>
    {:else}
        <span class="play-spacer" aria-hidden="true" />
    {/if}

    <span class="name">{reciter.name}</span>

    <StatePill state={reciter.primary_bucket} size="sm" />

    {#if reciter.deliveries_count > 0}
        <button
            type="button"
            class="delivery-chip"
            on:click={onDeliveryChip}
            aria-expanded={mode === 'expanded'}
        >deliveries: {reciter.deliveries_count}</button>
    {/if}

    {#if reciter.chapter_count_total > 0}
        <CoveragePill
            chapterCount={reciter.chapter_count_total}
            total={114 * Math.max(reciter.deliveries_count, 1)}
        />
    {/if}

    {#if reciter.riwayat.length > 0}
        <span class="meta">{reciter.riwayat.join(' · ')}</span>
    {/if}

    {#if reciter.country}
        <span class="meta dim">{reciter.country}</span>
    {/if}
</div>

{#if mode === 'expanded' && reciter.deliveries_count > 0}
    <div class="deliveries-pane">
        <DeliveriesTable
            deliveries={reciter.deliveries}
            variant="inline"
            on:play={onDeliveryPlay}
        />
    </div>
{/if}

<style>
    .row {
        display: grid;
        grid-template-columns: 36px minmax(180px, 2fr) auto auto auto auto auto;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
        transition: background var(--t-fast);
        cursor: pointer;
    }
    .row:hover,
    .row.expanded { background: var(--panel); }
    .row:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: -2px;
    }

    .play, .play-spacer {
        width: 28px; height: 28px;
        border-radius: 50%;
        border: 1px solid var(--border-default);
        background: transparent;
        color: var(--text-muted);
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .play-spacer { border: none; }
    .play:hover {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }

    .name {
        font-size: var(--fs-row);
        color: var(--text-primary);
        font-weight: 450;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
    }

    .meta {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        white-space: nowrap;
    }
    .meta.dim { color: var(--text-faint); }

    .delivery-chip {
        display: inline-flex;
        align-items: center;
        padding: 1px 6px;
        font-size: 10.5px;
        color: var(--text-secondary);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        font-variant-numeric: tabular-nums;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .delivery-chip:hover {
        color: var(--text-primary);
        border-color: var(--border-strong);
    }
    .row.expanded .delivery-chip {
        color: var(--accent);
        border-color: var(--accent);
    }

    .deliveries-pane {
        padding: var(--s-2) var(--s-2) var(--s-3) calc(36px + var(--s-3));
        background: var(--canvas-inset);
        border-bottom: 1px solid var(--border-quiet);
    }
</style>
