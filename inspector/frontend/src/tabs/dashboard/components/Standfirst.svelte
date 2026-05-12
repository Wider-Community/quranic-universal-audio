<script lang="ts">
    /**
     * Magazine-style intro sentence with six clickable bucket counts.
     * Clicking a count scopes the catalog via dashboard-state.
     */
    import { createEventDispatcher } from 'svelte';

    import type { BucketCounts, PublicBucket } from '../../../lib/types/public-state';

    export let stats: BucketCounts | null = null;

    const dispatch = createEventDispatcher<{ select: PublicBucket }>();

    function n(bucket: PublicBucket): number {
        return stats?.[bucket] ?? 0;
    }

    function click(bucket: PublicBucket): void {
        if (n(bucket) > 0) dispatch('select', bucket);
    }
</script>

<p class="standfirst">
    <strong>{stats ? Object.values(stats).reduce((a, b) => a + b, 0) : 0}</strong> reciters tracked.
    <button class="count" disabled={n('published') === 0} on:click={() => click('published')}>{n('published')} published</button>,
    <button class="count" disabled={n('publishing') === 0} on:click={() => click('publishing')}>{n('publishing')} publishing</button>,
    <button class="count" disabled={n('under_review') === 0} on:click={() => click('under_review')}>{n('under_review')} under review</button>.
    <button class="count" disabled={n('available_for_review') === 0} on:click={() => click('available_for_review')}>{n('available_for_review')} available to claim</button>,
    <button class="count" disabled={n('requested') === 0} on:click={() => click('requested')}>{n('requested')} requested</button>,
    <button class="count" disabled={n('available_for_request') === 0} on:click={() => click('available_for_request')}>{n('available_for_request')} available for request</button>.
</p>

<style>
    .standfirst {
        max-width: 880px;
        margin: var(--s-8) 0 var(--s-6);
        padding: 0 var(--gutter);
        font-size: var(--fs-h2);
        line-height: var(--lh-tight);
        color: var(--text-secondary);
        font-weight: 400;
        letter-spacing: -0.005em;
    }
    .standfirst :global(strong) {
        color: var(--text-primary);
        font-weight: 500;
    }
    .count {
        color: var(--text-primary);
        font-weight: 500;
        font-variant-numeric: tabular-nums;
        border: 0;
        background: transparent;
        border-bottom: 1px dotted var(--border-default);
        padding: 0 0 1px;
        cursor: pointer;
        font: inherit;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .count:hover:not(:disabled) {
        color: var(--accent);
        border-bottom-color: var(--accent);
    }
    .count:disabled {
        color: var(--text-faint);
        cursor: default;
        border-bottom-color: transparent;
    }
</style>
