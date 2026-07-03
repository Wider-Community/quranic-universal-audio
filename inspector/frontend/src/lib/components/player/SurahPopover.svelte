<script lang="ts">
    /**
     * Surah picker popover — 6-column grid matching the ayah picker style.
     * Each cell: number (left, small, muted) · name_en / name_ar stacked right.
     */
    import { createEventDispatcher, onMount, tick } from 'svelte';

    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';

    import { getSurahInfo, surahInfoReady } from '../../utils/surah-info';

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
        nameEn: string;
        nameAr: string;
        /** Combined search key: number + English + Arabic, so filtering matches either script. */
        search: string;
    }

    $: items = ready
        ? surahNums.map((n) => {
              const info = getSurahInfo()[String(n)];
              const nameEn = info?.name_en ?? String(n);
              const nameAr = info?.name_ar.replace(/^سُورَةُ\s*/, '') ?? '';
              return { n, nameEn, nameAr, search: `${n} ${nameEn} ${nameAr}`.toLowerCase() } as Item;
          })
        : [];
    $: filtered = query.trim()
        ? items.filter((it) => it.search.includes(query.trim().toLowerCase()))
        : items;

    const dispatch = createEventDispatcher<{ change: number; hover: number }>();

    function pick(n: number): void {
        dispatch('change', n);
    }

    function hover(n: number): void {
        dispatch('hover', n);
    }

    function onKeydown(ev: KeyboardEvent): void {
        if (ev.key === 'Enter' && filtered.length > 0) {
            pick(filtered[0]!.n);
        }
    }

    $: pickerLabel = tr($localeStore, m.common_player_surah_picker_label());
    $: filterPlaceholder = tr($localeStore, m.common_player_surah_filter_placeholder());
    $: noMatches = tr($localeStore, m.common_player_surah_no_matches());
</script>

<div class="wrap" role="dialog" aria-label={pickerLabel}>
    <input
        bind:this={inputEl}
        bind:value={query}
        on:keydown={onKeydown}
        class="search"
        type="text"
        placeholder={filterPlaceholder}
        autocomplete="off"
    />
    <div class="grid" role="listbox">
        {#each filtered as it (it.n)}
            <button
                type="button"
                class="cell"
                class:active={value === it.n}
                role="option"
                aria-selected={value === it.n}
                on:click={() => pick(it.n)}
                on:pointerenter={() => hover(it.n)}
                on:focus={() => hover(it.n)}
            >
                <span class="num">{it.n}</span>
                <span class="names">
                    <span class="name-en">{it.nameEn}</span>
                    <span class="name-ar">{it.nameAr}</span>
                </span>
            </button>
        {:else}
            <div class="empty">{noMatches}</div>
        {/each}
    </div>
</div>

<style>
    .wrap {
        width: 100%;
        display: flex;
        flex-direction: column;
        /* 487px = 9 complete rows (447px grid) + 40px search+margin — avoids partial row clip */
        max-height: min(487px, 75vh);
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
        grid-template-columns: repeat(6, 1fr);
        gap: 3px;
        overflow-y: auto;
        padding-bottom: 3px;
    }
    .cell {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 4px;
        padding: 7px 6px;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        cursor: pointer;
        min-height: 47px;
        overflow: hidden;
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
    /* Fixed width reserves the same column for 1–114 */
    .num {
        font-family: var(--font-mono);
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
        width: 20px;
        flex-shrink: 0;
        text-align: end;
        color: var(--text-faint);
        line-height: 1;
    }
    .cell.active .num {
        color: var(--accent);
    }
    .names {
        display: flex;
        flex-direction: column;
        gap: 2px;
        overflow: hidden;
        flex: 1;
        min-width: 0;
    }
    .name-en {
        font-size: 10px;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--text-secondary);
    }
    .name-ar {
        font-size: 10.5px;
        line-height: 1.2;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        direction: rtl;
        color: var(--text-muted);
    }
    .cell:hover .name-en,
    .cell.active .name-en,
    .cell:hover .name-ar,
    .cell.active .name-ar {
        color: inherit;
    }
    .empty {
        grid-column: 1 / -1;
        padding: var(--s-3);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        text-align: center;
    }
</style>
