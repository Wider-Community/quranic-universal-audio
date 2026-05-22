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
    import { undiscardReciter } from '../../../lib/api/requests';
    import Modal from '../../../lib/components/Modal.svelte';
    import StatePill from '../../../lib/components/StatePill.svelte';
    import { SIGN_IN_MESSAGES } from '../../../lib/sign-in-messages';
    import { currentUser, isAdmin, isOwner, isSignedIn } from '../../../lib/stores/current-user';
    import { playerContext } from '../../../lib/stores/player-context';
    import { openSignInModal } from '../../../lib/stores/sign-in-modal';
    import {
        type AdminDiscardedDelivery,
        type AdminViewReciter,
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
    import { compareDeliveries } from '../../../lib/utils/delivery-sort';
    import RequestForm from '../components/RequestForm.svelte';
    import StateTimeline from '../components/StateTimeline.svelte';
    import { loadCatalog } from '../stores/catalog-data';
    import { closeDetail, dashboardState } from '../stores/dashboard-state';

    let reciter: (PublicReciter & Partial<AdminViewReciter>) | null = null;
    let loading = false;
    let notFound = false;
    let error: string | null = null;
    let inflight: AbortController | null = null;
    let lastFetched: string | null = null;
    let selectedSlug: string | null = null;

    /** Open request form, in either user-create or admin-review mode. */
    let formState: {
        mode: 'create' | 'review';
        delivery: PublicDelivery;
    } | null = null;

    function openRequest(d: PublicDelivery): void {
        if (!isSignedIn($currentUser)) {
            openSignInModal(null, SIGN_IN_MESSAGES.request);
            return;
        }
        formState = { mode: 'create', delivery: d };
        // Load surah 1 of this combination in the bottom player so the user
        // can listen to a sample while filling out the form. Skipped for
        // by_ayah deliveries (surah-level streams aren't available — same
        // reason the row's play button hides for those). Also skipped when
        // the player already has this exact delivery loaded — don't yank
        // playback position back to 0 for the user who's already listening.
        if (reciter && d.audio_category !== 'by_ayah') {
            selectedSlug = d.slug;
            const currentSlug = $playerContext.delivery?.slug;
            if (currentSlug !== d.slug) {
                playerContext.update((s) => ({
                    ...s,
                    reciter,
                    delivery: d,
                    surahNum: 1,
                    positionMs: 0,
                    isPlaying: true,
                }));
            }
        }
    }

    function openReview(d: PublicDelivery): void {
        formState = { mode: 'review', delivery: d };
    }

    function closeForm(): void {
        formState = null;
    }

    async function onFormResolved(): Promise<void> {
        formState = null;
        // Refresh the modal so the row's pill (and the discarded section)
        // reflect the new state.
        if (detailId !== null) {
            lastFetched = null;
            await maybeReload(detailId);
        }
        // Also refresh the dashboard list/counts/picker behind the modal —
        // a request submit/reject/undiscard changes catalog+state, and the
        // catalog store is otherwise length-gated to its boot snapshot.
        void loadCatalog(true);
    }

    async function onUndiscard(d: AdminDiscardedDelivery): Promise<void> {
        const reason = window.prompt(
            'Reason (≥10 characters) for un-discarding this combination — recorded in the audit log:',
            '',
        );
        if (reason === null) return;
        const trimmed = reason.trim();
        if (trimmed.length < 10) {
            window.alert('Reason must be at least 10 characters.');
            return;
        }
        try {
            await undiscardReciter(d.slug, trimmed);
            await onFormResolved();
        } catch (e) {
            window.alert(`Un-discard failed: ${(e as Error).message}`);
        }
    }

    $: detailView = $dashboardState.view.kind === 'detail' ? $dashboardState.view : null;
    $: detailId = detailView?.reciterId ?? null;
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
            else {
                reciter = result;
                // Pre-select the slug requested by the caller (e.g. from the
                // bottom player's state pill), if it exists on this reciter.
                const req = detailView?.initialSlug;
                if (req && result.deliveries.some((d) => d.slug === req)) {
                    selectedSlug = req;
                }
            }
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
                                            {#if d.bucket === 'available_for_request'}
                                                <button
                                                    type="button"
                                                    class="request-btn"
                                                    on:click|stopPropagation={() => openRequest(d)}
                                                >Request</button>
                                            {:else if d.bucket === 'requested' && $isAdmin}
                                                <button
                                                    type="button"
                                                    class="pill-as-btn"
                                                    title="Review submitted request"
                                                    on:click|stopPropagation={() => openReview(d)}
                                                ><StatePill state={d.bucket} size="sm" /></button>
                                            {:else}
                                                <StatePill state={d.bucket} size="sm" />
                                            {/if}
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
                                            {#if d.bucket === 'available_for_request'}
                                                <button
                                                    type="button"
                                                    class="request-btn"
                                                    on:click|stopPropagation={() => openRequest(d)}
                                                >Request</button>
                                            {:else if d.bucket === 'requested' && $isAdmin}
                                                <button
                                                    type="button"
                                                    class="pill-as-btn"
                                                    title="Review submitted request"
                                                    on:click|stopPropagation={() => openReview(d)}
                                                ><StatePill state={d.bucket} size="sm" /></button>
                                            {:else}
                                                <StatePill state={d.bucket} size="sm" />
                                            {/if}
                                        </td>
                                    </tr>
                                {/each}
                            </tbody>
                        {/if}
                    </table>
                </div>
            {/if}

            {#if $isAdmin && reciter.discarded_deliveries && reciter.discarded_deliveries.length > 0}
                <section class="discarded-section" aria-label="Discarded combinations">
                    <h3>
                        Discarded combinations
                        <span class="count">{reciter.discarded_deliveries.length}</span>
                    </h3>
                    <p class="note">
                        Hidden from public view. Maintainers + owners only.
                        {#if $isOwner}Owners can un-discard.{/if}
                    </p>
                    <ul class="discarded-list">
                        {#each reciter.discarded_deliveries as d (d.slug)}
                            <li>
                                <div class="d-row">
                                    <span class="d-combo">
                                        {titleCaseSlug(d.riwayah)} · {titleCaseSlug(d.style)}
                                        {#if d.recording_context}· {titleCaseSlug(d.recording_context)}{/if}
                                        {#if d.recording_year}· {d.recording_year}{/if}
                                    </span>
                                    <StatePill state={'discarded'} size="sm" />
                                </div>
                                {#if d.visibility_reason}
                                    <p class="d-reason">{d.visibility_reason}</p>
                                {/if}
                                {#if $isOwner}
                                    <button
                                        type="button"
                                        class="undiscard-btn"
                                        on:click={() => onUndiscard(d)}
                                    >Un-discard</button>
                                {/if}
                            </li>
                        {/each}
                    </ul>
                </section>
            {/if}
        {/if}
    </div>
</Modal>

{#if formState && reciter}
    <div
        class="form-backdrop"
        role="presentation"
        on:click={(e) => { if (e.target === e.currentTarget) closeForm(); }}
    >
        <RequestForm
            mode={formState.mode}
            {reciter}
            delivery={formState.delivery}
            on:submitted={onFormResolved}
            on:rejected={onFormResolved}
            on:close={closeForm}
        />
    </div>
{/if}

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
    .state.error { color: var(--state-error-fg); }
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

    /* Request button — replaces the "Available for request" pill for
       signed-in non-admin viewers. Compact so it doesn't reflow the row. */
    .request-btn {
        background: var(--state-available-request-bg);
        color: var(--state-available-request-fg);
        border: 1px solid var(--state-available-request-fg);
        border-radius: 999px;
        padding: 2px 10px;
        font-size: 11px;
        cursor: pointer;
        transition: background var(--t-fast), color var(--t-fast);
    }
    .request-btn:hover {
        background: var(--state-available-request-fg);
        color: var(--canvas);
    }
    /* Pill-as-button: admin click target on the "Requested" pill that opens
       the review form. Strips the default button chrome so the pill renders
       identically to the non-interactive variant. */
    .pill-as-btn {
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
    }

    /* Discarded section (admin-only). */
    .discarded-section {
        margin-top: var(--s-5);
        padding-top: var(--s-4);
        border-top: 1px dashed var(--border-quiet);
    }
    .discarded-section h3 {
        font-size: var(--fs-body);
        font-weight: 500;
        color: var(--text-secondary);
        margin: 0 0 var(--s-1);
    }
    .discarded-section .count {
        margin-left: var(--s-2);
        color: var(--text-faint);
        font-weight: 400;
        font-size: var(--fs-meta);
    }
    .discarded-section .note {
        margin: 0 0 var(--s-3);
        font-size: var(--fs-meta);
        color: var(--text-faint);
    }
    .discarded-list {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .discarded-list li {
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: var(--s-3);
        opacity: 0.85;
    }
    .d-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
    }
    .d-combo {
        color: var(--text-secondary);
        font-size: var(--fs-meta);
    }
    .d-reason {
        margin: var(--s-1) 0 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        font-style: italic;
    }
    .undiscard-btn {
        margin-top: var(--s-2);
        background: transparent;
        border: 1px solid var(--border-default);
        color: var(--text-secondary);
        border-radius: var(--r-2);
        padding: 4px 10px;
        font-size: 11px;
        cursor: pointer;
    }
    .undiscard-btn:hover {
        color: var(--text-primary);
        border-color: var(--accent);
    }

    /* Inner sub-modal hosting the RequestForm. Sits above the reciter
       Modal's backdrop without nesting Modal (which would compete on
       focus trap + scroll lock). */
    .form-backdrop {
        position: fixed;
        inset: 0;
        background: oklch(0.06 0.005 268 / 0.65);
        z-index: 110;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--s-6);
        /* The bottom player is fixed at z-index 110 (same as this backdrop),
           so it paints over anything that reaches the viewport bottom. Reserve
           its height so the centered modal — and its footer — clear it. */
        padding-bottom: calc(var(--s-6) + var(--player-h, 72px));
    }
</style>
