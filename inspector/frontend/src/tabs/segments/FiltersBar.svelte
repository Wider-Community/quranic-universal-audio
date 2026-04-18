<script lang="ts">
    /**
     * FiltersBar — the segments filter bar (header + condition rows).
     *
     * Subscribes to `activeFilters`, `displayedResult` (for count label), and
     * `selectedVerse` (for "1/N" display when verse filter active). Writes to
     * `activeFilters` (add/clear). Clearing filters also clears
     * `savedFilterView` (see Navigation.svelte for the complementary rule that
     * clears it when filters become non-empty).
     */

    import { activeFilters, displayedResult } from '../../lib/stores/segments/filters';
    import { selectedVerse } from '../../lib/stores/segments/chapter';
    import { savedFilterView } from '../../lib/stores/segments/navigation';
    import FilterCondition from './FilterCondition.svelte';

    export let hidden: boolean = true;

    $: count = $activeFilters.length;
    $: countLabel = count > 0 ? `(${count})` : '';
    $: statusText = ($activeFilters.some((f) => f.value !== null) || $selectedVerse)
        ? `${$displayedResult.segments.length} / ${$displayedResult.total}`
        : '';

    let justAdded = false;

    function addCondition(): void {
        justAdded = true;
        activeFilters.update((list) => [
            ...list,
            { field: 'duration_s', op: '>', value: null },
        ]);
        // Reset justAdded after one tick so autoFocus only fires for this condition.
        setTimeout(() => { justAdded = false; }, 0);
    }

    function clearAll(): void {
        activeFilters.set([]);
        savedFilterView.set(null);
    }

    function onConditionChange(): void {
        // Trigger store-internal write so `displayedResult` re-derives.
        activeFilters.update((list) => [...list]);
    }

    function onConditionRemove(idx: number): void {
        activeFilters.update((list) => {
            const next = [...list];
            next.splice(idx, 1);
            return next;
        });
    }
</script>

<div class="seg-filter-bar" id="seg-filter-bar" {hidden}>
    <div class="seg-filter-header">
        <span class="seg-filter-title">
            Filters <span id="seg-filter-count" class="seg-filter-count">{countLabel}</span>
        </span>
        <button id="seg-filter-add-btn" class="btn btn-sm" on:click={addCondition}>+ Add Condition</button>
        <button
            id="seg-filter-clear-btn"
            class="btn btn-sm btn-cancel"
            hidden={count === 0}
            on:click={clearAll}>Clear All</button>
        <span id="seg-filter-status" class="seg-filter-status">{statusText}</span>
    </div>
    <div id="seg-filter-rows" class="seg-filter-rows">
        {#each $activeFilters as f, i (i)}
            <FilterCondition
                filter={f}
                autoFocus={justAdded && i === $activeFilters.length - 1}
                on:change={onConditionChange}
                on:remove={() => onConditionRemove(i)}
            />
        {/each}
    </div>
</div>
