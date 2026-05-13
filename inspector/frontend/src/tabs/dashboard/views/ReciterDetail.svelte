<script lang="ts">
    /**
     * Reciter detail modal.
     *
     * Opened from the dashboard catalog. Lists the reciter's combinations
     * in a flat table, sorted by status priority and other axes (see
     * compareDeliveries below). Selected row drives the per-combination
     * timeline pinned at the top of the modal; clicking a row updates the
     * timeline. When dashboard filters are active, matching combinations
     * are grouped above non-matching ones.
     */
    import { onDestroy } from 'svelte';

    import { fetchPublicReciter } from '../../../lib/api/public-reciter-detail';
    import Modal from '../../../lib/components/Modal.svelte';
    import StatePill from '../../../lib/components/StatePill.svelte';
    import { playerContext } from '../../../lib/stores/player-context';
    import {
        bucketRank,
        type PublicDelivery,
        type PublicReciter,
    } from '../../../lib/types/public-state';
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
    let selectedSlug: string | null = null;

    $: detailId = $dashboardState.view.kind === 'detail' ? $dashboardState.view.reciterId : null;
    $: void maybeReload(detailId);

    async function maybeReload(id: string | null): Promise<void> {
        if (id === null) {
            reciter = null;
            lastFetched = null;
            selectedSlug = null;
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
        selectedSlug = null;
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

    // ---- sort ----
    function catRank(cat: string): number {
        // surah-style first, ayah-style last
        if (cat === 'by_surah') return 0;
        if (cat === 'by_ayah')  return 2;
        return 1;
    }

    function compareDeliveries(a: PublicDelivery, b: PublicDelivery): number {
        const s = bucketRank(a.bucket) - bucketRank(b.bucket);
        if (s !== 0) return s;
        const c = catRank(a.audio_category) - catRank(b.audio_category);
        if (c !== 0) return c;
        // full coverage > partial
        if (a.coverage_kind !== b.coverage_kind) {
            return a.coverage_kind === 'full' ? -1 : 1;
        }
        const r = a.riwayah.localeCompare(b.riwayah);
        if (r !== 0) return r;
        const st = a.style.localeCompare(b.style);
        if (st !== 0) return st;
        return (b.bitrate_kbps_nominal ?? 0) - (a.bitrate_kbps_nominal ?? 0);
    }

    // ---- filter-match partition (ignore status axis) ----
    const AXIS_TAGS: Record<string, (d: PublicDelivery) => string[]> = {
        riwayah: (d) => [d.riwayah],
        style: (d) => [d.style],
        coverage: (d) => [d.coverage_kind],
        recording_context: (d) => (d.recording_context ? [d.recording_context] : []),
        channel: (d) => [d.channel],
    };

    function matchesActiveFilters(
        d: PublicDelivery,
        filters: Record<string, Set<string>>,
    ): boolean {
        for (const [axisKey, tags] of Object.entries(filters)) {
            if (axisKey === 'status') continue;
            if (!tags || tags.size === 0) continue;
            const tagsOf = AXIS_TAGS[axisKey];
            if (!tagsOf) continue;
            const dTags = tagsOf(d);
            if (!dTags.some((t) => tags.has(t))) return false;
        }
        return true;
    }

    $: sortedDeliveries = reciter
        ? [...reciter.deliveries].sort(compareDeliveries)
        : [];

    $: hasFacetFilters = (() => {
        for (const [k, set] of Object.entries($dashboardState.activeFilters)) {
            if (k === 'status') continue;
            if (set && set.size > 0) return true;
        }
        return false;
    })();

    $: partition = (() => {
        if (!hasFacetFilters) {
            return { matching: sortedDeliveries, other: [] as PublicDelivery[] };
        }
        const matching: PublicDelivery[] = [];
        const other: PublicDelivery[] = [];
        for (const d of sortedDeliveries) {
            if (matchesActiveFilters(d, $dashboardState.activeFilters)) matching.push(d);
            else other.push(d);
        }
        return { matching, other };
    })();

    // Default selection: first row of the matching group (or first row overall).
    $: defaultSlug = partition.matching[0]?.slug ?? partition.other[0]?.slug ?? null;
    $: if (defaultSlug && (selectedSlug === null || !sortedDeliveries.some((d) => d.slug === selectedSlug))) {
        selectedSlug = defaultSlug;
    }

    $: selectedDelivery = sortedDeliveries.find((d) => d.slug === selectedSlug) ?? null;

    function playDelivery(d: PublicDelivery, ev: Event): void {
        ev.stopPropagation();
        if (!reciter) return;
        selectedSlug = d.slug;
        playerContext.update((s) => ({
            ...s,
            reciter,
            delivery: d,
            surahNum: s.surahNum ?? 1,
            positionMs: 0,
            isPlaying: true,
        }));
    }

    function selectRow(d: PublicDelivery): void {
        selectedSlug = d.slug;
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

            <div class="timeline-pin">
                <StateTimeline delivery={selectedDelivery} />
            </div>

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
                        {#if hasFacetFilters && partition.matching.length > 0}
                            <tbody>
                                <tr class="group-head">
                                    <td colspan={visibleCols.length + 2}>
                                        Matching your filters
                                        <span class="group-count">{partition.matching.length}</span>
                                    </td>
                                </tr>
                                {#each partition.matching as d (d.slug)}
                                    <tr
                                        class="row"
                                        class:selected={d.slug === selectedSlug}
                                        on:click={() => selectRow(d)}
                                    >
                                        <td class="col-play">
                                            {#if d.audio_category !== 'by_ayah'}
                                                <button
                                                    type="button"
                                                    class="play"
                                                    aria-label="Play this combination"
                                                    on:click={(e) => playDelivery(d, e)}
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
                            {#if partition.other.length > 0}
                                <tbody>
                                    <tr class="group-head other">
                                        <td colspan={visibleCols.length + 2}>
                                            Other combinations
                                            <span class="group-count">{partition.other.length}</span>
                                        </td>
                                    </tr>
                                    {#each partition.other as d (d.slug)}
                                        <tr
                                            class="row dim"
                                            class:selected={d.slug === selectedSlug}
                                            on:click={() => selectRow(d)}
                                        >
                                            <td class="col-play">
                                                {#if d.audio_category !== 'by_ayah'}
                                                    <button
                                                        type="button"
                                                        class="play"
                                                        aria-label="Play this combination"
                                                        on:click={(e) => playDelivery(d, e)}
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
                            {/if}
                        {:else}
                            <tbody>
                                {#each sortedDeliveries as d (d.slug)}
                                    <tr
                                        class="row"
                                        class:selected={d.slug === selectedSlug}
                                        on:click={() => selectRow(d)}
                                    >
                                        <td class="col-play">
                                            {#if d.audio_category !== 'by_ayah'}
                                                <button
                                                    type="button"
                                                    class="play"
                                                    aria-label="Play this combination"
                                                    on:click={(e) => playDelivery(d, e)}
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
                        {/if}
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
        margin-bottom: var(--s-2);
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

    /* Pin the timeline to the modal scroll container so the table can
       scroll under it. The closest scrolling ancestor is `.modal-body`. */
    .timeline-pin {
        position: sticky;
        top: 0;
        z-index: 2;
        background: var(--canvas);
        padding-bottom: var(--s-2);
        margin: 0 calc(var(--s-6) * -1) var(--s-3);
        padding-left: var(--s-6);
        padding-right: var(--s-6);
        border-bottom: 1px solid var(--border-quiet);
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
        position: sticky;
        top: 0;
        background: var(--canvas);
    }
    .combinations tbody td {
        padding: var(--s-3);
        color: var(--text-secondary);
        border-bottom: 1px solid var(--border-quiet);
        vertical-align: middle;
        white-space: nowrap;
    }
    .row { cursor: pointer; }
    .row:hover td { background: var(--panel); }
    .row.selected td {
        background: var(--accent-tint-soft);
        box-shadow: inset 2px 0 0 var(--accent);
    }
    .row.dim td { color: var(--text-muted); }
    .group-head td {
        padding: var(--s-3) var(--s-3) var(--s-2);
        color: var(--text-muted);
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        background: var(--panel);
        border-bottom: 1px solid var(--border-quiet);
    }
    .group-count {
        margin-left: var(--s-2);
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
        font-family: var(--font-mono);
        text-transform: none;
    }
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
