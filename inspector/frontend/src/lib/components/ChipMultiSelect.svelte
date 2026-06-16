<script lang="ts">
    /**
     * ChipMultiSelect — token-styled searchable multi-select (Svelte 5 runes).
     *
     * Selected values render as removable chips; an inline search input opens a
     * filtered dropdown of the remaining options. Reuses the app's Arabic-aware
     * fuzzy `filterByFields`. Keyboard: ↑/↓ move the highlight, Enter adds,
     * Escape closes, Backspace on an empty query removes the last chip.
     *
     * Generic — the email-prefs modal uses one instance for reciters and one
     * for riwayahs. The caller owns the value list via `onchange`.
     */
    import type { SelectOption } from '../types/ui';
    import { filterByFields } from '../utils/fuzzy-match';

    interface Props {
        options: SelectOption[];
        selected: string[];
        onchange: (_next: string[]) => void;
        placeholder?: string;
        emptyHint?: string;
        ariaLabel?: string;
        disabled?: boolean;
    }

    let {
        options,
        selected,
        onchange,
        placeholder = 'Search…',
        emptyHint,
        ariaLabel,
        disabled = false,
    }: Props = $props();

    let query = $state('');
    let open = $state(false);
    let highlight = $state(0);
    let inputEl = $state<HTMLInputElement | null>(null);
    let wrapEl = $state<HTMLDivElement | null>(null);

    const labelOf = $derived(new Map(options.map((o) => [o.value, o.label])));
    const selectedSet = $derived(new Set(selected));
    const available = $derived(options.filter((o) => !selectedSet.has(o.value)));
    const matches = $derived(filterByFields(available, query, (o) => [o.label]));

    function add(value: string): void {
        if (disabled || selectedSet.has(value)) return;
        onchange([...selected, value]);
        query = '';
        highlight = 0;
        inputEl?.focus();
    }

    function remove(value: string): void {
        if (disabled) return;
        onchange(selected.filter((v) => v !== value));
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            open = true;
            highlight = Math.min(highlight + 1, matches.length - 1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            highlight = Math.max(highlight - 1, 0);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const opt = matches[highlight] ?? matches[0];
            if (opt) add(opt.value);
        } else if (e.key === 'Escape') {
            if (open) {
                e.stopPropagation();
                open = false;
            }
        } else if (e.key === 'Backspace' && query === '' && selected.length > 0) {
            remove(selected[selected.length - 1]!);
        }
    }

    function onDocPointer(e: PointerEvent): void {
        if (wrapEl && !wrapEl.contains(e.target as Node)) open = false;
    }

    $effect(() => {
        if (typeof document === 'undefined') return;
        document.addEventListener('pointerdown', onDocPointer);
        return () => document.removeEventListener('pointerdown', onDocPointer);
    });
</script>

<div class="cms" class:disabled bind:this={wrapEl}>
    <div class="field" class:focused={open} role="group" aria-label={ariaLabel}>
        {#each selected as value (value)}
            <span class="chip">
                <span class="chip-label">{labelOf.get(value) ?? value}</span>
                <button
                    type="button"
                    class="chip-x"
                    aria-label={`Remove ${labelOf.get(value) ?? value}`}
                    {disabled}
                    onclick={() => remove(value)}>×</button>
            </span>
        {/each}
        <input
            bind:this={inputEl}
            class="cms-input"
            type="text"
            aria-label={ariaLabel}
            {placeholder}
            {disabled}
            bind:value={query}
            onfocus={() => (open = true)}
            oninput={() => {
                open = true;
                highlight = 0;
            }}
            onkeydown={onKey} />
    </div>

    {#if open && !disabled}
        <div class="menu" role="listbox" aria-label={ariaLabel}>
            {#if matches.length === 0}
                <div class="menu-empty">
                    {available.length === 0 ? 'All added' : 'No matches'}
                </div>
            {:else}
                {#each matches.slice(0, 60) as opt, i (opt.value)}
                    <button
                        type="button"
                        role="option"
                        aria-selected={i === highlight}
                        class="menu-item"
                        class:hl={i === highlight}
                        onmouseenter={() => (highlight = i)}
                        onclick={() => add(opt.value)}>{opt.label}</button>
                {/each}
            {/if}
        </div>
    {/if}

    {#if selected.length === 0 && emptyHint}
        <p class="hint">{emptyHint}</p>
    {/if}
</div>

<style>
    .cms {
        position: relative;
        min-width: 0;
    }
    .field {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 5px;
        padding: 5px 6px;
        min-height: 34px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        transition: border-color var(--t-fast);
    }
    .field.focused {
        border-color: var(--accent);
        box-shadow: 0 0 0 3px var(--accent-tint);
    }
    .cms.disabled .field {
        opacity: 0.55;
    }

    .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 4px 2px 9px;
        background: var(--elevated);
        border: 1px solid var(--border-default);
        border-radius: 999px;
        font-size: var(--fs-meta);
        color: var(--text-primary);
        max-width: 100%;
    }
    .chip-label {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .chip-x {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 16px;
        height: 16px;
        border: 0;
        border-radius: 50%;
        background: transparent;
        color: var(--text-muted);
        font-size: 14px;
        line-height: 1;
        cursor: pointer;
        flex-shrink: 0;
        transition:
            color var(--t-fast),
            background var(--t-fast);
    }
    .chip-x:hover {
        color: var(--text-primary);
        background: var(--panel);
    }

    .cms-input {
        flex: 1 1 90px;
        min-width: 90px;
        border: 0;
        background: transparent;
        color: var(--text-primary);
        font-size: var(--fs-body);
        padding: 2px 4px;
        outline: none;
    }
    .cms-input::placeholder {
        color: var(--text-muted);
    }

    .menu {
        position: absolute;
        top: calc(100% + 4px);
        left: 0;
        right: 0;
        z-index: 10;
        max-height: 220px;
        overflow-y: auto;
        padding: 4px;
        background: var(--panel-2);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        box-shadow: 0 12px 28px oklch(0 0 0 / 0.4);
        display: flex;
        flex-direction: column;
        gap: 1px;
    }
    .menu-item {
        text-align: left;
        border: 0;
        background: transparent;
        color: var(--text-secondary);
        font-size: var(--fs-body);
        padding: 6px 9px;
        border-radius: var(--r-1);
        cursor: pointer;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .menu-item.hl {
        background: var(--elevated);
        color: var(--text-primary);
    }
    .menu-empty {
        padding: 8px 9px;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        font-style: italic;
    }

    .hint {
        margin: 6px 2px 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
</style>
