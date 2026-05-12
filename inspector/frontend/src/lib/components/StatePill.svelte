<script lang="ts">
    /**
     * StatePill — leading dot + label for a six-bucket public state.
     * Mirrors the design `.state.state-*` classes from
     * `inspector/frontend/design/components.css`.
     */
    import type { PublicBucket } from '../types/public-state';

    export let state: PublicBucket;
    export let size: 'sm' | 'md' | 'lg' = 'md';

    const LABELS: Record<PublicBucket, string> = {
        available_for_request: 'Available for request',
        requested: 'Requested',
        available_for_review: 'Available for review',
        under_review: 'Under review',
        publishing: 'Publishing',
        published: 'Published',
    };

    $: bucketClass = `bucket-${state.replace(/_/g, '-')}`;
</script>

<span class="pill {bucketClass}" class:sm={size === 'sm'} class:lg={size === 'lg'}>
    <span class="dot" aria-hidden="true"></span>
    <span class="label">{LABELS[state]}</span>
</span>

<style>
    .pill {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        padding: 2px var(--s-2);
        font-size: var(--fs-meta);
        border-radius: 999px;
        line-height: 1.4;
        white-space: nowrap;
    }
    .dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: currentColor;
        flex-shrink: 0;
    }
    .pill.sm {
        font-size: 10.5px;
        padding: 1px var(--s-2);
    }
    .pill.lg {
        font-size: var(--fs-body);
        padding: 4px var(--s-3);
    }
    .pill.lg .dot { width: 8px; height: 8px; }

    .bucket-published        { color: var(--state-published-fg);         background: var(--state-published-bg); }
    .bucket-publishing       { color: var(--state-publishing-fg);        background: var(--state-publishing-bg); }
    .bucket-under-review     { color: var(--state-under-review-fg);      background: var(--state-under-review-bg); }
    .bucket-available-for-review { color: var(--state-available-fg);     background: var(--state-available-bg); }
    .bucket-requested        { color: var(--state-requested-fg);         background: var(--state-requested-bg); }
    .bucket-available-for-request{ color: var(--state-available-request-fg); background: var(--state-available-request-bg); }
</style>
