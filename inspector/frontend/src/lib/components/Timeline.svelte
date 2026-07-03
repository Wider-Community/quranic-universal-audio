<script lang="ts">
    /** Generic event list: coloured dot + (optional mono slug) + text +
     * (optional muted "by" + tag pill) + right-aligned relative time. One
     * component for role / claims / requests / activity history. */
    interface TimelineItem {
        dot?: string; // '' | 'accent' | 'green' | 'amber' | 'violet'
        slug?: string | null;
        text?: string;
        by?: string | null;
        tag?: { label: string; kind: string } | null;
        when?: string | null;
    }
    let { items = [] }: { items?: TimelineItem[] } = $props();
</script>

<ul class="tl">
    {#each items as it, i (i)}
        <li>
            <span class="dot {it.dot ?? ''}"></span>
            <span class="ev">
                {#if it.slug}<span class="slugref">{it.slug}</span>{' '}{/if}
                {#if it.text}{it.text}{/if}
                {#if it.by}<span class="by">{it.by}</span>{/if}
                {#if it.tag}<span class="tag {it.tag.kind}">{it.tag.label}</span>{/if}
            </span>
            {#if it.when}<span class="when">{it.when}</span>{/if}
        </li>
    {/each}
</ul>

<style>
    .tl { list-style: none; margin: 0; padding: 0; }
    .tl li {
        display: grid;
        grid-template-columns: 14px 1fr auto;
        gap: var(--s-3);
        align-items: baseline;
        padding: var(--s-2) 0;
        border-bottom: 1px solid var(--border-quiet);
    }
    .tl li:last-child { border-bottom: none; }
    .dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: var(--border-strong);
        align-self: start;
        margin-top: 6px;
    }
    .dot.accent { background: var(--accent); }
    .dot.green { background: var(--state-published-fg); }
    .dot.amber { background: var(--state-error-fg); }
    .dot.violet { background: oklch(0.84 0.11 300); }
    .ev { color: var(--text-secondary); font-size: var(--fs-body); line-height: var(--lh-normal); min-width: 0; }
    .ev .slugref { font-family: var(--font-mono); color: var(--text-primary); font-size: 12px; }
    .ev .by { color: var(--text-muted); margin-inline-start: 4px; }
    .when {
        color: var(--text-faint);
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .tag {
        display: inline-flex;
        align-items: center;
        margin-inline-start: 6px;
        padding: 1px 7px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.02em;
    }
    .tag.accepted { color: var(--state-published-fg); background: var(--state-published-bg); }
    .tag.returned { color: var(--state-error-fg); background: oklch(0.86 0.13 75 / 0.14); }
    .tag.pending { color: var(--accent); background: var(--accent-tint); }
    .tag.discarded { color: var(--state-discarded-fg); background: var(--state-discarded-bg); }
</style>
