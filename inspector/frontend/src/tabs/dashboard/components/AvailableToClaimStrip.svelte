<script lang="ts">
    /**
     * Up to 5 cards for reciters in `available_for_review` — the "claim
     * me" content-first surface above the catalog table.
     *
     * Claim CTA is rendered but disabled when the user is anonymous;
     * the actual claim API lives in lib/api/claims-client.ts and isn't
     * wired up here in Slice F (visual scaffolding only). Slice F's
     * acceptance criteria are limited to filtering + browsing; claim
     * action lands when the segments-tab context strip (Slice J) and
     * the dashboard converge.
     */
    import { createEventDispatcher } from 'svelte';

    import type { PublicReciter } from '../../../lib/types/public-state';

    export let reciters: PublicReciter[] = [];
    export let maxItems = 5;

    const dispatch = createEventDispatcher<{
        open: PublicReciter;
        play: PublicReciter;
    }>();

    $: visible = reciters.slice(0, maxItems);
</script>

{#if visible.length > 0}
    <section class="strip">
        <header>
            <h2>Available to claim</h2>
            <span class="sub">{reciters.length} reciter{reciters.length === 1 ? '' : 's'} waiting for review</span>
        </header>
        <div class="list">
            {#each visible as r (r.name)}
                <article class="card">
                    <button
                        type="button"
                        class="play"
                        aria-label="Play"
                        on:click={() => dispatch('play', r)}
                    >▶</button>
                    <div class="body">
                        <button
                            type="button"
                            class="name"
                            on:click={() => dispatch('open', r)}
                        >{r.name}</button>
                        <div class="meta">
                            {#if r.riwayat.length > 0}
                                <span>{r.riwayat.join(' · ')}</span>
                            {/if}
                            {#if r.deliveries_count > 0}
                                <span class="dot-sep">·</span>
                                <span>{r.deliveries_count} delivery{r.deliveries_count === 1 ? '' : ' deliveries'}</span>
                            {/if}
                        </div>
                    </div>
                </article>
            {/each}
        </div>
    </section>
{/if}

<style>
    .strip {
        margin: var(--s-6) 0 var(--s-4);
    }
    header {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        padding-bottom: var(--s-3);
    }
    header h2 {
        font-size: var(--fs-h3);
        color: var(--text-primary);
        font-weight: 500;
        margin: 0;
    }
    .sub {
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .list {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
        gap: var(--s-3);
    }
    .card {
        display: grid;
        grid-template-columns: 48px 1fr;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-4);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .card:hover {
        border-color: var(--border-strong);
        background: var(--panel-2);
    }
    .play {
        width: 48px; height: 48px;
        border-radius: 50%;
        background: var(--canvas-inset);
        border: 1px solid var(--border-default);
        display: flex; align-items: center; justify-content: center;
        color: var(--text-secondary);
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .play:hover {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
    .body { min-width: 0; }
    .name {
        font-size: var(--fs-row);
        color: var(--text-primary);
        font-weight: 500;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        margin-bottom: 2px;
        background: transparent; border: 0; padding: 0;
        text-align: left;
        cursor: pointer;
    }
    .name:hover { color: var(--accent); }
    .meta {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        display: flex; align-items: center; gap: var(--s-2);
    }
    .dot-sep { color: var(--text-faint); }
</style>
