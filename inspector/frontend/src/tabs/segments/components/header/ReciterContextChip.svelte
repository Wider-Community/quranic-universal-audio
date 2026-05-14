<script lang="ts">
    /**
     * Segments-tab reciter chip. The chip itself is a horizontal row:
     * a borderless trigger button (opens the CombinationPicker) on the
     * left, then any inline claim/unclaim/mark-ready actions the parent
     * passes via the default slot — both share one bordered surface.
     */
    import { createEventDispatcher } from 'svelte';

    import CombinationPicker, {
        type CombinationSelection,
    } from '../../../../lib/components/picker/CombinationPicker.svelte';
    import StatePill from '../../../../lib/components/StatePill.svelte';
    import type { PublicBucket } from '../../../../lib/types/public-state';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';

    export let currentSlug: string | null = null;
    export let currentName: string | null = null;
    export let currentBucket: PublicBucket | null = null;
    export let currentRiwayah: string | null = null;
    export let currentStyle: string | null = null;

    const dispatch = createEventDispatcher<{
        change: {
            slug: string;
            name: string;
            bucket: PublicBucket;
            riwayah: string;
            style: string;
        };
    }>();

    let pickerOpen = false;

    $: chipMeta = [titleCaseSlug(currentRiwayah), titleCaseSlug(currentStyle)]
        .filter(Boolean)
        .join(' · ');

    function onSelect(ev: CustomEvent<CombinationSelection>): void {
        const { reciter, delivery } = ev.detail;
        dispatch('change', {
            slug: delivery.slug,
            name: reciter.name,
            bucket: delivery.bucket,
            riwayah: delivery.riwayah,
            style: delivery.style,
        });
        pickerOpen = false;
    }
</script>

<div class="seg-chip-row">
    <div class="chip">
        <button
            type="button"
            class="chip-trigger"
            on:click={() => (pickerOpen = true)}
            aria-haspopup="dialog"
        >
            <span class="chip-name">
                {currentName ?? (currentSlug ? 'Loading…' : 'Pick a reciter')}
            </span>
            {#if chipMeta}
                <span class="chip-meta">{chipMeta}</span>
            {/if}
            {#if currentBucket}
                <StatePill state={currentBucket} size="sm" />
            {/if}
            <span class="switch" aria-hidden="true">⇄</span>
        </button>
        {#if $$slots.default}
            <div class="chip-actions"><slot /></div>
        {/if}
    </div>
</div>

{#if pickerOpen}
    <CombinationPicker
        open={pickerOpen}
        title="Switch reciter"
        on:select={onSelect}
        on:close={() => (pickerOpen = false)}
    />
{/if}

<style>
    .seg-chip-row {
        /* Edge-to-edge inside the segments panel so the chip lines up with
         * the Shortcuts and Stats accordions above it. */
        margin-bottom: 8px;
    }
    .chip {
        display: flex;
        align-items: stretch;
        width: 100%;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .chip:hover { border-color: var(--border-strong); }
    .chip-trigger {
        flex: 1;
        min-width: 0;
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-4);
        background: transparent;
        border: 0;
        color: inherit;
        text-align: left;
        cursor: pointer;
        font: inherit;
    }
    .chip-name {
        flex: 0 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--fs-row);
        color: var(--text-primary);
        font-weight: 500;
    }
    .chip-meta {
        flex: 1 1 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .chip .switch {
        color: var(--text-faint);
        font-size: var(--fs-meta);
        margin-inline-start: var(--s-2);
        transition: color var(--t-fast);
    }
    .chip:hover .switch { color: var(--text-muted); }
    .chip-actions {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-2) var(--s-3);
        border-left: 1px solid var(--border-quiet);
    }
</style>
