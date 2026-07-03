<script lang="ts">
    /**
     * Per-combination lifecycle timeline (4 nodes + 1 conditional).
     *
     * Renders the simplified lifecycle of a single delivery:
     *   requested → available_for_review → under_review → published
     *
     * Plus a conditional 5th node "Timestamps refreshed" when the delivery's
     * timestamps were regenerated after the first generation
     * (``ts_refresh_dates`` — latest date, ×N when repeated).
     *
     * Off-axis buckets:
     *   - available_for_request → no nodes reached, no current
     *
     * Dates: ``PublicDelivery.bucket_dates`` (modal-only) carries the full
     * chronological entry timestamps per bucket. Each node shows its
     * first-reached date; nodes visited more than once expose every entry in a
     * hover tooltip. Nodes ABOVE the current bucket render an em dash even if
     * previously reached (a regressed delivery — e.g. un-published back to
     * under-review — only shows dates for its current position and below).
     */
    import { i18n } from '../../../lib/i18n/locale.svelte';
    import * as m from '../../../lib/paraglide/messages';
    import type { PublicDelivery } from '../../../lib/types/generated/schemas';
    import { PUBLIC_BUCKET_LABELS, type PublicBucket } from '../../../lib/types/public-bucket';

    let { delivery = null }: { delivery?: PublicDelivery | null } = $props();

    const AXIS: readonly PublicBucket[] = [
        'requested',
        'available_for_review',
        'under_review',
        'published',
    ] as const;

    function fmtDate(iso: string): string {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return '';
        return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }

    function fmtDateTime(iso: string): string {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
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

    const bucket = $derived(delivery?.bucket ?? null);
    const currentIdx = $derived(reachedIndex(bucket));
    const bucketDates = $derived(delivery?.bucket_dates ?? {});
    const tsRefreshDates = $derived(delivery?.ts_refresh_dates ?? []);

    interface TimelineItem {
        id: string;
        label: string;
        reached: boolean;
        current: boolean;
        date: string;
        visits: number;
        tooltip: string;
    }

    const items = $derived.by<TimelineItem[]>(() => {
        void i18n.locale; // re-derive labels/tooltips on locale switch
        const axis: TimelineItem[] = AXIS.map((b, i) => {
            const reached = i <= currentIdx;
            const entries = bucketDates[b] ?? [];
            // First-reached as the node date; fall back to state_since for the
            // current node when transition history is unavailable (legacy rows).
            let date = '';
            const firstEntry = entries[0];
            if (reached && firstEntry) {
                date = fmtDate(firstEntry);
            } else if (i === currentIdx && delivery?.state_since) {
                date = fmtDate(delivery.state_since);
            }
            const visits = reached ? entries.length : 0;
            const tooltip = visits > 1
                ? m.dashboard_timeline_tooltip_entered_count({
                      label: PUBLIC_BUCKET_LABELS[b](),
                      count: visits,
                      dates: entries.map(fmtDateTime).join('\n'),
                  })
                : '';
            return { id: b, label: PUBLIC_BUCKET_LABELS[b](), reached, current: i === currentIdx, date, visits, tooltip };
        });

        // Conditional 5th node — timestamp regenerations (every TS generation
        // after the first). Shows the LATEST refresh date + ×N when repeated.
        if (tsRefreshDates.length > 0) {
            const latest = tsRefreshDates[tsRefreshDates.length - 1]!;
            const visits = tsRefreshDates.length;
            axis.push({
                id: 'ts_refreshed',
                label: m.dashboard_timeline_node_ts_refreshed(),
                reached: true,
                current: false,
                date: fmtDate(latest),
                visits,
                tooltip: visits > 1
                    ? m.dashboard_timeline_tooltip_ts_refreshed_count({
                          count: visits,
                          dates: tsRefreshDates.map(fmtDateTime).join('\n'),
                      })
                    : m.dashboard_timeline_tooltip_ts_refreshed_single({ datetime: fmtDateTime(latest) }),
            });
        }
        return axis;
    });
</script>

<!-- dir="ltr" island: nodes are laid out chronologically left→right (requested →
     published) with connectors offset by physical left/right; the axis must not
     mirror under RTL. -->
<div class="timeline" role="list" dir="ltr" aria-label={m.dashboard_timeline_aria_label()}>
    <div class="axis"></div>
    <ol class="nodes" style="grid-template-columns: repeat({items.length}, 1fr)">
        {#each items as item, i (item.id)}
            <li
                class="node"
                class:reached={item.reached}
                class:current={item.current}
                role="listitem"
                title={item.tooltip || undefined}
            >
                <span class="dot" aria-hidden="true"></span>
                <div class="meta">
                    <div class="label">{item.label}</div>
                    {#if item.date}
                        <div class="date">
                            {item.date}{#if item.visits > 1}<span class="repeat" aria-label={m.dashboard_timeline_repeat_aria_label({ count: item.visits })}>×{item.visits}</span>{/if}
                        </div>
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
        grid-template-columns: repeat(4, 1fr);  /* overridden inline by node count */
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
    .repeat {
        margin-left: 3px;
        padding: 0 3px;
        border-radius: 4px;
        background: var(--accent-tint-soft);
        color: var(--accent);
        font-size: 9px;
        font-weight: 600;
        vertical-align: top;
    }
    .node[title] { cursor: help; }
</style>
