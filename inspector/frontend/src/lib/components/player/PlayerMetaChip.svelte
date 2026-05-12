<script lang="ts">
    /**
     * Player meta chip — left side of BottomPlayer.
     * Shows current reciter + delivery line and opens the ReciterPicker
     * on click.
     */
    import { createEventDispatcher } from 'svelte';

    import StatePill from '../StatePill.svelte';
    import type { PublicDelivery, PublicReciter } from '../../types/public-state';

    export let reciter: PublicReciter | null;
    export let delivery: PublicDelivery | null;

    const dispatch = createEventDispatcher<{ open: void }>();
</script>

<button class="meta" type="button" on:click={() => dispatch('open')}>
    {#if reciter}
        <div class="body">
            <div class="name">{reciter.name}</div>
            <div class="sub">
                {#if delivery}
                    <span>{delivery.riwayah}</span>
                    <span class="dot-sep">·</span>
                    <span>{delivery.style}</span>
                    <span class="dot-sep">·</span>
                    <span>{delivery.source}</span>
                {/if}
                <StatePill state={reciter.primary_bucket} size="sm" />
            </div>
        </div>
        <span class="switch" aria-hidden="true">⇄</span>
    {:else}
        <div class="body">
            <div class="name muted">Pick a reciter to start</div>
        </div>
        <span class="switch" aria-hidden="true">⇄</span>
    {/if}
</button>

<style>
    .meta {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        min-width: 0;
        background: transparent;
        border: 0;
        padding: var(--s-2);
        text-align: left;
        cursor: pointer;
        border-radius: var(--r-2);
        transition: background var(--t-fast);
    }
    .meta:hover { background: var(--panel-2); }
    .body { min-width: 0; }
    .name {
        font-size: var(--fs-body);
        color: var(--text-primary);
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .name.muted { color: var(--text-muted); font-weight: 400; }
    .sub {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .dot-sep { color: var(--text-faint); }
    .switch {
        color: var(--text-faint);
        font-size: 14px;
        transition: color var(--t-fast);
    }
    .meta:hover .switch { color: var(--text-secondary); }
</style>
