<script lang="ts">
    /**
     * Horizontal one-of-N bucket tab row at the top of the picker body.
     * "All" represents the unfiltered superset; the six buckets follow.
     */
    import { createEventDispatcher } from 'svelte';

    import { PICKER_BUCKETS } from '../../catalog/schema-descriptor';
    import { localeStore, tr } from '../../i18n/locale-store';
    import * as m from '../../paraglide/messages';
    import type { BucketCounts } from '../../types/generated/schemas';
    import { PUBLIC_BUCKET_LABELS, type PublicBucket } from '../../types/public-bucket';
    import FilterPill from '../FilterPill.svelte';

    export let activeBucket: PublicBucket | null = null;
    export let totalCount = 0;
    export let counts: Partial<BucketCounts> = {};
    export let allowedBuckets: readonly PublicBucket[] = PICKER_BUCKETS;

    const dispatch = createEventDispatcher<{ select: PublicBucket | null }>();

    // Re-evaluate the chrome labels when the ambient locale flips.
    $: allLabel = tr($localeStore, m.common_picker_tab_all());
    $: tabsAriaLabel = tr($localeStore, m.common_picker_tabs_aria_label());
    $: bucketLabel = (bucket: PublicBucket) => tr($localeStore, PUBLIC_BUCKET_LABELS[bucket]());

    // When the consumer narrows the bucket set, the "All" total no longer
    // matches the global reciter count — recompute it from `counts` instead.
    $: allTotal = allowedBuckets === PICKER_BUCKETS
        ? totalCount
        : allowedBuckets.reduce((acc, b) => acc + (counts[b] ?? 0), 0);
</script>

<div class="tabs" role="tablist" aria-label={tabsAriaLabel}>
    <FilterPill
        label={allLabel}
        count={allTotal}
        active={activeBucket === null}
        on:click={() => dispatch('select', null)}
    />
    {#each allowedBuckets as bucket (bucket)}
        {@const count = counts[bucket] ?? 0}
        <FilterPill
            label={bucketLabel(bucket)}
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
