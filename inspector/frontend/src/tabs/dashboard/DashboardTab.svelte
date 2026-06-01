<script lang="ts">
    /**
     * Dashboard tab root.
     *
     * CatalogList stays mounted; ReciterDetail renders as a modal when
     * dashboardState.view.kind === 'detail'. Filter state persists across
     * modal open/close.
     *
     * The BottomPlayer + NowReciting footer is no longer owned here — it was
     * promoted to the app shell (App.svelte) so playback/animation survive tab
     * switches. This tab just reserves space under the (shell-owned) footer.
     */
    import { get } from 'svelte/store';
    import { onMount } from 'svelte';

    import { loadPersistedSlice, playerContext } from '../../lib/stores/player-context';
    import AdminDashboardModal from './components/admin/AdminDashboardModal.svelte';
    import { loadCatalog, resolveDeliverySlug } from './stores/catalog-data';
    import CatalogList from './views/CatalogList.svelte';
    import ReciterDetail from './views/ReciterDetail.svelte';

    // Restore the last reciter+surah after a refresh. Only when nothing is
    // already bound (e.g. the user landed on Timestamps first and it set the
    // player) — we never override a live selection. Loads paused; the user
    // presses play. Speed is restored separately by the BottomPlayer.
    onMount(async () => {
        if (get(playerContext).delivery) return;
        const slice = loadPersistedSlice();
        if (!slice.deliverySlug) return;
        await loadCatalog();
        if (get(playerContext).delivery) return; // re-check after the await
        const resolved = resolveDeliverySlug(slice.deliverySlug);
        if (!resolved) return;
        playerContext.update((s) => ({
            ...s,
            reciter: resolved.reciter,
            delivery: resolved.delivery,
            surahNum: slice.surahNum ?? 1,
            positionMs: 0,
            isPlaying: false,
        }));
    });
</script>

<div class="dash">
    <CatalogList />
    <ReciterDetail />
    <AdminDashboardModal />
</div>

<style>
    .dash {
        min-height: 60vh;
        /* Reserve the footer height plus the now-reciting section (0 when it's
         *  hidden — NowReciting sets the var) so content never hides behind the
         *  shell-owned footer. */
        padding-bottom: calc(var(--player-h, 72px) + var(--now-reciting-h, 0px));
    }
</style>
