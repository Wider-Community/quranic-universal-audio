<script lang="ts">
    /**
     * Dashboard detail view — per-reciter page.
     *
     * Fetches /api/public/reciter/<id> on mount and re-fetches whenever
     * the active detail reciterId changes. 404 renders a "not found"
     * state with a back link; failed requests show a retry-able error.
     *
     * Back navigation returns to the list view via dashboard-state;
     * filter state is preserved because both views remain mounted.
     */
    import { onDestroy } from 'svelte';

    import { fetchPublicReciter } from '../../../lib/api/public-reciter-detail';
    import DeliveriesTable from '../../../lib/components/DeliveriesTable.svelte';
    import type { PublicReciter } from '../../../lib/types/public-state';
    import DetailHeader from '../components/DetailHeader.svelte';
    import FactsList from '../components/FactsList.svelte';
    import Timeline from '../components/Timeline.svelte';
    import { backToList, dashboardState } from '../stores/dashboard-state';

    let reciter: PublicReciter | null = null;
    let loading = false;
    let notFound = false;
    let error: string | null = null;
    let inflight: AbortController | null = null;
    let lastFetched: string | null = null;

    $: void maybeReload($dashboardState.view.kind === 'detail'
        ? $dashboardState.view.reciterId
        : null);

    async function maybeReload(id: string | null): Promise<void> {
        if (id === null || id === lastFetched) return;
        lastFetched = id;
        inflight?.abort();
        inflight = new AbortController();
        loading = true;
        notFound = false;
        error = null;
        reciter = null;
        try {
            const result = await fetchPublicReciter(id, inflight.signal);
            if (result === null) notFound = true;
            else reciter = result;
        } catch (e) {
            if ((e as Error).name === 'AbortError') return;
            error = (e as Error).message ?? 'Failed to load reciter';
        } finally {
            loading = false;
        }
    }

    onDestroy(() => inflight?.abort());

    $: facts = reciter ? [
        { key: 'Country', value: reciter.country },
        { key: 'Riwayah', value: reciter.riwayat.join(' · ') || null },
        { key: 'Style', value: reciter.styles.join(' · ') || null },
        { key: 'Source', value: reciter.sources.join(' · ') || null },
        { key: 'Channel', value: reciter.channels.join(' · ') || null },
        {
            key: 'Recording',
            value: reciter.recording_contexts.filter(Boolean).join(' · ') || null,
        },
        {
            key: 'Coverage',
            value: reciter.coverage_kind === 'full'
                ? 'Full mushaf'
                : reciter.coverage_kind === 'partial' ? 'Partial' : 'Mixed',
        },
    ] : [];
</script>

<div class="detail">
    <button class="back" on:click={backToList}>← Back to catalog</button>

    {#if loading}
        <div class="state">Loading…</div>
    {:else if notFound}
        <div class="state">
            <p>Reciter not found.</p>
            <button class="link" on:click={backToList}>Return to catalog</button>
        </div>
    {:else if error}
        <div class="state error">
            <p>{error}</p>
            <button class="link" on:click={() => { lastFetched = null; void maybeReload(($dashboardState.view.kind === 'detail') ? $dashboardState.view.reciterId : null); }}>Retry</button>
        </div>
    {:else if reciter}
        <DetailHeader reciter={reciter} />

        <div class="grid">
            <main>
                {#if reciter.deliveries_count > 0}
                    <section class="section">
                        <div class="section-head">
                            <h2>Deliveries</h2>
                            <span class="count">{reciter.deliveries_count}</span>
                        </div>
                        <DeliveriesTable
                            deliveries={reciter.deliveries}
                            variant="detail"
                        />
                    </section>
                {/if}

                <section class="section">
                    <div class="section-head">
                        <h2>Progress</h2>
                    </div>
                    <Timeline reciter={reciter} />
                </section>
            </main>

            <aside class="side">
                <FactsList facts={facts} />
            </aside>
        </div>
    {/if}
</div>

<style>
    .detail {
        padding: 0 var(--gutter) var(--s-12);
    }
    .back {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font-size: var(--fs-meta);
        padding: var(--s-3) 0;
        cursor: pointer;
        transition: color var(--t-fast);
    }
    .back:hover { color: var(--text-primary); }

    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-publishing-fg); }
    .link {
        background: transparent;
        border: 0;
        color: var(--accent);
        cursor: pointer;
        font-size: var(--fs-meta);
        text-decoration: underline;
        text-underline-offset: 3px;
        margin-top: var(--s-2);
    }
    .link:hover { color: var(--accent-strong); }

    .grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) 320px;
        gap: var(--s-12);
    }
    @media (max-width: 1020px) {
        .grid { grid-template-columns: 1fr; gap: var(--s-8); }
    }

    .section {
        margin-bottom: var(--s-12);
    }
    .section-head {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        margin-bottom: var(--s-4);
        padding-bottom: var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
    }
    .section-head h2 {
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
        letter-spacing: 0.01em;
        margin: 0;
    }
    .section-head .count {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        font-variant-numeric: tabular-nums;
    }

    .side {
        position: sticky;
        top: var(--s-6);
        align-self: start;
    }
    @media (max-width: 1020px) {
        .side { position: static; }
    }
</style>
