<script lang="ts">
    /** Detail-page header — name + state pill + meta strip. */
    import StatePill from '../../../lib/components/StatePill.svelte';
    import type { PublicReciter } from '../../../lib/types/generated/schemas';

    export let reciter: PublicReciter;
</script>

<header class="detail-header">
    <h1 class="name">{reciter.name}</h1>
    <StatePill state={reciter.primary_bucket} size="lg" />
    <div class="meta">
        {#if reciter.country}
            <span>{reciter.country}</span>
        {/if}
        {#if reciter.riwayat.length > 0}
            {#if reciter.country}<span class="dot-sep">·</span>{/if}
            <span>{reciter.riwayat.join(' · ')}</span>
        {/if}
        {#if reciter.styles.length > 0}
            <span class="dot-sep">·</span>
            <span>{reciter.styles.join(' · ')}</span>
        {/if}
        {#if reciter.deliveries_count > 0}
            <span class="dot-sep">·</span>
            <span>{reciter.deliveries_count} delivery{reciter.deliveries_count === 1 ? '' : ' deliveries'}</span>
        {/if}
    </div>
</header>

<style>
    .detail-header {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        padding: var(--s-3) 0 var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-8);
    }
    .name {
        font-size: var(--fs-h1);
        line-height: var(--lh-tight);
        font-weight: 500;
        letter-spacing: -0.015em;
        color: var(--text-primary);
        margin: 0;
    }
    .meta {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--s-3);
        color: var(--text-secondary);
        font-size: var(--fs-body);
    }
    .dot-sep { color: var(--text-faint); }
</style>
