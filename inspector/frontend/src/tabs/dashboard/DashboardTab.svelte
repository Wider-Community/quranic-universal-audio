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
    import { backToList, dashboardView } from './stores/dashboard-state';
</script>

<div class="dash">
    <div class="view" hidden={$dashboardView.kind !== 'list'}>
        <CatalogList />
    </div>
    <div class="view" hidden={$dashboardView.kind !== 'detail'}>
        {#if $dashboardView.kind === 'detail'}
            <div class="detail-placeholder">
                <button class="back" on:click={backToList}>← Back to catalog</button>
                <h1>{$dashboardView.reciterName}</h1>
                <p class="hint">Per-reciter detail view ships in Slice G.</p>
            </div>
        {/if}
    </div>
</div>

<style>
    .dash { min-height: 60vh; }
    .view[hidden] { display: none; }
    .detail-placeholder {
        padding: var(--s-8) var(--gutter);
    }
    .detail-placeholder h1 {
        font-size: var(--fs-h1);
        color: var(--text-primary);
        font-weight: 500;
        letter-spacing: -0.015em;
        margin: var(--s-4) 0 var(--s-4);
    }
    .back {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: var(--s-2) 0;
    }
    .back:hover { color: var(--text-primary); }
    .hint {
        color: var(--text-faint);
        font-size: var(--fs-meta);
    }
</style>
