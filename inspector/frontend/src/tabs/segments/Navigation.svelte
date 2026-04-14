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
     * Cross-cutting rule (S2-B01 fix, option (a) from store-bindings matrix):
     * this component ALSO subscribes to activeFilters — when filters become
     * non-empty, savedFilterView is cleared. This single ownership point
     * replaces the scattered Stage-1 writes (filters.applyFiltersAndRender +
     * data.clearSegDisplay + navigation._restoreFilterView all cleared the
     * saved view).
     */

    import { createEventDispatcher } from 'svelte';

    import { activeFilters } from '../../lib/stores/segments/filters';
    import {
        backBannerVisible,
        savedFilterView,
    } from '../../lib/stores/segments/navigation';

    const dispatch = createEventDispatcher<{ restore: void }>();

    // Rule: when filters become non-empty, clear the saved view (the "back
    // to results" context becomes stale the moment the user starts filtering
    // again). This replaces the scattered Stage-1 writes.
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
