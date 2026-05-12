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
    import BottomPlayer from '../../lib/components/player/BottomPlayer.svelte';
    import { dashboardView } from './stores/dashboard-state';
    import CatalogList from './views/CatalogList.svelte';
    import ReciterDetail from './views/ReciterDetail.svelte';
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

    <BottomPlayer />
</div>

<style>
    .dash {
        min-height: 60vh;
        padding-bottom: var(--player-h, 72px);
    }
    .view[hidden] { display: none; }
</style>
