<script lang="ts">
    /**
     * SearchableSelect — filterable dropdown with keyboard navigation (arrows,
     * Enter, Escape) and Arabic text normalization. Emits a 'change' Svelte
     * event with the selected value.
     */

    import { createEventDispatcher, onMount } from 'svelte';

    import { localeStore, tr } from '../i18n/locale-store';
    import * as m from '../paraglide/messages';
    import type { SelectOption } from '../types/ui';
    import { filterByFields } from '../utils/fuzzy-match';

    export let options: SelectOption[] = [];
    export let value = '';
    export let placeholder = '--';
    export let className = '';

    const dispatch = createEventDispatcher<{ change: string }>();

    let inputEl: HTMLInputElement;
    let dropdownEl: HTMLDivElement;
    let inputValue = '';
    let isOpen = false;
    let highlightIdx = -1;
    let filtered: SelectOption[] = [];

    // Sync input display text when value prop changes from outside
    $: {
        const matched = options.find(o => o.value === value);
        if (!isOpen) inputValue = matched ? matched.label : '';
    }

    // Re-filter when options change
    $: if (options) filter(inputValue);

    $: noResultsLabel = tr($localeStore, m.common_select_no_results());

    function filter(q: string): void {
        filtered = filterByFields(options, q, o => [o.label, o.group]);
        highlightIdx = -1;
    }

    function open(): void {
        inputValue = '';
        filter('');
        isOpen = true;
    }

    function close(): void {
        isOpen = false;
        highlightIdx = -1;
        const matched = options.find(o => o.value === value);
        inputValue = matched ? matched.label : '';
    }

    function pick(opt: SelectOption): void {
        value = opt.value;
        inputValue = opt.label;
        close();
        dispatch('change', value);
    }

    function onInput(): void {
        filter(inputValue);
    }

    function onFocus(): void {
        open();
    }

    function onKey(e: KeyboardEvent): void {
        if (!isOpen) {
            if (e.key === 'ArrowDown' || e.key === 'Enter') { open(); e.preventDefault(); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            highlightIdx = Math.min(highlightIdx + 1, filtered.length - 1);
            scrollToHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            highlightIdx = Math.max(highlightIdx - 1, 0);
            scrollToHighlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const idx = highlightIdx >= 0 ? highlightIdx : 0;
            const opt = filtered[idx];
            if (opt) pick(opt);
        } else if (e.key === 'Escape') {
            close();
        }
    }

    function scrollToHighlight(): void {
        if (!dropdownEl) return;
        const el = dropdownEl.querySelector<HTMLElement>('.ss-highlight');
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    function onDocClick(e: MouseEvent): void {
        // Close if click is outside the wrapper
        const wrapper = inputEl?.closest('.ss-wrapper');
        if (wrapper && !wrapper.contains(e.target as Node)) close();
    }

    onMount(() => {
        document.addEventListener('click', onDocClick);
        return () => document.removeEventListener('click', onDocClick);
    });
</script>

<div class="ss-wrapper {className}">
    <input
        bind:this={inputEl}
        class="ss-input"
        type="text"
        {placeholder}
        bind:value={inputValue}
        on:focus={onFocus}
        on:input={onInput}
        on:keydown={onKey}
    />
    {#if isOpen}
        <div class="ss-dropdown" bind:this={dropdownEl}>
            {#each filtered as opt, i}
                {#if opt.group && (i === 0 || filtered[i - 1]?.group !== opt.group)}
                    <div class="ss-group-label">{opt.group}</div>
                {/if}
                <div
                    class="ss-option"
                    role="button"
                    tabindex="0"
                    class:ss-option-grouped={!!opt.group}
                    class:ss-highlight={i === highlightIdx}
                    on:mousedown|preventDefault={() => pick(opt)}
                >
                    {opt.label}
                </div>
            {/each}
            {#if filtered.length === 0}
                <div class="ss-empty">{noResultsLabel}</div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .ss-wrapper {
        position: relative;
        display: inline-block;
    }
    .ss-input {
        width: 100%;
        padding: 6px 10px;
        background: #16213e;
        color: #eee;
        border: 1px solid #333;
        border-radius: 4px;
        font-size: 0.9rem;
        cursor: pointer;
        box-sizing: border-box;
    }
    .ss-input:focus {
        outline: none;
        border-color: #4361ee;
    }
    .ss-dropdown {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        background: #16213e;
        border: 1px solid #333;
        border-top: none;
        border-radius: 0 0 4px 4px;
        max-height: 260px;
        overflow-y: auto;
        z-index: 100;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
    }
    .ss-option {
        padding: 6px 10px;
        cursor: pointer;
        font-size: 0.9rem;
        color: #eee;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ss-option-grouped {
        padding-left: 20px;
    }
    .ss-option:hover,
    .ss-highlight {
        background: #1a2a4e;
    }
    .ss-group-label {
        padding: 4px 10px 2px;
        font-size: 0.75rem;
        color: #888;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        background: #0f0f23;
    }
    .ss-empty {
        padding: 8px 10px;
        color: #666;
        font-size: 0.85rem;
        font-style: italic;
    }
</style>
