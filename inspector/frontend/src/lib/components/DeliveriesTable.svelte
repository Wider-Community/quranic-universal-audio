<script lang="ts">
    /**
     * DeliveriesTable — Smithsonian-density mono table of deliveries.
     *
     * Two variants:
     *   - `inline` — compact table embedded under an expanded catalog row.
     *   - `detail` — full table on the reciter detail page (larger
     *     padding, dedicated `Play` action column, mushaf-name col).
     *
     * Slug is internal — never rendered in the DOM.
     */
    import { createEventDispatcher } from 'svelte';

    import type { PublicDelivery } from '../types/public-state';

    export let deliveries: PublicDelivery[];
    export let variant: 'inline' | 'detail' = 'inline';

    const dispatch = createEventDispatcher<{ play: PublicDelivery }>();

    function play(delivery: PublicDelivery, ev: Event): void {
        ev.stopPropagation();
        dispatch('play', delivery);
    }
</script>

{#if variant === 'inline'}
    <table class="deliveries inline">
        <thead>
            <tr>
                <th class="name">Mushaf</th>
                <th>Riwayah</th>
                <th>Style</th>
                <th>Source</th>
                <th class="num">Chapters</th>
            </tr>
        </thead>
        <tbody>
            {#each deliveries as d}
                <tr>
                    <td class="name">{d.source}</td>
                    <td>{d.riwayah}</td>
                    <td>{d.style}</td>
                    <td>{d.channel}</td>
                    <td class="num">{d.chapter_count}</td>
                </tr>
            {/each}
        </tbody>
    </table>
{:else}
    <table class="deliveries detail">
        <thead>
            <tr>
                <th class="mushaf">Mushaf</th>
                <th>Riwayah</th>
                <th>Style</th>
                <th>Source</th>
                <th class="mono">Chapters</th>
                <th aria-label="Play" />
            </tr>
        </thead>
        <tbody>
            {#each deliveries as d}
                <tr>
                    <td class="mushaf">{d.source}</td>
                    <td>{d.riwayah}</td>
                    <td>{d.style}</td>
                    <td>{d.channel}</td>
                    <td class="mono">{d.chapter_count}</td>
                    <td class="action">
                        <button
                            type="button"
                            class="player-btn"
                            aria-label="Play"
                            on:click={(ev) => play(d, ev)}
                        >▶</button>
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
{/if}

<style>
    .deliveries {
        width: 100%;
        border-collapse: collapse;
    }

    /* inline variant — Smithsonian density */
    .inline {
        font-family: var(--font-mono);
        font-size: 11.5px;
        color: var(--text-secondary);
    }
    .inline th,
    .inline td {
        text-align: left;
        padding: 4px var(--s-2);
        border-bottom: 1px dashed var(--border-quiet);
    }
    .inline th {
        color: var(--text-faint);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-size: 10px;
    }
    .inline tr:last-child td { border-bottom: none; }
    .inline td.name {
        color: var(--text-primary);
        font-family: var(--font-sans);
        font-size: var(--fs-meta);
    }
    .inline th.num,
    .inline td.num { text-align: right; font-variant-numeric: tabular-nums; }

    /* detail variant — full page */
    .detail thead th {
        text-align: left;
        padding: var(--s-2) var(--s-3);
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
        font-weight: 500;
        border-bottom: 1px solid var(--border-default);
    }
    .detail tbody td {
        padding: var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font-size: var(--fs-meta);
        vertical-align: middle;
    }
    .detail tbody tr { transition: background var(--t-fast); }
    .detail tbody tr:hover { background: var(--panel); }
    .detail tbody tr:last-child td { border-bottom: none; }
    .detail td.mushaf {
        color: var(--text-primary);
        font-size: var(--fs-body);
    }
    .detail td.mono,
    .detail th.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
    .detail td.action { width: 1%; padding: var(--s-2) var(--s-3); }
    .detail td.action .player-btn {
        width: 28px; height: 28px;
        display: flex; align-items: center; justify-content: center;
        background: transparent;
        border: 1px solid var(--border-default);
        border-radius: 50%;
        color: var(--text-muted);
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .detail td.action .player-btn:hover {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
</style>
