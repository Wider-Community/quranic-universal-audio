<script lang="ts">
    /**
     * Player meta chip — left side of BottomPlayer.
     * Shows current reciter + combination meta. When the reciter has more
     * than one combination, clicking opens a dropup to switch combination
     * (delivery). With a single combination, the chip is non-interactive.
     */
    import { createEventDispatcher } from 'svelte';

    import { catalogData } from '../../../tabs/dashboard/stores/catalog-data';
    import { clickOutside } from '../../actions/click-outside';
    import type { PublicDelivery, PublicReciter } from '../../types/generated/schemas';
    import { combinationCompact } from '../../utils/delivery-label';
    import { compareDeliveries } from '../../utils/delivery-sort';
    import ReciterChip from '../ReciterChip.svelte';
    import StatePill from '../StatePill.svelte';

    export let reciter: PublicReciter | null;
    export let delivery: PublicDelivery | null;

    const dispatch = createEventDispatcher<{ select: PublicDelivery }>();

    let open = false;

    // Resolve the LIVE reciter + delivery from the shared `catalogData`
    // snapshot — the playerContext cache the BottomPlayer hands us is
    // frozen from whenever the user first picked the row, so its bucket
    // values drift out of sync with the dashboard modal after any state
    // change (request submitted, claim flipped, etc.). The dashboard
    // catalog list and ReciterDetail both read from this same store,
    // so sourcing here keeps every pill on the same source of truth.
    // Falls through to the prop snapshot only while the catalog is still
    // loading or the reciter genuinely isn't in it.
    $: liveReciter = (() => {
        if (!reciter) return null;
        const live = $catalogData.reciters.find(
            (r) => r.reciter_id === reciter!.reciter_id,
        );
        return live ?? reciter;
    })();
    $: liveDelivery = (() => {
        if (!delivery) return null;
        const match = liveReciter?.deliveries.find((d) => d.slug === delivery!.slug);
        return match ?? delivery;
    })();

    // Only by_surah deliveries are playable — BottomPlayer's url lookup
    // is keyed by surah number and silently misses by_ayah sidecars.
    // Hide them from the switcher entirely.
    $: combinations = [...(liveReciter?.deliveries ?? [])]
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
        {#if liveReciter}
            <ReciterChip
                name={liveReciter.name}
                nameAr={liveReciter.name_ar}
                country={liveReciter.country}
                subline={liveDelivery ? combinationCompact(liveDelivery) : null}
                bucket={liveDelivery?.bucket ?? null}
            />
            {#if hasMany}
                <span class="switch" aria-hidden="true">⇄</span>
            {/if}
        {:else}
            <span class="name muted">Pick a reciter to start</span>
        {/if}
    </button>

    {#if open && hasMany && liveReciter}
        <div class="dropup" role="listbox" aria-label="Switch combination">
            {#each combinations as d (d.slug)}
                <button
                    class="opt"
                    class:active={liveDelivery?.slug === d.slug}
                    type="button"
                    role="option"
                    aria-selected={liveDelivery?.slug === d.slug}
                    on:click={() => pick(d)}
                >
                    <!-- Reciter name is already shown on the trigger; the
                         dropup lists combinations only so the eye isn't
                         re-parsing the same name on every row. -->
                    <span class="opt-subline">{combinationCompact(d)}</span>
                    <StatePill state={d.bucket} size="sm" />
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
    /* Pill-shaped wrapper — kept in lockstep with the segments footer's
       `.identity` button (tabs/segments/components/footer/SegmentsFooter.svelte)
       so both reciter-picker affordances read as the same surface. */
    .meta {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        max-width: 100%;
        min-width: 0;
        flex: 0 1 auto;
        padding: 5px var(--s-3) 5px 5px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: inherit;
        cursor: default;
        font: inherit;
        text-align: left;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .meta.interactive { cursor: pointer; }
    .meta.interactive:hover {
        border-color: var(--border-strong);
        background: var(--panel);
    }
    .meta:focus-visible { outline: none; border-color: var(--accent); }
    .meta:disabled { opacity: 0.7; cursor: default; }

    .name {
        font-size: var(--fs-body);
        color: var(--text-primary);
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        padding-inline: var(--s-2);
    }
    .name.muted { color: var(--text-muted); font-weight: 400; }

    .switch {
        margin-inline-start: var(--s-2);
        color: var(--text-faint);
        font-size: var(--fs-meta);
        transition: color var(--t-fast);
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
        gap: var(--s-2);
        padding: 6px var(--s-2);
        background: transparent;
        border: 0;
        border-radius: var(--r-2);
        cursor: pointer;
        text-align: left;
        transition: background var(--t-fast);
        color: var(--text-primary);
        font: inherit;
    }
    .opt-subline {
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .opt:hover { background: var(--accent-tint-soft); }
    .opt.active { background: var(--accent-tint); }
</style>
