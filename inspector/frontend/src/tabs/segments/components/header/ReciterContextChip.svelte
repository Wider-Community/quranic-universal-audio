<script lang="ts">
    /**
     * Segments-tab reciter chip. Opens the CombinationPicker modal — the
     * picker commits a (reciter, delivery) pair; this component never
     * deals with audio.
     *
     * A right-side default slot holds inline action buttons (Claim /
     * Unclaim / Mark-ready) supplied by the parent.
     */
    import { createEventDispatcher } from 'svelte';

    import CombinationPicker, {
        type CombinationSelection,
    } from '../../../../lib/components/picker/CombinationPicker.svelte';
    import StatePill from '../../../../lib/components/StatePill.svelte';
    import type { PublicBucket } from '../../../../lib/types/public-state';

    export let currentSlug: string | null = null;
    export let currentName: string | null = null;
    export let currentBucket: PublicBucket | null = null;

    const dispatch = createEventDispatcher<{
        change: { slug: string; name: string; bucket: PublicBucket };
    }>();

    let pickerOpen = false;

    function onSelect(ev: CustomEvent<CombinationSelection>): void {
        const { reciter, delivery } = ev.detail;
        dispatch('change', {
            slug: delivery.slug,
            name: reciter.name,
            bucket: delivery.bucket,
        });
        pickerOpen = false;
    }
</script>

<div class="seg-chip-row">
    <div class="chip-wrap">
        <span class="label">Reciter</span>
        <button
            type="button"
            class="chip"
            on:click={() => (pickerOpen = true)}
            aria-haspopup="dialog"
        >
            <div class="chip-body">
                <div class="name">{currentName ?? (currentSlug ? 'Loading…' : 'Pick a reciter')}</div>
                {#if currentBucket}
                    <div class="meta">
                        <StatePill state={currentBucket} size="sm" />
                    </div>
                {/if}
            </div>
            <span class="switch" aria-hidden="true">⇄</span>
        </button>
    </div>
    {#if $$slots.default}
        <div class="seg-chip-row-actions">
            <slot />
        </div>
    {/if}
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
    .chip-wrap {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding: var(--s-5) 0 var(--s-2);
    }
    .label {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-faint);
    }
    .chip {
        width: 100%;
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: center;
        gap: var(--s-4);
        padding: var(--s-4) var(--s-5);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        text-align: left;
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .chip:hover {
        border-color: var(--border-strong);
        background: var(--panel-2);
    }
    .chip-body { min-width: 0; }
    .name {
        font-size: var(--fs-h3);
        color: var(--text-primary);
        font-weight: 500;
        letter-spacing: -0.005em;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .meta {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        margin-top: var(--s-1);
    }
    .switch {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        border-left: 1px solid var(--border-quiet);
        padding-left: var(--s-4);
        transition: color var(--t-fast);
    }
    .chip:hover .switch { color: var(--text-primary); }
</style>
