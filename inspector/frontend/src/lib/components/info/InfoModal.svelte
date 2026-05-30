<script lang="ts">
    /**
     * Info modal — onboarding "what is this place?" for first-time visitors,
     * opened from the ⓘ button beside Submit recitation on the dashboard.
     *
     * Content lives in `overview.md` (imported `?raw`) and is rendered through
     * the tiny `info-doc` parser. Single tabless document for now; the parser
     * already returns a flat block list, so adding more docs / a tab strip
     * later is a wrapper change, not a rewrite. The lifecycle directive renders
     * the five public-bucket `StatePill`s so the colors match the catalog 1:1.
     */
    import Modal from '../../../../lib/components/Modal.svelte';
    import StatePill from '../../../../lib/components/StatePill.svelte';

    import { type InlineToken, parseInfoDoc } from './info-doc';
    import OVERVIEW_MD from './overview.md?raw';

    let { open = false, onClose }: { open?: boolean; onClose: () => void } = $props();

    const doc = parseInfoDoc(OVERVIEW_MD);
</script>

{#snippet inline(tokens: InlineToken[])}{#each tokens as t, i (i)}{#if t.bold}<strong>{t.text}</strong>{:else}{t.text}{/if}{/each}{/snippet}

<Modal {open} title={doc.title} on:close={onClose}>
    <div class="info-doc">
        {#each doc.blocks as block, i (i)}
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
</Modal>

<style>
    .info-doc {
        padding: var(--s-5) var(--s-6) var(--s-6);
        max-width: 640px;
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
