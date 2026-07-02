<script lang="ts">
    /**
     * FilterCondition — one row of the filter bar: field / op / value / remove.
     *
     * Debounce timer is component-local per pre-artifact note #3 (transient
     * implementation detail of the value input's handler).
     *
     * Emits 'change' when the row content settles after debounce or on field/
     * op change; emits 'remove' on the X button.
     */

    import { createEventDispatcher, onDestroy, onMount } from 'svelte';

    import { localeStore, tr } from '../../../../lib/i18n/locale-store';
    import * as m from '../../../../lib/paraglide/messages';
    import type { SegActiveFilter } from '../../stores/filters';
    import { SEG_FILTER_OPS } from '../../utils/constants';
    import { SEG_FILTER_FIELDS } from '../../utils/data/filter-fields';

    export let filter: SegActiveFilter;
    export let autoFocus: boolean = false;

    let inputEl: HTMLInputElement | null = null;

    onMount(() => {
        if (autoFocus && inputEl) inputEl.focus();
    });

    const dispatch = createEventDispatcher<{ change: void; remove: void }>();

    // 150ms: short enough to feel instant, long enough to skip intermediate keystrokes.
    const DEBOUNCE_MS = 150;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    function onFieldChange(): void {
        dispatch('change');
    }

    function onOpChange(): void {
        dispatch('change');
    }

    function onValueInput(e: Event): void {
        const v = parseFloat((e.currentTarget as HTMLInputElement).value);
        filter.value = isNaN(v) ? null : v;
        if (debounceTimer !== null) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            debounceTimer = null;
            dispatch('change');
        }, DEBOUNCE_MS);
    }

    function onRemove(): void {
        if (debounceTimer !== null) {
            clearTimeout(debounceTimer);
            debounceTimer = null;
        }
        dispatch('remove');
    }

    onDestroy(() => {
        if (debounceTimer !== null) clearTimeout(debounceTimer);
    });

    $: valuePlaceholder = tr($localeStore, m.segments_filter_value_placeholder());
    $: fieldOptions = tr($localeStore, SEG_FILTER_FIELDS.map((f) => ({ value: f.value, label: f.label() })));
</script>

<div class="seg-filter-row">
    <select class="seg-filter-field" bind:value={filter.field} on:change={onFieldChange}>
        {#each fieldOptions as f (f.value)}
            <option value={f.value}>{f.label}</option>
        {/each}
    </select>
    <select class="seg-filter-op" bind:value={filter.op} on:change={onOpChange}>
        {#each SEG_FILTER_OPS as op (op)}
            <option value={op}>{op}</option>
        {/each}
    </select>
    <input
        bind:this={inputEl}
        class="seg-filter-value"
        type="number"
        step="any"
        placeholder={valuePlaceholder}
        value={filter.value != null ? String(filter.value) : ''}
        on:input={onValueInput}
    />
    <button class="btn btn-sm btn-cancel seg-filter-remove" on:click={onRemove}>&times;</button>
</div>
