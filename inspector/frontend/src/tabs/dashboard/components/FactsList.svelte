<script lang="ts">
    /**
     * Key/val facts list rendered in the detail-page side rail.
     *
     * Rows with null values are omitted entirely — no "Unknown" or "—"
     * placeholders. The shape stays consumer-driven so the parent
     * component decides which facts to show.
     */
    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';

    export let facts: { key: string; value: string | null }[] = [];

    $: shown = facts.filter((f) => f.value !== null && f.value !== '');
    $: factsHeading = tr($localeStore, m.dashboard_facts_heading());
</script>

{#if shown.length > 0}
    <dl class="facts">
        <dt class="head">{factsHeading}</dt>
        {#each shown as f}
            <div class="row">
                <dt class="key">{f.key}</dt>
                <dd class="val">{f.value}</dd>
            </div>
        {/each}
    </dl>
{/if}

<style>
    .facts {
        display: flex;
        flex-direction: column;
        margin: 0;
    }
    .head {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
        font-weight: 500;
        padding-bottom: var(--s-2);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-2);
    }
    .row {
        display: grid;
        grid-template-columns: 110px 1fr;
        gap: var(--s-3);
        padding: var(--s-2) 0;
        font-size: var(--fs-meta);
        border-bottom: 1px dashed var(--border-quiet);
    }
    .row:last-child { border-bottom: none; }
    .key {
        color: var(--text-muted);
        margin: 0;
    }
    .val {
        color: var(--text-primary);
        margin: 0;
    }
</style>
