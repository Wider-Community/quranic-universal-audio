<script lang="ts">
    /**
     * Browse-by-state strip — quick scope chips beside the reciter chip.
     * Clicking any chip opens the ReciterPicker pre-filtered to that
     * bucket. Counts pull from /api/public/stats.
     */
    import { onMount } from 'svelte';

    import { fetchPublicStats } from '../../../../lib/api/public-reciters';
    import FilterPill from '../../../../lib/components/FilterPill.svelte';
    import ReciterPicker, {
        type PickerSelection,
    } from '../../../../lib/components/picker/ReciterPicker.svelte';
    import type { BucketCounts, PublicBucket } from '../../../../lib/types/public-state';
    import { createEventDispatcher } from 'svelte';

    const dispatch = createEventDispatcher<{
        change: { slug: string; name: string; bucket: PublicBucket };
    }>();

    let stats: BucketCounts | null = null;
    let openBucket: PublicBucket | null = null;

    onMount(async () => {
        try {
            stats = await fetchPublicStats();
        } catch {
            stats = null;
        }
    });

    function open(bucket: PublicBucket): void {
        openBucket = bucket;
    }

    function onSelect(ev: CustomEvent<PickerSelection>): void {
        const { reciter, delivery } = ev.detail;
        if (!delivery) return;
        dispatch('change', {
            slug: delivery.slug,
            name: reciter.name,
            bucket: reciter.primary_bucket,
        });
        openBucket = null;
    }

    function count(b: PublicBucket): number {
        return stats?.[b] ?? 0;
    }
</script>

<div class="strip">
    <span class="label">Browse</span>
    <FilterPill
        label="Available"
        count={count('available_for_review')}
        empty={count('available_for_review') === 0}
        on:click={() => open('available_for_review')}
    />
    <FilterPill
        label="Under review"
        count={count('under_review')}
        empty={count('under_review') === 0}
        on:click={() => open('under_review')}
    />
    <FilterPill
        label="Published"
        count={count('published')}
        empty={count('published') === 0}
        on:click={() => open('published')}
    />
</div>

{#if openBucket}
    <ReciterPicker
        open={openBucket !== null}
        mode="modal"
        title="Pick a reciter"
        initialFilter={{ bucket: openBucket }}
        on:select={onSelect}
        on:close={() => (openBucket = null)}
    />
{/if}

<style>
    .strip {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2) 0 var(--s-3);
        flex-wrap: wrap;
    }
    .label {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
        margin-right: var(--s-2);
    }
</style>
