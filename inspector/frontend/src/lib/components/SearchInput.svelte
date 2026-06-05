<script context="module" lang="ts">
    /**
     * Canonical search input — magnifying-glass icon on the left, optional
     * inline "X of Y" count on the right. Layout (width, container) is the
     * caller's job; this component owns input chrome only.
     *
     * Used by CombinationPicker (modal search) and CatalogList (dashboard).
     * Add `debounceMs` if a consumer ever needs throttled input.
     */
    export interface SearchInputEvents { input: string; }
</script>

<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    export let value = '';
    export let placeholder = 'Search';
    export let count: number | null = null;
    export let total: number | null = null;
    export let ariaLabel: string | undefined = undefined;

    let inputEl: HTMLInputElement | null = null;
    export function focus(): void { inputEl?.focus(); }

    const dispatch = createEventDispatcher<SearchInputEvents>();

    function onInput(e: Event): void {
        dispatch('input', (e.target as HTMLInputElement).value);
    }

    $: countLabel = count !== null && total !== null ? `${count} of ${total}` : null;
</script>

<div class="search-input">
    <span class="icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.35-4.35" />
        </svg>
    </span>
    <input
        bind:this={inputEl}
        type="search"
        autocomplete="off"
        {placeholder}
        aria-label={ariaLabel ?? placeholder}
        {value}
        on:input={onInput}
    />
    {#if countLabel}<span class="count">{countLabel}</span>{/if}
</div>

<style>
    .search-input {
        position: relative;
        display: flex;
        align-items: center;
        width: 100%;
    }
    .icon {
        position: absolute;
        left: var(--s-3);
        top: 50%;
        transform: translateY(-50%);
        display: flex;
        color: var(--text-faint);
        pointer-events: none;
    }
    input {
        width: 100%;
        height: 32px;
        padding: 0 56px 0 calc(var(--s-3) + 24px);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-body);
        outline: none;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    input:focus {
        border-color: var(--accent);
        background: var(--panel-2);
    }
    input::placeholder { color: var(--text-faint); }
    /* Suppress the native ×; no custom clear button yet. */
    input::-webkit-search-cancel-button {
        -webkit-appearance: none;
        appearance: none;
        display: none;
    }
    .count {
        position: absolute;
        right: var(--s-3);
        top: 50%;
        transform: translateY(-50%);
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        pointer-events: none;
    }
</style>
