<script lang="ts">
    /**
     * Vertical state timeline rendered on the detail page.
     *
     * Derives a synthetic progression from the reciter's union of
     * observed buckets — there's no per-event audit feed here in
     * Slice G (that's slice H). Each item shows a colored dot plus a
     * state label and the most-recent activity date when known.
     */
    import type { PublicBucket, PublicReciter } from '../../../lib/types/public-state';
    import { relativeTime } from '../../../lib/utils/relative-time';

    export let reciter: PublicReciter;

    const ORDER: readonly PublicBucket[] = [
        'available_for_request',
        'requested',
        'available_for_review',
        'under_review',
        'publishing',
        'published',
    ];

    const LABELS: Record<PublicBucket, string> = {
        available_for_request: 'Available for request',
        requested: 'Requested',
        available_for_review: 'Available to claim',
        under_review: 'Under review',
        publishing: 'Publishing',
        published: 'Published',
    };

    $: items = ORDER.map((bucket) => ({
        bucket,
        reached: reciter.buckets.includes(bucket) || bucket === reciter.primary_bucket,
        current: bucket === reciter.primary_bucket,
    }));

    $: lastActivityRel = reciter.last_activity ? relativeTime(reciter.last_activity) : null;

    function dotClass(bucket: PublicBucket): string {
        return `dot dot-${bucket.replace(/_/g, '-')}`;
    }
</script>

<ol class="timeline">
    {#each items as item (item.bucket)}
        <li class="item" class:current={item.current} class:reached={item.reached}>
            <span class={dotClass(item.bucket)} aria-hidden="true"></span>
            <span class="label">{LABELS[item.bucket]}</span>
            {#if item.current && lastActivityRel}
                <span class="date">{lastActivityRel}</span>
            {/if}
        </li>
    {/each}
</ol>

<style>
    .timeline {
        list-style: none;
        padding: 0;
        margin: 0;
        position: relative;
        padding-left: 8px;
    }
    .item {
        display: grid;
        grid-template-columns: 14px 1fr auto;
        gap: var(--s-3);
        padding: var(--s-2) 0;
        align-items: baseline;
        position: relative;
        opacity: 0.5;
    }
    .item.reached { opacity: 1; }
    .item::before {
        content: '';
        position: absolute;
        left: 5px;
        top: 22px;
        bottom: -8px;
        width: 1px;
        background: var(--border-quiet);
    }
    .item:last-child::before { display: none; }
    .dot {
        width: 10px; height: 10px;
        border-radius: 50%;
        background: var(--border-default);
        margin-top: 6px;
        border: 2px solid var(--canvas);
        box-shadow: 0 0 0 1px var(--border-default);
    }
    .item.current .dot {
        box-shadow: 0 0 0 1px currentColor;
    }
    .dot-available-for-request { color: var(--state-available-request-fg); }
    .dot-requested             { color: var(--state-requested-fg); }
    .dot-available-for-review  { color: var(--state-available-fg); }
    .dot-under-review          { color: var(--state-under-review-fg); }
    .dot-publishing            { color: var(--state-publishing-fg); }
    .dot-published             { color: var(--state-published-fg); }
    .item.reached .dot,
    .item.current .dot { background: currentColor; }

    .label {
        font-size: var(--fs-body);
        color: var(--text-secondary);
    }
    .item.current .label {
        color: var(--text-primary);
        font-weight: 500;
    }
    .date {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--text-faint);
        white-space: nowrap;
    }
</style>
