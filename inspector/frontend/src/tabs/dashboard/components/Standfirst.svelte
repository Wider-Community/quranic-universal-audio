<script lang="ts">
    /**
     * Bucket count strip — six centered boxes, one per public bucket.
     * Clicking a box scopes the catalog via dashboard-state.
     * Disabled boxes (count === 0) don't dispatch.
     */
    import { createEventDispatcher } from 'svelte';

    import type { BucketCounts, PublicBucket } from '../../../lib/types/public-state';

    export let stats: BucketCounts | null = null;

    const dispatch = createEventDispatcher<{ select: PublicBucket }>();

    const ITEMS: { bucket: PublicBucket; label: string }[] = [
        { bucket: 'published',             label: 'Published' },
        { bucket: 'publishing',            label: 'Publishing' },
        { bucket: 'under_review',          label: 'Under review' },
        { bucket: 'available_for_review',  label: 'Available to claim' },
        { bucket: 'requested',             label: 'Requested' },
        { bucket: 'available_for_request', label: 'Available for request' },
    ];

    function n(b: PublicBucket): number {
        return stats?.[b] ?? 0;
    }

    function click(b: PublicBucket): void {
        if (n(b) > 0) dispatch('select', b);
    }

    function bucketClass(b: PublicBucket): string {
        return `card card-${b.replace(/_/g, '-')}`;
    }
</script>

<section class="strip">
    {#each ITEMS as item (item.bucket)}
        {@const count = n(item.bucket)}
        <button
            type="button"
            class={bucketClass(item.bucket)}
            class:empty={count === 0}
            disabled={count === 0}
            on:click={() => click(item.bucket)}
        >
            <div class="count">{count}</div>
            <div class="label">{item.label}</div>
        </button>
    {/each}
</section>

<style>
    .strip {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: var(--s-3);
        padding: var(--s-8) var(--gutter) var(--s-6);
    }
    @media (max-width: 1100px) {
        .strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 640px) {
        .strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    .card {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: var(--s-1);
        padding: var(--s-5) var(--s-3);
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-3);
        color: var(--text-primary);
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast), color var(--t-fast);
        min-height: 100px;
    }
    .card:hover:not(:disabled) {
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .card:disabled,
    .card.empty {
        cursor: default;
        opacity: 0.4;
    }
    .count {
        font-size: 2rem;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.015em;
        line-height: 1;
    }
    .label {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        text-align: center;
    }
    .card:hover:not(:disabled) .label { color: var(--text-secondary); }

    /* Per-bucket accent on the count number */
    .card-published .count        { color: var(--state-published-fg); }
    .card-publishing .count       { color: var(--state-publishing-fg); }
    .card-under-review .count     { color: var(--state-under-review-fg); }
    .card-available-for-review .count { color: var(--state-available-fg); }
    .card-requested .count        { color: var(--state-requested-fg); }
    .card-available-for-request .count { color: var(--state-available-request-fg); }
</style>
