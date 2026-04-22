<script lang="ts">
    /**
     * Navigation — "Back to filter results" banner.
     *
     * Subscribes to `backBannerVisible` derived; renders banner when true.
     * Click handler restores saved filter view (filters / chapter / verse /
     * scrollTop) via the parent's `onRestore` callback — the restore flow
     * needs access to chapter loading (SegmentsTab owns the reciter/chapter
     * cascade + applyFiltersAndRender invocation) so it's kept at the parent.
     *
     * This component also subscribes to activeFilters — when filters become
     * non-empty, savedFilterView is cleared. Single ownership point: avoids
     * scattered clears across FiltersBar, SegmentsTab, and navigation utils.
     */

    import { createEventDispatcher } from 'svelte';

    import { activeFilters } from '../../stores/filters';
    import {
        backBannerVisible,
        savedFilterView,
    } from '../../stores/navigation';

    const dispatch = createEventDispatcher<{ restore: void }>();

    // When filters become non-empty, clear the saved view — the "back to
    // results" context becomes stale the moment the user starts filtering again.
    $: if ($activeFilters.some((f) => f.value !== null)) {
        if ($savedFilterView) savedFilterView.set(null);
    }

    function onBackClick(): void {
        dispatch('restore');
    }
</script>

{#if $backBannerVisible}
    <div class="seg-back-banner">
        <button class="btn btn-sm seg-back-btn" on:click={onBackClick}>
            &larr; Back to filter results
        </button>
    </div>
{/if}
