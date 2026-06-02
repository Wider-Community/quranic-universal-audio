<script lang="ts">
    /**
     * Dashboard tab root.
     *
     * CatalogList stays mounted; ReciterDetail renders as a modal when
     * dashboardState.view.kind === 'detail'. Filter state persists across
     * modal open/close.
     */
    import AdminDashboardModal from './components/admin/AdminDashboardModal.svelte';
    import CatalogList from './views/CatalogList.svelte';
    import ReciterDetail from './views/ReciterDetail.svelte';
</script>

<div class="dash">
    <CatalogList />
    <ReciterDetail />
    <AdminDashboardModal />
</div>

<style>
    .dash {
        min-height: 60vh;
        padding-bottom: var(--player-h, 72px);
    }
</style>
