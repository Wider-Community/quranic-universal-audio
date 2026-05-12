<script lang="ts">
    /** Inline delivery sub-picker expanded under a multi-delivery row. */
    import { createEventDispatcher } from 'svelte';

    import type { PublicDelivery } from '../../types/public-state';

    export let deliveries: PublicDelivery[];

    const dispatch = createEventDispatcher<{ pick: PublicDelivery }>();
</script>

<div class="dp">
    <div class="head">Pick a delivery</div>
    {#each deliveries as d}
        <button
            type="button"
            class="option"
            on:click|stopPropagation={() => dispatch('pick', d)}
        >
            <span class="mushaf">{d.source}</span>
            <span class="tech">{d.riwayah} · {d.style}{d.recording_context ? ` · ${d.recording_context}` : ''}</span>
            <span class="cta">Pick →</span>
        </button>
    {/each}
</div>

<style>
    .dp {
        padding: var(--s-2) var(--s-6) var(--s-3) calc(var(--s-6) + var(--s-3));
        background: var(--canvas-inset);
        border-left: 2px solid var(--accent);
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .head {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
        margin: var(--s-1) 0 var(--s-2);
    }
    .option {
        display: grid;
        grid-template-columns: 1fr auto auto;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-3);
        background: transparent;
        border: none;
        border-radius: var(--r-2);
        align-items: center;
        cursor: pointer;
        transition: background var(--t-fast);
        text-align: left;
    }
    .option:hover { background: var(--panel); }
    .mushaf {
        font-size: var(--fs-meta);
        color: var(--text-primary);
    }
    .tech {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
    }
    .cta {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
    }
    .option:hover .cta { color: var(--accent); }
</style>
