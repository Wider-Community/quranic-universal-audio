<script lang="ts">
    /** Picker header — title + close button + search field with kbd hint. */
    import { createEventDispatcher } from 'svelte';

    export let title = 'Switch reciter';
    export let search = '';
    export let resultsLabel: string | null = null;

    const dispatch = createEventDispatcher<{
        close: void;
        search: string;
    }>();

    let inputEl: HTMLInputElement | null = null;

    export function focusSearch(): void {
        inputEl?.focus();
    }

    function onInput(e: Event): void {
        const v = (e.target as HTMLInputElement).value;
        dispatch('search', v);
    }
</script>

<header class="head">
    <h2 class="title">{title}</h2>
    <button
        type="button"
        class="close"
        aria-label="Close picker"
        on:click={() => dispatch('close')}
    >×</button>
</header>

<div class="search">
    <span class="search-icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M21 21l-4.35-4.35" />
        </svg>
    </span>
    <input
        bind:this={inputEl}
        type="text"
        autocomplete="off"
        placeholder="Search reciters — name in English or Arabic"
        value={search}
        on:input={onInput}
    />
    {#if resultsLabel}
        <span class="hint">{resultsLabel}</span>
    {/if}
</div>

<style>
    .head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: var(--s-4) var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
    }
    .title {
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
        letter-spacing: 0.005em;
        margin: 0;
    }
    .close {
        width: 32px; height: 32px;
        display: flex; align-items: center; justify-content: center;
        color: var(--text-muted);
        background: transparent;
        border: none;
        border-radius: var(--r-2);
        font-size: 18px;
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .close:hover { color: var(--text-primary); background: var(--panel); }

    .search {
        padding: var(--s-4) var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
        position: relative;
        display: flex;
        align-items: center;
    }
    .search-icon {
        position: absolute;
        left: calc(var(--s-6) + var(--s-3));
        color: var(--text-faint);
        pointer-events: none;
    }
    .search input {
        width: 100%;
        padding: var(--s-3) var(--s-3) var(--s-3) calc(var(--s-3) + 24px);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font-size: var(--fs-body);
        outline: none;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .search input:focus {
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .search input::placeholder { color: var(--text-faint); }
    .hint {
        position: absolute;
        right: calc(var(--s-6) + var(--s-3));
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        pointer-events: none;
    }
</style>
