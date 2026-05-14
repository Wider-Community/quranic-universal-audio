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
    import { combinationStandard } from '../../utils/delivery-label';
    import { compareDeliveries } from '../../utils/delivery-sort';
    import StatePill from '../StatePill.svelte';

    export let reciter: PublicReciter | null;
    export let delivery: PublicDelivery | null;
    export let surahNum: number | null = null;
    export let speed: number = 1;

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
            <div class="body">
                <div class="name-row">
                    <span class="name">{reciter.name}</span>
                    {#if reciter.name_ar}
                        <span class="name-ar" dir="rtl">{reciter.name_ar}</span>
                    {/if}
                </div>
                <div class="sub">
                    {#if delivery}
                        <StatePill state={delivery.bucket} size="sm" />
                        <span class="sep" aria-hidden="true">|</span>
                        <span>Surah {surahNum ?? '—'}</span>
                        <span class="sep" aria-hidden="true">|</span>
                        <span class="mono">{speed}×</span>
                    {/if}
                </div>
            </div>
            {#if hasMany}
                <span class="switch" aria-hidden="true">⌃</span>
            {/if}
        {:else}
            <div class="body">
                <div class="name muted">Pick a reciter to start</div>
            </div>
        {/if}
    </button>

    {#if open && hasMany}
        <div class="dropup" role="listbox" aria-label="Switch combination">
            {#each combinations as d (d.slug)}
                {@const lines = combinationStandard(d)}
                <button
                    class="opt"
                    class:active={delivery?.slug === d.slug}
                    type="button"
                    role="option"
                    aria-selected={delivery?.slug === d.slug}
                    on:click={() => pick(d)}
                >
                    <span class="opt-main">{lines.line1}</span>
                    <span class="opt-meta">{lines.line2}</span>
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
    .body { min-width: 0; flex: 1 1 auto; }
    .name-row {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        min-width: 0;
    }
    .name {
        font-size: var(--fs-body);
        color: var(--text-primary);
        font-weight: 500;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .name.muted { color: var(--text-muted); font-weight: 400; }
    .name-ar {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        font-family: var(--font-arabic, inherit);
    }
    .sub {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .sep { color: var(--border-default); user-select: none; }
    .mono { font-family: var(--font-mono); font-size: 10.5px; }
    .switch {
        color: var(--text-faint);
        font-size: 14px;
        transition: color var(--t-fast);
    }
    .meta.interactive:hover .switch { color: var(--text-secondary); }

    .dropup {
        position: absolute;
        bottom: calc(100% + var(--s-2));
        left: 0;
        min-width: 280px;
        max-width: 420px;
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
        gap: 1px;
    }
    .opt {
        display: flex;
        flex-direction: column;
        gap: 2px;
        padding: 6px var(--s-2);
        background: transparent;
        border: 0;
        border-radius: var(--r-2);
        cursor: pointer;
        text-align: left;
        color: var(--text-secondary);
    }
    .opt:hover { background: var(--canvas-inset); color: var(--text-primary); }
    .opt.active { background: var(--canvas-inset); color: var(--accent); }
    .opt-main { font-size: var(--fs-meta); }
    .opt-meta {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
    }
</style>
