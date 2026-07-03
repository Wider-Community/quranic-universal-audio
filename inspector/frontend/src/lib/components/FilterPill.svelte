<script lang="ts">
    /**
     * FilterPill — single faceted filter pill with count chip.
     * Three orthogonal states: active (selected), empty (count===0,
     * disabled), and idle. Click emits no payload; consumers carry the
     * facet/tag context themselves.
     */
    import { createEventDispatcher } from 'svelte';

    import { localizeDigits } from '$lib/i18n/format';
    import { localeStore, tr } from '$lib/i18n/locale-store';

    export let label: string;
    export let count: number | null = null;
    export let active = false;
    export let empty = false;
    export let sort = false;

    const dispatch = createEventDispatcher<{ click: void }>();
</script>

<button
    type="button"
    class="pill"
    class:active
    class:empty
    class:sort
    disabled={empty}
    on:click={() => dispatch('click')}
>
    <span class="label">{label}</span>
    {#if count !== null}
        <span class="pill-count">{tr($localeStore, localizeDigits(count))}</span>
    {/if}
</button>

<style>
    .pill {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        padding: var(--s-1) var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        transition: color var(--t-fast), background var(--t-fast),
                    border-color var(--t-fast), opacity var(--t-fast);
        white-space: nowrap;
        cursor: pointer;
    }
    .pill:hover:not(.empty):not(:disabled) {
        border-color: var(--border-strong);
        color: var(--text-primary);
    }
    .pill.active {
        background: var(--accent-tint);
        border-color: var(--accent);
        color: var(--text-primary);
    }
    .pill-count {
        font-size: 10.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        padding-inline-start: 2px;
    }
    .pill.active .pill-count { color: var(--accent-strong); }
    .pill.empty {
        opacity: 0.32;
        cursor: not-allowed;
    }
    .pill.sort { border-style: dashed; }
    .pill.sort.active { border-style: solid; }
</style>
