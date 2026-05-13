<script lang="ts">
    /**
     * Horizontal state timeline. Nodes alternate above/below the axis;
     * labels + dates render on the same side as their node. Each of the
     * six lifecycle states is plotted; states the reciter has reached
     * are highlighted, the rest sit muted.
     *
     * Dates are derived from per-delivery `state_since`: for each bucket
     * we take the most-recent state_since across deliveries currently in
     * that bucket. Buckets that no delivery is currently in get no date.
     */
    import type { PublicBucket, PublicReciter } from '../../../lib/types/public-state';

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

    function fmtDate(iso: string | null): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        return d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    $: dateByBucket = (() => {
        const m = new Map<PublicBucket, string>();
        for (const d of reciter.deliveries) {
            if (!d.state_since) continue;
            const prev = m.get(d.bucket);
            if (!prev || d.state_since > prev) m.set(d.bucket, d.state_since);
        }
        return m;
    })();

    $: reachedSet = new Set<PublicBucket>([...reciter.buckets, reciter.primary_bucket]);

    $: items = ORDER.map((bucket, i) => ({
        bucket,
        label: LABELS[bucket],
        date: fmtDate(dateByBucket.get(bucket) ?? null),
        reached: reachedSet.has(bucket),
        current: bucket === reciter.primary_bucket,
        side: i % 2 === 0 ? 'up' : 'down' as 'up' | 'down',
    }));
</script>

<div class="timeline" role="list" aria-label="Reciter lifecycle">
    <div class="axis"></div>
    <ol class="nodes">
        {#each items as item (item.bucket)}
            <li
                class="node"
                class:reached={item.reached}
                class:current={item.current}
                class:up={item.side === 'up'}
                class:down={item.side === 'down'}
                role="listitem"
            >
                <div class="meta">
                    <div class="label">{item.label}</div>
                    {#if item.date}
                        <div class="date">{item.date}</div>
                    {:else}
                        <div class="date faint">—</div>
                    {/if}
                </div>
                <span class="dot" aria-hidden="true"></span>
                <span class="leader" aria-hidden="true"></span>
            </li>
        {/each}
    </ol>
</div>

<style>
    .timeline {
        position: relative;
        margin: var(--s-3) 0 var(--s-5);
        padding: var(--s-6) var(--s-2);
    }
    .axis {
        position: absolute;
        left: 0; right: 0;
        top: 50%;
        height: 1px;
        background: var(--border-quiet);
    }
    .nodes {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        position: relative;
        height: 120px;
    }
    .node {
        position: relative;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
    .dot {
        width: 11px; height: 11px;
        border-radius: 50%;
        background: var(--border-default);
        border: 2px solid var(--canvas);
        box-shadow: 0 0 0 1px var(--border-default);
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
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
    .leader {
        position: absolute;
        left: 50%;
        width: 1px;
        background: var(--border-quiet);
    }
    .node.up .leader {
        bottom: 50%;
        height: 22px;
    }
    .node.down .leader {
        top: 50%;
        height: 22px;
    }
    .meta {
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        text-align: center;
        white-space: nowrap;
        opacity: 0.5;
    }
    .node.reached .meta { opacity: 1; }
    .node.up .meta {
        bottom: calc(50% + 26px);
    }
    .node.down .meta {
        top: calc(50% + 26px);
    }
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
