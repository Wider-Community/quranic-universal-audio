<script lang="ts">
    /**
     * Surah picker popover — single-click select. Plain scrollable list
     * with a text filter input; avoids the SearchableSelect double-click
     * (first click focuses input, second click selects).
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';

    import { getSurahInfo, surahInfoReady, surahOptionText } from '../../utils/surah-info';

    export let surahNums: number[] = [];
    export let value: number | null = null;

    let ready = false;
    let query = '';
    let inputEl: HTMLInputElement | null = null;

    onMount(async () => {
        await surahInfoReady;
        ready = true;
        await tick();
        inputEl?.focus();
    });

    interface Item {
        n: number;
        label: string;
    }

    $: items = ready
        ? surahNums.map((n) => {
              void getSurahInfo();
              return { n, label: surahOptionText(n) } as Item;
          })
        : [];
    $: filtered = query.trim()
        ? items.filter((it) => it.label.toLowerCase().includes(query.trim().toLowerCase()))
        : items;

    const dispatch = createEventDispatcher<{ change: number }>();

    function pick(n: number): void {
        dispatch('change', n);
    }

    function onKeydown(ev: KeyboardEvent): void {
        if (ev.key === 'Enter' && filtered.length > 0) {
            pick(filtered[0]!.n);
        }
    }
</script>

<div class="wrap" role="dialog" aria-label="Surah picker">
    <input
        bind:this={inputEl}
        bind:value={query}
        on:keydown={onKeydown}
        class="search"
        type="text"
        placeholder="Filter surahs…"
        autocomplete="off"
    />
    <div class="list" role="listbox">
        {#each filtered as it (it.n)}
            <button
                type="button"
                class="row"
                class:active={value === it.n}
                role="option"
                aria-selected={value === it.n}
                on:click={() => pick(it.n)}
            >
                <span class="num">{it.n}</span>
                <span class="label">{it.label.replace(/^\d+\s*/, '')}</span>
            </button>
        {:else}
            <div class="empty">No matches</div>
        {/each}
    </div>
</div>

<style>
    /* Inherit the wrapper width from the consumer so the popover never
     * overflows its anchor (the player-stack row in the segments footer
     * is ~232px wide; the dashboard's surah-trigger is ~140px). Each call
     * site sets an explicit width on its `.pop-*` container — we just
     * fill it. Clamps below cap the popover at a comfortable 320px max
     * even when the anchor is wider (e.g. the dashboard delivery cluster). */
    .wrap {
        width: 100%;
        max-width: 320px;
        min-width: 180px;
        display: flex;
        flex-direction: column;
        max-height: min(420px, 60vh);
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
    }
    .search:focus {
        border-color: var(--accent);
    }
    .list {
        flex: 1 1 auto;
        overflow-y: auto;
        margin-top: var(--s-2);
        display: flex;
        flex-direction: column;
        gap: 1px;
    }
    .row {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        padding: 6px var(--s-2);
        background: transparent;
        border: 0;
        text-align: left;
        color: var(--text-secondary);
        cursor: pointer;
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
    }
    .row:hover {
        background: var(--canvas-inset);
        color: var(--text-primary);
    }
    .row.active {
        background: var(--canvas-inset);
        color: var(--accent);
    }
    .num {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        min-width: 22px;
        text-align: right;
    }
    .row.active .num {
        color: var(--accent);
    }
    .label {
        flex: 1 1 auto;
    }
    .empty {
        padding: var(--s-3);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        text-align: center;
    }
</style>
