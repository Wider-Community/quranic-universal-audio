<script lang="ts">
    /**
     * Dashboard catalog table — Smithsonian-density list of reciters.
     *
     * Renders the visible-after-filter slice; row click navigates to
     * the per-reciter detail view (Slice G). Inline delivery expansion
     * is wired but the BottomPlayer hook lands in Slice I.
     */
    import ReciterRow from '../../../lib/components/ReciterRow.svelte';
    import type { PublicDelivery, PublicReciter } from '../../../lib/types/public-state';
    import { createEventDispatcher } from 'svelte';

    export let reciters: PublicReciter[];

    let expandedKey: string | null = null;

    const dispatch = createEventDispatcher<{
        open: PublicReciter;
        play: PublicReciter;
        playDelivery: { reciter: PublicReciter; delivery: PublicDelivery };
    }>();

    function rowKey(r: PublicReciter): string {
        return r.name + (r.deliveries[0]?.slug ?? '');
    }

    function toggleExpand(r: PublicReciter): void {
        const k = rowKey(r);
        expandedKey = expandedKey === k ? null : k;
    }
</script>

{#if reciters.length === 0}
    <div class="empty">
        <p>No reciters match the current filters.</p>
    </div>
{:else}
    <div class="catalog">
        {#each reciters as r (rowKey(r))}
            <ReciterRow
                reciter={r}
                mode={expandedKey === rowKey(r) ? 'expanded' : 'compact'}
                on:click={() => dispatch('open', r)}
                on:play={() => dispatch('play', r)}
                on:toggleDeliveries={() => toggleExpand(r)}
                on:playDelivery={(ev) => dispatch('playDelivery', { reciter: r, delivery: ev.detail })}
            />
        {/each}
    </div>
{/if}

<style>
    .catalog {
        margin-top: var(--s-2);
        border-top: 1px solid var(--border-quiet);
    }
    .empty {
        padding: var(--s-12) var(--gutter);
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
</style>
