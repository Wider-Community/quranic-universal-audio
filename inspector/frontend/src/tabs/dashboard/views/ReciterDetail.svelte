<script lang="ts">
    /**
     * Reciter detail modal.
     *
     * Opened from the dashboard catalog. Lists the reciter's combinations
     * in a flat table; columns where every value is null are omitted.
     *
     * No reciter-level aggregate totals (hours, coverage) — those are
     * properties of combinations and are shown per row.
     */
    import { onDestroy } from 'svelte';

    import { fetchPublicReciter } from '../../../lib/api/public-reciter-detail';
    import Modal from '../../../lib/components/Modal.svelte';
    import StatePill from '../../../lib/components/StatePill.svelte';
    import { playerContext } from '../../../lib/stores/player-context';
    import type { PublicDelivery, PublicReciter } from '../../../lib/types/public-state';
    import {
        bitrateLabel,
        categoryLabel,
        channelDisplay,
        countryName,
        coverageLabel,
        titleCaseSlug,
        totalHoursLabel,
    } from '../../../lib/utils/delivery-label';
    import StateTimeline from '../components/StateTimeline.svelte';
    import { closeDetail, dashboardState } from '../stores/dashboard-state';

    let reciter: PublicReciter | null = null;
    let loading = false;
    let notFound = false;
    let error: string | null = null;
    let inflight: AbortController | null = null;
    let lastFetched: string | null = null;

    $: detailId = $dashboardState.view.kind === 'detail' ? $dashboardState.view.reciterId : null;
    $: void maybeReload(detailId);

    async function maybeReload(id: string | null): Promise<void> {
        if (id === null) {
            reciter = null;
            lastFetched = null;
            return;
        }
        if (id === lastFetched) return;
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

    interface ColSpec {
        key: 'riwayah' | 'style' | 'context' | 'year' | 'category' | 'coverage' | 'channel' | 'bitrate' | 'hours';
        label: string;
        present: (d: PublicDelivery) => boolean;
        value: (d: PublicDelivery) => string;
    }

    const ALL_COLS: ColSpec[] = [
        { key: 'riwayah', label: 'Riwayah', present: (d) => !!d.riwayah, value: (d) => titleCaseSlug(d.riwayah) },
        { key: 'style',   label: 'Style',   present: (d) => !!d.style,   value: (d) => titleCaseSlug(d.style) },
        { key: 'context', label: 'Context', present: (d) => !!d.recording_context, value: (d) => titleCaseSlug(d.recording_context!) },
        { key: 'year',    label: 'Year',    present: (d) => d.recording_year != null, value: (d) => String(d.recording_year ?? '') },
        { key: 'category', label: 'Category', present: (d) => !!d.audio_category, value: (d) => categoryLabel(d) },
        { key: 'coverage', label: 'Coverage', present: (d) => d.chapter_count > 0, value: (d) => coverageLabel(d) },
        { key: 'channel', label: 'Channel', present: (d) => !!d.channel, value: (d) => channelDisplay(d) },
        { key: 'bitrate', label: 'Bitrate', present: (d) => d.bitrate_kbps_nominal != null || !!d.bitrate_mode, value: (d) => bitrateLabel(d) },
        { key: 'hours',   label: 'Total hours', present: (d) => d.total_duration_sec != null, value: (d) => totalHoursLabel(d) },
    ];

    $: visibleCols = reciter
        ? ALL_COLS.filter((c) => reciter!.deliveries.some(c.present))
        : [];

    function playDelivery(d: PublicDelivery): void {
        if (!reciter) return;
        playerContext.update((s) => ({
            ...s,
            reciter,
            delivery: d,
            surahNum: s.surahNum ?? 1,
            positionMs: 0,
            isPlaying: true,
        }));
    }

    $: open = detailId !== null;
</script>

<Modal {open} title={null} on:close={closeDetail}>
    <div class="detail" role="region" aria-label="Reciter detail">
        {#if loading}
            <div class="state">Loading…</div>
        {:else if notFound}
            <div class="state">
                <p>Reciter not found.</p>
            </div>
        {:else if error}
            <div class="state error">
                <p>{error}</p>
                <button class="link" on:click={() => { lastFetched = null; void maybeReload(detailId); }}>Retry</button>
            </div>
        {:else if reciter}
            <header class="head">
                <div class="names">
                    <h2 class="name-en">{reciter.name}</h2>
                    {#if reciter.name_ar}
                        <span class="name-ar" dir="rtl">{reciter.name_ar}</span>
                    {/if}
                </div>
                {#if reciter.country}
                    <div class="country">{countryName(reciter.country)}</div>
                {/if}
            </header>

            <StateTimeline {reciter} />

            {#if reciter.deliveries.length === 0}
                <div class="state">No combinations available.</div>
            {:else}
                <div class="table-wrap">
                    <table class="combinations">
                        <thead>
                            <tr>
                                <th class="col-play" aria-label="Play"></th>
                                {#each visibleCols as col (col.key)}
                                    <th>{col.label}</th>
                                {/each}
                                <th class="col-state">State</th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each reciter.deliveries as d (d.slug)}
                                <tr>
                                    <td class="col-play">
                                        {#if d.audio_category !== 'by_ayah'}
                                            <button
                                                type="button"
                                                class="play"
                                                aria-label="Play this combination"
                                                on:click={() => playDelivery(d)}
                                            >▶</button>
                                        {/if}
                                    </td>
                                    {#each visibleCols as col (col.key)}
                                        <td class={`cell cell-${col.key}`}>{col.value(d)}</td>
                                    {/each}
                                    <td class="col-state">
                                        <StatePill state={d.bucket} size="sm" />
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            {/if}
        {/if}
    </div>
</Modal>

<style>
    .detail {
        padding: var(--s-4) var(--s-6) var(--s-6);
        max-width: 1100px;
        width: min(96vw, 1100px);
        min-height: 240px;
    }
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

    .head {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--s-1);
        padding-bottom: var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-4);
    }
    .names {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        flex-wrap: wrap;
    }
    .name-en {
        font-size: var(--fs-h3);
        font-weight: 500;
        color: var(--text-primary);
        margin: 0;
    }
    .name-ar {
        font-size: var(--fs-body);
        color: var(--text-secondary);
        font-family: var(--font-arabic, inherit);
    }
    .country {
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }

    .table-wrap { overflow-x: auto; }
    .combinations {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-meta);
    }
    .combinations thead th {
        text-align: left;
        font-weight: 500;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 10.5px;
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        white-space: nowrap;
    }
    .combinations tbody td {
        padding: var(--s-3);
        color: var(--text-secondary);
        border-bottom: 1px solid var(--border-quiet);
        vertical-align: middle;
        white-space: nowrap;
    }
    .combinations tbody tr:hover td { background: var(--panel); }
    .col-play { width: 36px; }
    .col-state { text-align: left; }
    .cell-coverage,
    .cell-bitrate,
    .cell-hours,
    .cell-year { font-family: var(--font-mono); font-variant-numeric: tabular-nums; color: var(--text-primary); }

    .play {
        width: 26px; height: 26px;
        border-radius: 50%;
        border: 1px solid var(--border-default);
        background: transparent;
        color: var(--text-muted);
        display: inline-flex; align-items: center; justify-content: center;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast);
    }
    .play:hover {
        color: var(--accent);
        border-color: var(--accent);
        background: var(--accent-tint-soft);
    }
</style>
