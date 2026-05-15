<script lang="ts">
    /**
     * Player meta chip — left side of BottomPlayer.
     * Shows current reciter + combination meta. When the reciter has more
     * than one combination, clicking opens a dropup to switch combination
     * (delivery). With a single combination, the chip is non-interactive.
     */
    import { createEventDispatcher } from 'svelte';

    import { clickOutside } from '../../actions/click-outside';
    import type { PublicDelivery, PublicReciter } from '../../types/public-state';
    import { combinationCompact } from '../../utils/delivery-label';
    import { compareDeliveries } from '../../utils/delivery-sort';
    import ReciterChip from '../ReciterChip.svelte';

    export let reciter: PublicReciter | null;
    export let delivery: PublicDelivery | null;

    const dispatch = createEventDispatcher<{ select: PublicDelivery }>();

    let open = false;

    // Only by_surah deliveries are playable — BottomPlayer's url lookup
    // is keyed by surah number and silently misses by_ayah sidecars.
    // Hide them from the switcher entirely.
    $: combinations = [...(reciter?.deliveries ?? [])]
        .filter((d) => d.audio_category !== 'by_ayah')
        .sort(compareDeliveries);
    $: hasMany = combinations.length > 1;

    function toggle(): void {
        if (!hasMany) return;
        open = !open;
    }

    function pick(d: PublicDelivery): void {
        open = false;
        if (delivery && d.slug === delivery.slug) return;
        dispatch('select', d);
    }
</script>

<div class="wrap" use:clickOutside={() => (open = false)}>
    <button
        class="meta"
        class:interactive={hasMany}
        type="button"
        on:click={toggle}
        disabled={!hasMany && !delivery}
        aria-expanded={hasMany ? open : undefined}
        aria-haspopup={hasMany ? 'listbox' : undefined}
    >
        {#if reciter}
            <ReciterChip
                name={reciter.name}
                nameAr={reciter.name_ar}
                country={reciter.country}
                subline={delivery ? combinationCompact(delivery) : null}
                bucket={delivery?.bucket ?? null}
            />
            {#if hasMany}
                <span class="switch" aria-hidden="true">⌃</span>
            {/if}
        {:else}
            <span class="name muted">Pick a reciter to start</span>
        {/if}
    </button>

    {#if open && hasMany && reciter}
        <div class="dropup" role="listbox" aria-label="Switch combination">
            {#each combinations as d (d.slug)}
                <button
                    class="opt"
                    class:active={delivery?.slug === d.slug}
                    type="button"
                    role="option"
                    aria-selected={delivery?.slug === d.slug}
                    on:click={() => pick(d)}
                >
                    <ReciterChip
                        name={reciter.name}
                        nameAr={reciter.name_ar}
                        country={reciter.country}
                        subline={combinationCompact(d)}
                        bucket={d.bucket}
                        variant="compact"
                    />
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .wrap {
        position: relative;
        min-width: 0;
    }
    .meta {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        min-width: 0;
        width: 100%;
        background: transparent;
        border: 0;
        padding: var(--s-2);
        text-align: left;
        cursor: default;
        border-radius: var(--r-2);
        transition: background var(--t-fast);
        color: inherit;
    }
    .meta.interactive { cursor: pointer; }
    .meta.interactive:hover { background: var(--panel-2); }
    .name {
        font-size: var(--fs-body);
        color: var(--text-primary);
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .name.muted { color: var(--text-muted); font-weight: 400; }
    .switch {
        color: var(--text-faint);
        font-size: 14px;
        transition: color var(--t-fast);
        margin-inline-start: auto;
    }
    .meta.interactive:hover .switch { color: var(--text-secondary); }

    .dropup {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        left: 0;
        min-width: 320px;
        max-width: 480px;
        max-height: min(360px, 50vh);
        overflow-y: auto;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
        z-index: 50;
        padding: var(--s-2);
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    /* Each option hosts a <ReciterChip> body. The button is just the
       click target — padding + rounded pill hover matches the catalog
       row + segments footer + combination picker so every "reciter
       picker" surface reads the same. */
    .opt {
        display: flex;
        align-items: center;
        padding: 6px var(--s-2);
        background: transparent;
        border: 0;
        border-radius: var(--r-2);
        cursor: pointer;
        text-align: left;
        transition: background var(--t-fast);
    }
    .opt:hover { background: var(--accent-tint-soft); }
    .opt.active { background: var(--accent-tint); }
</style>
