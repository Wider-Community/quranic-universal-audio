<script lang="ts">
    /**
     * SearchableSelect — Svelte port of shared/searchable-select.ts::SearchableSelect.
     *
     * Provides a filterable dropdown with keyboard navigation (arrows, Enter,
     * Escape) and Arabic text normalization. Emits a 'change' Svelte event with
     * the selected value.
     *
     * Consumers (tab index.ts files) continue to use the legacy class API from
     * shared/searchable-select.ts until their Svelte conversion in Waves 4-5.
     * The .ts file has a deprecation comment noting this Svelte component as
     * its replacement.
     */

    import { createEventDispatcher, onMount } from 'svelte';

    import type { SelectOption } from '../types/ui';

    export let options: SelectOption[] = [];
    export let value = '';
    export let placeholder = '--';

    const dispatch = createEventDispatcher<{ change: string }>();

    let inputEl: HTMLInputElement;
    let dropdownEl: HTMLDivElement;
    let inputValue = '';
    let isOpen = false;
    let highlightIdx = -1;
    let filtered: SelectOption[] = [];

    // Sync input display text when value prop changes from outside
    $: {
        const match = options.find(o => o.value === value);
        if (!isOpen) inputValue = match ? match.label : '';
    }

    // Re-filter when options change
    $: if (options) filter(inputValue);

    function normalizeArabic(str: string): string {
        return str
            .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED]/g, '')
            .replace(/[أإآٱ]/g, 'ا')
            .replace(/ة/g, 'ه')
            .replace(/ى/g, 'ي');
    }

    function filter(q: string): void {
        const norm = normalizeArabic(q.toLowerCase());
        filtered = norm
            ? options.filter(o =>
                normalizeArabic(o.label.toLowerCase()).includes(norm) ||
                normalizeArabic((o.group ?? '').toLowerCase()).includes(norm)
            )
            : [...options];
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
        const match = options.find(o => o.value === value);
        inputValue = match ? match.label : '';
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
            const opt = filtered[highlightIdx];
            if (highlightIdx >= 0 && opt) pick(opt);
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

<div class="ss-wrapper">
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
                <!-- svelte-ignore a11y-click-events-have-key-events -->
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <div
                    class="ss-option"
                    class:ss-option-grouped={!!opt.group}
                    class:ss-highlight={i === highlightIdx}
                    on:mousedown|preventDefault={() => pick(opt)}
                >
                    {opt.label}
                </div>
            {/each}
            {#if filtered.length === 0}
                <div class="ss-empty">No results</div>
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
