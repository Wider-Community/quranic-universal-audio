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

    import { SEG_FILTER_FIELDS } from '../../../lib/utils/segments/filter-fields';
    import { SEG_FILTER_OPS } from '../../../lib/utils/segments/constants';
    import type { SegActiveFilter } from '../../../lib/stores/segments/filters';

    export let filter: SegActiveFilter;
    export let autoFocus: boolean = false;

    let inputEl: HTMLInputElement | null = null;

    onMount(() => {
        if (autoFocus && inputEl) inputEl.focus();
    });

    const dispatch = createEventDispatcher<{ change: void; remove: void }>();

    const DEBOUNCE_MS = 300;
    let debounceTimer: ReturnType<typeof setTimeout> | null = null;

    function onFieldChange(e: Event): void {
        filter.field = (e.currentTarget as HTMLSelectElement).value;
        dispatch('change');
    }

    function onOpChange(e: Event): void {
        filter.op = (e.currentTarget as HTMLSelectElement).value;
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
</script>

<div class="seg-filter-row">
    <select class="seg-filter-field" value={filter.field} on:change={onFieldChange}>
        {#each SEG_FILTER_FIELDS as f}
            <option value={f.value}>{f.label}</option>
        {/each}
    </select>
    <select class="seg-filter-op" value={filter.op} on:change={onOpChange}>
        {#each SEG_FILTER_OPS as op}
            <option value={op}>{op}</option>
        {/each}
    </select>
    <input
        bind:this={inputEl}
        class="seg-filter-value"
        type="number"
        step="any"
        placeholder="value"
        value={filter.value != null ? String(filter.value) : ''}
        on:input={onValueInput}
    />
    <button class="btn btn-sm btn-cancel seg-filter-remove" on:click={onRemove}>&times;</button>
</div>
