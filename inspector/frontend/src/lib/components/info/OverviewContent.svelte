<script lang="ts">
    /**
     * Project-overview body — the parsed `overview.md` rendered as headings,
     * prose, lists, links, and the five lifecycle `StatePill`s. Chrome-free
     * shared content: the dashboard wraps it in a narrow `Modal` (`InfoModal`),
     * and the segments first-edit gate renders it inside `AccordionGuideModal`
     * via the `::component{name="overview"}` directive. Edit wording in
     * `overview.md`.
     */
    import StatePill from '../StatePill.svelte';

    import type { InlineToken } from './info-doc';
    import { overviewDoc } from './overview';
</script>

{#snippet inline(tokens: InlineToken[])}{#each tokens as t, i (i)}{#if t.href}<a href={t.href} target="_blank" rel="noopener noreferrer">{t.text}</a>{:else if t.bold}<strong>{t.text}</strong>{:else}{t.text}{/if}{/each}{/snippet}

<div class="info-doc">
    {#each overviewDoc.blocks as block, i (i)}
        {#if block.type === 'heading'}
            <h3 class="info-h">{block.text}</h3>
        {:else if block.type === 'paragraph'}
            <p class="info-p">{@render inline(block.tokens)}</p>
        {:else if block.type === 'list'}
            <ul class="info-list">
                {#each block.items as item, j (j)}
                    <li>{@render inline(item)}</li>
                {/each}
            </ul>
        {:else if block.type === 'lifecycle'}
            <ul class="lifecycle">
                {#each block.rows as row (row.state)}
                    <li class="lifecycle-row">
                        <span class="lifecycle-pill"><StatePill state={row.state} size="sm" /></span>
                        <span class="lifecycle-text">{row.text}</span>
                    </li>
                {/each}
            </ul>
        {/if}
    {/each}
</div>

<style>
    .info-doc {
        padding: var(--s-5) var(--s-6) var(--s-6);
        color: var(--text-secondary);
        font-size: var(--fs-body);
        line-height: 1.62;
    }
    .info-h {
        margin: var(--s-6) 0 var(--s-2);
        font-size: var(--fs-body);
        font-weight: 600;
        color: var(--text-primary);
        letter-spacing: 0.01em;
    }
    .info-doc > :global(:first-child) {
        margin-top: 0;
    }
    .info-p {
        margin: 0 0 var(--s-3);
    }
    .info-p :global(strong) {
        color: var(--text-primary);
        font-weight: 600;
    }
    .info-list {
        margin: 0 0 var(--s-3);
        padding-left: var(--s-5);
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .info-list li {
        list-style: disc;
    }
    .info-list li :global(strong) {
        color: var(--text-primary);
        font-weight: 600;
    }
    .info-doc :global(a) {
        color: var(--accent);
        text-decoration: underline;
        text-underline-offset: 2px;
        text-decoration-color: var(--accent-tint, currentColor);
        transition: color var(--t-fast);
    }
    .info-doc :global(a:hover) {
        color: var(--accent-strong);
        text-decoration-color: currentColor;
    }
    .info-doc :global(a:focus-visible) {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
        border-radius: 2px;
    }

    .lifecycle {
        list-style: none;
        margin: var(--s-3) 0 var(--s-3);
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .lifecycle-row {
        display: grid;
        grid-template-columns: max-content 1fr;
        align-items: baseline;
        gap: var(--s-3);
    }
    .lifecycle-pill {
        display: inline-flex;
        align-self: start;
        padding-top: 2px;
    }
    .lifecycle-text {
        min-width: 0;
    }
</style>
