<script lang="ts">
    /**
     * Dashboard tab root.
     *
     * Owns the list↔detail view toggle via `dashboard-state`. Both
     * views are mounted simultaneously and toggled via the App-shell
     * `hidden` cascade pattern so back-navigation preserves filter
     * state without remounting CatalogList.
     *
     * Detail view (Slice G) ships as a placeholder until ReciterDetail
     * lands; for now the "open detail" event just no-ops.
     */
    import CatalogList from './views/CatalogList.svelte';
    import ReciterDetail from './views/ReciterDetail.svelte';
    import { dashboardView } from './stores/dashboard-state';
</script>

<div class="dash">
    <div class="view" hidden={$dashboardView.kind !== 'list'}>
        <CatalogList />
    </div>
    <div class="view" hidden={$dashboardView.kind !== 'detail'}>
        {#if $dashboardView.kind === 'detail'}
            <ReciterDetail />
        {/if}
    </div>
</div>

<style>
    .dash { min-height: 60vh; }
    .view[hidden] { display: none; }
</style>
