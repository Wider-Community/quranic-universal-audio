<script lang="ts">
    /**
     * Ayah picker — data-driven verse grid + numeric filter, mirroring the
     * SurahPopover style. Lifted from the segments-tab inline picker into a
     * reusable, store-free component: pass the available verse numbers and a
     * change callback. Seeking is the caller's job (it maps verse → ms).
     */
    import { onMount, tick } from 'svelte';

    interface Props {
        /** Verse numbers present in the current surah, ascending. */
        verses: number[];
        /** Currently-active verse (highlighted), or null. */
        value?: number | null;
        onChange: (verse: number) => void;
    }

    let { verses, value = null, onChange }: Props = $props();

    let query = $state('');
    let inputEl = $state<HTMLInputElement | undefined>(undefined);

    const filtered = $derived(
        query.trim()
            ? verses.filter((v) => String(v).includes(query.trim()))
            : verses,
    );

    onMount(async () => {
        await tick();
        inputEl?.focus();
    });

    function pick(v: number): void {
        onChange(v);
    }

    function onKeydown(ev: KeyboardEvent): void {
        if (ev.key === 'Enter' && filtered.length > 0) pick(filtered[0]!);
    }
</script>

<div class="wrap" role="dialog" aria-label="Ayah picker">
    <input
        bind:this={inputEl}
        bind:value={query}
        onkeydown={onKeydown}
        class="search"
        type="text"
        inputmode="numeric"
        placeholder="Jump to ayah…"
        autocomplete="off"
    />
    <div class="grid" role="listbox">
        {#each filtered as v (v)}
            <button
                type="button"
                class="cell"
                class:active={value === v}
                role="option"
                aria-selected={value === v}
                onclick={() => pick(v)}
            >{v}</button>
        {:else}
            <div class="empty">No matches</div>
        {/each}
    </div>
</div>

<style>
    .wrap {
        width: 100%;
        display: flex;
        flex-direction: column;
        max-height: min(420px, 70vh);
        overflow: hidden;
    }
    .search {
        flex: 0 0 auto;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        color: var(--text-primary);
        padding: 6px var(--s-2);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        outline: none;
        margin-bottom: var(--s-2);
    }
    .search:focus {
        border-color: var(--accent);
    }
    .grid {
        flex: 1 1 auto;
        min-height: 0;
        display: grid;
        grid-template-columns: repeat(8, 1fr);
        gap: 3px;
        overflow-y: auto;
        padding-bottom: 3px;
    }
    .cell {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 7px 4px;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        font-family: var(--font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        cursor: pointer;
        transition:
            border-color var(--t-fast),
            color var(--t-fast),
            background var(--t-fast);
    }
    .cell:hover {
        border-color: var(--border-strong);
        color: var(--text-primary);
        background: var(--panel-2);
    }
    .cell.active {
        border-color: var(--accent);
        color: var(--accent);
        background: var(--accent-tint);
    }
    .empty {
        grid-column: 1 / -1;
        padding: var(--s-3);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        text-align: center;
    }
</style>
