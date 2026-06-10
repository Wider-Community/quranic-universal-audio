<script context="module" lang="ts">
    import type { PublicDelivery, PublicReciter } from '../../../lib/types/generated/schemas';

    export interface RowEntry {
        reciter: PublicReciter;
        visibleDeliveries: PublicDelivery[];
    }
</script>

<script lang="ts">
    /**
     * Catalog list. Renders one row per reciter that has at least one
     * combination passing the active filters. Counts on each row reflect
     * the post-filter combinations for that reciter.
     */
    import { createEventDispatcher } from 'svelte';

    import ReciterRow from '../../../lib/components/ReciterRow.svelte';

    export let rows: RowEntry[];

    const dispatch = createEventDispatcher<{
        open: PublicReciter;
        play: RowEntry;
    }>();

    function isPlayable(d: PublicDelivery): boolean {
        return d.audio_category !== 'by_ayah';
    }
</script>

{#if rows.length === 0}
    <div class="empty">
        <p>No reciters match the current filters.</p>
    </div>
{:else}
    <div class="catalog">
        {#each rows as row (row.reciter.reciter_id)}
            <ReciterRow
                reciter={row.reciter}
                visibleDeliveries={row.visibleDeliveries}
                showPlay={row.visibleDeliveries.some(isPlayable)}
                on:click={() => dispatch('open', row.reciter)}
                on:play={() => dispatch('play', row)}
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
