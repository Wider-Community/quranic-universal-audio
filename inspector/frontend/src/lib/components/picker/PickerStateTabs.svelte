<script lang="ts">
    /**
     * Horizontal one-of-N bucket tab row at the top of the picker body.
     * "All" represents the unfiltered superset; the six buckets follow.
     */
    import { createEventDispatcher } from 'svelte';

    import FilterPill from '../FilterPill.svelte';
    import type { BucketCounts, PublicBucket } from '../../types/public-state';
    import { PICKER_BUCKETS } from '../../catalog/schema-descriptor';

    export let activeBucket: PublicBucket | null = null;
    export let totalCount = 0;
    export let counts: Partial<BucketCounts> = {};

    const dispatch = createEventDispatcher<{ select: PublicBucket | null }>();

    const LABELS: Record<PublicBucket, string> = {
        available_for_review: 'Available to claim',
        under_review: 'Under review',
        publishing: 'Publishing',
        published: 'Published',
        requested: 'Requested',
        available_for_request: 'Available for request',
    };
</script>

<div class="tabs" role="tablist" aria-label="State">
    <FilterPill
        label="All"
        count={totalCount}
        active={activeBucket === null}
        on:click={() => dispatch('select', null)}
    />
    {#each PICKER_BUCKETS as bucket (bucket)}
        {@const count = counts[bucket] ?? 0}
        <FilterPill
            label={LABELS[bucket]}
            count={count}
            active={activeBucket === bucket}
            empty={count === 0}
            on:click={() => dispatch('select', bucket)}
        />
    {/each}
</div>

<style>
    .tabs {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-1);
        padding: var(--s-3) var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
</style>
