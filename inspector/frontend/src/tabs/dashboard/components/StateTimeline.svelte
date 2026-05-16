<script lang="ts">
    /**
     * Per-combination 4-state timeline.
     *
     * Renders the simplified lifecycle of a single delivery:
     *   requested → available_for_review → under_review → published
     *
     * Off-axis buckets:
     *   - available_for_request → no nodes reached, no current
     *
     * Dates: the wire-level ``PublicDelivery`` carries ``state_since`` only
     * for the current bucket, so only the current node shows a date — the
     * others render an em dash. (Full bucket_dates history would require
     * an audit-log replay on the backend; out of scope here.)
     */
    import { PUBLIC_BUCKET_LABELS, type PublicBucket, type PublicDelivery } from '../../../lib/types/public-state';

    export let delivery: PublicDelivery | null = null;

    const AXIS: readonly PublicBucket[] = [
        'requested',
        'available_for_review',
        'under_review',
        'published',
    ] as const;

    function fmtDate(iso: string | null): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }

    // Map any bucket to where it lands on the 4-node axis.
    // Returns the highest axis index considered "reached", or -1 for none.
    function reachedIndex(b: PublicBucket | null): number {
        if (b === null) return -1;
        switch (b) {
            case 'available_for_request': return -1;
            case 'requested':              return 0;
            case 'available_for_review':   return 1;
            case 'under_review':           return 2;
            case 'published':              return 3;
        }
    }

    $: bucket = delivery?.bucket ?? null;
    $: currentIdx = reachedIndex(bucket);
    $: dateLabel = delivery?.state_since ? fmtDate(delivery.state_since) : '';

    $: items = AXIS.map((b, i) => ({
        bucket: b,
        label: PUBLIC_BUCKET_LABELS[b],
        reached: i <= currentIdx,
        current: i === currentIdx,
        date: i === currentIdx ? dateLabel : '',
    }));
</script>

<div class="timeline" role="list" aria-label="Combination lifecycle">
    <div class="axis"></div>
    <ol class="nodes">
        {#each items as item, i (item.bucket)}
            <li
                class="node"
                class:reached={item.reached}
                class:current={item.current}
                role="listitem"
            >
                <span class="dot" aria-hidden="true"></span>
                <div class="meta">
                    <div class="label">{item.label}</div>
                    {#if item.date}
                        <div class="date">{item.date}</div>
                    {:else}
                        <div class="date faint">—</div>
                    {/if}
                </div>
                {#if i < items.length - 1}
                    <span class="connector" class:filled={item.reached && (items[i + 1]?.reached ?? false)} aria-hidden="true"></span>
                {/if}
            </li>
        {/each}
    </ol>
</div>

<style>
    .timeline {
        position: relative;
        padding: var(--s-4) var(--s-2) var(--s-3);
    }
    .axis { display: none; }
    .nodes {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        position: relative;
    }
    .node {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: var(--s-2);
    }
    .dot {
        width: 11px; height: 11px;
        border-radius: 50%;
        background: var(--border-default);
        border: 2px solid var(--canvas);
        box-shadow: 0 0 0 1px var(--border-default);
        z-index: 1;
    }
    .node.reached .dot {
        background: var(--accent);
        box-shadow: 0 0 0 1px var(--accent);
    }
    .node.current .dot {
        width: 13px; height: 13px;
        box-shadow: 0 0 0 1px var(--accent), 0 0 0 4px var(--accent-tint-soft);
    }
    .connector {
        position: absolute;
        top: 5px;
        left: calc(50% + 8px);
        right: calc(-50% + 8px);
        height: 1px;
        background: var(--border-quiet);
        z-index: 0;
    }
    .connector.filled { background: var(--accent); }
    .meta {
        text-align: center;
        white-space: nowrap;
        opacity: 0.55;
    }
    .node.reached .meta { opacity: 1; }
    .label {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .node.current .label {
        color: var(--text-primary);
        font-weight: 500;
    }
    .date {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
        margin-top: 2px;
    }
    .date.faint { opacity: 0.55; }
</style>
