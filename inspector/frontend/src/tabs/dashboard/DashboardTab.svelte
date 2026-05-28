<script lang="ts">
    /**
     * Dashboard tab root.
     *
     * CatalogList stays mounted; ReciterDetail renders as a modal when
     * dashboardState.view.kind === 'detail'. Filter state persists across
     * modal open/close.
     */
    import BottomPlayer from '../../lib/components/player/BottomPlayer.svelte';
    import AdminDashboardModal from './components/admin/AdminDashboardModal.svelte';
    import CatalogList from './views/CatalogList.svelte';
    import ReciterDetail from './views/ReciterDetail.svelte';
</script>

<div class="dash">
    <CatalogList />
    <ReciterDetail />
    <AdminDashboardModal />
    <BottomPlayer />
</div>

<style>
    .dash {
        min-height: 60vh;
        padding-bottom: var(--player-h, 72px);
    }
</style>
