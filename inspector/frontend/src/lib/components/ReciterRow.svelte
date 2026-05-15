<script lang="ts">
    /**
     * ReciterRow — single catalog row primitive used by CatalogTable.
     *
     * Layout (left to right):
     *   [Play] [Name en + Arabic + country + state-stack] (spacer) [count pills]
     *
     * `visibleDeliveries` is the post-facet subset of the reciter's
     * combinations; counts shown on the row reflect that subset (so the
     * row "honors" the user's active filters).
     */
    import { createEventDispatcher } from 'svelte';

    import {
        BUCKET_PRIORITY,
        type PublicBucket,
        type PublicDelivery,
        type PublicReciter,
    } from '../types/public-state';
    import { countryName, titleCaseSlug } from '../utils/delivery-label';
    import StatePill from './StatePill.svelte';

    export let reciter: PublicReciter;
    export let visibleDeliveries: PublicDelivery[];
    export let showPlay = true;

    const dispatch = createEventDispatcher<{
        click: void;
        play: void;
    }>();

    function onPlay(ev: Event): void {
        ev.stopPropagation();
        dispatch('play');
    }

    // Buckets that drop out of the displayed pill stack as soon as any
    // non-suppressible bucket is present on the reciter's combinations.
    const SUPPRESSIBLE: ReadonlySet<PublicBucket> = new Set([
        'available_for_request',
        'requested',
    ]);

    $: visibleBuckets = computeVisibleBuckets(visibleDeliveries);
    $: combinationCount = visibleDeliveries.length;
    $: riwayahCount = new Set(visibleDeliveries.map((d) => d.riwayah)).size;
    $: styleCount = new Set(visibleDeliveries.map((d) => d.style)).size;

    function computeVisibleBuckets(dels: PublicDelivery[]): PublicBucket[] {
        const present = new Set<PublicBucket>(dels.map((d) => d.bucket));
        const nonSuppressible = [...present].filter((b) => !SUPPRESSIBLE.has(b));
        const survivors: ReadonlySet<PublicBucket> =
            nonSuppressible.length > 0 ? new Set(nonSuppressible) : present;
        return BUCKET_PRIORITY.filter((b) => survivors.has(b));
    }
</script>

<div
    class="row"
    role="button"
    tabindex="0"
    on:click={() => dispatch('click')}
    on:keydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            dispatch('click');
        }
    }}
>
    {#if showPlay}
        <button
            type="button"
            class="play"
            aria-label="Play {reciter.name}"
            on:click={onPlay}
            disabled={combinationCount === 0}
        >▶</button>
    {:else}
        <span class="play-spacer" aria-hidden="true"></span>
    {/if}

    <div class="left">
        <div class="name-line">
            <span class="name">{reciter.name}</span>
            {#if reciter.name_ar}
                <span class="name-ar" dir="rtl">{reciter.name_ar}</span>
            {/if}
            {#if reciter.country}
                <span class="country">{countryName(reciter.country)}</span>
            {/if}
        </div>
        {#if visibleBuckets.length > 0}
            <div class="states">
                {#each visibleBuckets as bucket (bucket)}
                    <StatePill state={bucket} size="sm" />
                {/each}
            </div>
        {/if}
    </div>

    <div class="right">
        {#if combinationCount > 0}
            <span class="pill">
                <span class="pill-n">{combinationCount}</span>
                {combinationCount === 1 ? 'combination' : 'combinations'}
            </span>
            <span class="pill">
                <span class="pill-n">{riwayahCount}</span>
                {riwayahCount === 1 ? 'riwayah' : 'riwayahs'}
            </span>
            <span class="pill">
                <span class="pill-n">{styleCount}</span>
                {styleCount === 1 ? 'style' : 'styles'}
            </span>
        {/if}
    </div>
</div>

<style>
    /* Row reads as a rounded pill: side-inset margin so the hover
       background doesn't bleed to the page edges, and a soft accent
       tint on hover that matches the ReciterChip family elsewhere.
       Bottom border dropped — at rounded radii a bottom rule looks
       cut off. Rhythm comes from row padding alone. */
    .row {
        display: grid;
        grid-template-columns: 36px minmax(0, 1fr) auto;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-3);
        margin-inline: var(--s-2);
        border-radius: var(--r-3);
        transition: background var(--t-fast), border-color var(--t-fast);
        cursor: pointer;
    }
    .row:hover {
        background: var(--accent-tint-soft);
    }
    .row:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: -2px;
        border-radius: var(--r-3);
    }

    .play, .play-spacer {
        width: 28px; height: 28px;
        border-radius: 50%;
        border: 1px solid var(--border-default);
        background: transparent;
        color: var(--text-muted);
        display: flex; align-items: center; justify-content: center;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .play-spacer { border: none; }
    .play:hover:not(:disabled) {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
    .play:disabled { opacity: 0.3; cursor: default; }

    .left {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .name-line {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        min-width: 0;
        flex-wrap: wrap;
    }
    .name {
        font-size: var(--fs-row);
        color: var(--text-primary);
        font-weight: 450;
    }
    .name-ar {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        font-family: var(--font-arabic, inherit);
    }
    .country {
        font-size: var(--fs-meta);
        color: var(--text-faint);
    }
    .states {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-2);
    }

    .right {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex-wrap: wrap;
        justify-content: flex-end;
    }
    .pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 8px;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        white-space: nowrap;
    }
    .pill-n {
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--text-primary);
    }
    @media (max-width: 720px) {
        .pill { font-size: 10.5px; padding: 1px 6px; }
    }
</style>
