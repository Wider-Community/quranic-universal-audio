<script lang="ts">
    /**
     * Admin Releases compartment.
     *
     * Three zones (mirrors the Reviews compartment for visual + interaction
     * parity):
     *   1. ``ReleasesSummaryCard`` — current GH release + Cut button + in-
     *      flight alert strip.
     *   2. Sticky filter bar — search (Arabic + Latin name) + facet chips
     *      (Riwayah / Style / Channel) + sort toggle (stalest / name) + clear.
     *   3. Five collapsible state sections — In progress / Stale on HF /
     *      Waiting to publish / Published & current / Excluded from GH.
     *      Priority-first bucketing: in_flight → stale_hf → waiting →
     *      published → excluded. A row belongs to exactly one bucket.
     *
     * Single bulk fetch via ``/api/admin/releases/status`` + FE-side bucketing
     * (same pattern as ReviewsCompartment). 30 s poll picks up new in-flight
     * state; the launch path also invalidates the server-side 5 s cache so
     * the next poll reflects the new state immediately.
     */
    import {
        fetchReleasesStatus,
        publishHf,
        type InFlightJob,
        type ReleaseStatusRow,
        type ReleasesStatusResponse,
    } from '../../../../../lib/api/admin-releases';
    import { releasesStore } from '../../../../../lib/stores/releases.svelte';
    import CutReleaseModal from './CutReleaseModal.svelte';
    import ReleasesRow, { type ReleasesBucket } from './ReleasesRow.svelte';
    import ReleasesSummaryCard from './ReleasesSummaryCard.svelte';

    let resp = $state<ReleasesStatusResponse | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    let cutModalOpen = $state(false);
    let busySlug = $state<string | null>(null);
    let rowError = $state<{ slug: string; message: string } | null>(null);

    // Trigger refetch from internal mutations (publish action) without
    // touching the store's refreshSeq.
    let refetchSeq = $state(0);
    let listAreaEl: HTMLElement | null = $state(null);

    /** Fetch on mount and every 30 s while the compartment is alive.
     *  AbortController cancels stale fetches on tab switch / unmount. */
    $effect(() => {
        refetchSeq;            // tracked dep (manual bump)
        releasesStore.refreshSeq;   // tracked dep (external — e.g. cut modal)
        const ac = new AbortController();
        loading = resp === null;   // only show the spinner on the cold load
        error = null;
        fetchReleasesStatus(ac.signal)
            .then((r) => {
                if (ac.signal.aborted) return;
                resp = r;
                loading = false;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load releases';
                loading = false;
            });
        return () => ac.abort();
    });

    $effect(() => {
        const id = window.setInterval(() => { refetchSeq += 1; }, 30_000);
        return () => window.clearInterval(id);
    });

    function refetch(): void { refetchSeq += 1; }

    const allRows = $derived(resp?.recitations ?? []);
    const inFlight = $derived(resp?.in_flight ?? []);
    const summary = $derived(resp?.summary ?? null);

    // ---- bucketing predicates ----
    const inFlightSlugs = $derived(new Set(
        inFlight.map((j) => j.slug).filter((s): s is string => !!s),
    ));
    function jobForSlug(slug: string): InFlightJob | null {
        return inFlight.find((j) => j.slug === slug) ?? null;
    }

    function isInFlight(r: ReleaseStatusRow): boolean {
        return inFlightSlugs.has(r.slug);
    }
    function isStaleHf(r: ReleaseStatusRow): boolean {
        return !!r.hf?.stale_since;
    }
    function isWaiting(r: ReleaseStatusRow): boolean {
        return r.state === 'released' && r.hf === null && r.ts !== null;
    }
    function isPublishedCurrent(r: ReleaseStatusRow): boolean {
        return r.hf !== null && !r.hf.stale_since;
    }
    function isExcluded(r: ReleaseStatusRow): boolean {
        return !r.gh_release_eligible;
    }

    function bucketOf(r: ReleaseStatusRow): ReleasesBucket | null {
        if (isInFlight(r)) return 'in_flight';
        if (isStaleHf(r)) return 'stale_hf';
        if (isWaiting(r)) return 'waiting';
        if (isPublishedCurrent(r)) return 'published_current';
        if (isExcluded(r)) return 'excluded';
        return null;   // fresh / inert — hide
    }

    // ---- filter + sort ----
    function matchFilter(r: ReleaseStatusRow): boolean {
        const f = releasesStore.filters;
        const q = f.q.trim().toLowerCase();
        if (q) {
            const ar = (r.name_ar ?? '').toLowerCase();
            const en = (r.name_en ?? '').toLowerCase();
            if (!ar.includes(q) && !en.includes(q)) return false;
        }
        if (f.riwayah && r.riwayah !== f.riwayah) return false;
        if (f.style && r.style !== f.style) return false;
        if (f.channel && r.channel !== f.channel) return false;
        return true;
    }

    function compareRows(a: ReleaseStatusRow, b: ReleaseStatusRow): number {
        if (releasesStore.sortBy === 'name') {
            return (a.name_en ?? a.slug).localeCompare(b.name_en ?? b.slug);
        }
        // "stalest first" — HF stale_since ASC, then HF produced_at ASC,
        // then slug. Rows without HF sort by ts.produced_at, surfacing the
        // longest-waiting-to-publish first.
        const aKey = a.hf?.stale_since ?? a.hf?.produced_at ?? a.ts?.produced_at ?? '';
        const bKey = b.hf?.stale_since ?? b.hf?.produced_at ?? b.ts?.produced_at ?? '';
        if (aKey !== bKey) return aKey.localeCompare(bKey);
        return a.slug.localeCompare(b.slug);
    }

    const filteredRows = $derived(allRows.filter(matchFilter).sort(compareRows));
    const narrowedToZero = $derived(
        allRows.length > 0
            && filteredRows.length === 0
            && releasesStore.hasActiveFilters,
    );

    // ---- facet value lists (with counts from the full unfiltered set) ----
    function countBy(rows: ReleaseStatusRow[], key: 'riwayah' | 'style' | 'channel'): Array<[string, number]> {
        const m = new Map<string, number>();
        for (const r of rows) {
            const v = r[key];
            if (!v) continue;
            m.set(v, (m.get(v) ?? 0) + 1);
        }
        return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    }
    const riwayahValues = $derived(countBy(allRows, 'riwayah'));
    const styleValues = $derived(countBy(allRows, 'style'));
    const channelValues = $derived(countBy(allRows, 'channel'));

    // ---- bucket-grouped rows ----
    type Section = {
        key: ReleasesBucket;
        label: string;
        mark: string;
        defaultCollapsed: boolean;
        hideWhenEmpty: boolean;
    };
    const SECTIONS: Section[] = [
        { key: 'in_flight',         label: 'In progress',         mark: 'inflight',  defaultCollapsed: false, hideWhenEmpty: true },
        { key: 'stale_hf',          label: 'Stale on HF',         mark: 'stale',     defaultCollapsed: false, hideWhenEmpty: false },
        { key: 'waiting',           label: 'Waiting to publish',  mark: 'waiting',   defaultCollapsed: false, hideWhenEmpty: false },
        { key: 'published_current', label: 'Published & current', mark: 'published', defaultCollapsed: true,  hideWhenEmpty: false },
        { key: 'excluded',          label: 'Excluded from GH',    mark: 'excluded',  defaultCollapsed: true,  hideWhenEmpty: false },
    ];

    const bucketed = $derived.by(() => {
        const out: Record<ReleasesBucket, ReleaseStatusRow[]> = {
            in_flight: [], stale_hf: [], waiting: [],
            published_current: [], excluded: [],
        };
        for (const r of filteredRows) {
            const b = bucketOf(r);
            if (b !== null) out[b].push(r);
        }
        return out;
    });

    /** Number of rows that COULD land in the next GH cut — released + has
     *  TS + eligible channel + (new OR refreshable). Surfaced in the summary
     *  card's "No releases yet · N ready" state and as Cut-button context. */
    const readyCount = $derived(
        allRows.filter((r) =>
            r.state === 'released'
            && r.gh_release_eligible
            && r.ts !== null
            && (r.gh === null || !!r.hf?.stale_since || (r.ts && summary?.produced_at && r.ts.produced_at > summary.produced_at)),
        ).length,
    );

    /** Disabled reason for the Cut button — null when enabled. */
    const cutDisabledReason = $derived.by(() => {
        if (inFlight.some((j) => j.kind === 'cut_release')) {
            return 'A cut is already in flight';
        }
        // Nothing-changed: there IS a current release AND no row has TS
        // newer than the cut's produced_at AND no member is stale.
        if (summary && summary.produced_at) {
            const cutAt = summary.produced_at;
            const anyFresher = allRows.some((r) =>
                r.gh_release_eligible
                && r.ts !== null
                && r.ts.produced_at > cutAt,
            );
            const anyStaleMember = allRows.some(
                (r) => r.gh_release_eligible && !!r.gh?.stale_since,
            );
            const anyAdded = allRows.some(
                (r) =>
                    r.gh_release_eligible
                    && r.state === 'released'
                    && r.ts !== null
                    && r.gh === null,
            );
            if (!anyFresher && !anyStaleMember && !anyAdded) {
                return 'Nothing changed since last cut';
            }
        }
        return null;
    });

    // ---- collapse persistence ----
    const COLLAPSE_LS_KEY = 'insp_releases_collapsed';
    function loadCollapsed(): Record<ReleasesBucket, boolean> {
        const fallback: Record<ReleasesBucket, boolean> = {
            in_flight: false, stale_hf: false, waiting: false,
            published_current: true, excluded: true,
        };
        try {
            const raw = localStorage.getItem(COLLAPSE_LS_KEY);
            if (!raw) return fallback;
            const parsed = JSON.parse(raw) as Partial<Record<ReleasesBucket, boolean>>;
            return {
                in_flight: parsed.in_flight ?? fallback.in_flight,
                stale_hf: parsed.stale_hf ?? fallback.stale_hf,
                waiting: parsed.waiting ?? fallback.waiting,
                published_current: parsed.published_current ?? fallback.published_current,
                excluded: parsed.excluded ?? fallback.excluded,
            };
        } catch {
            return fallback;
        }
    }
    let collapsed = $state<Record<ReleasesBucket, boolean>>(loadCollapsed());

    function toggle(key: ReleasesBucket): void {
        collapsed[key] = !collapsed[key];
        try { localStorage.setItem(COLLAPSE_LS_KEY, JSON.stringify(collapsed)); }
        catch { /* ignore */ }
    }

    // ---- actions ----
    async function onPublish(slug: string): Promise<void> {
        if (busySlug !== null) return;
        busySlug = slug;
        rowError = null;
        try {
            await publishHf(slug);
            refetch();   // the server cache is already busted; this gets the new in_flight
        } catch (e) {
            rowError = { slug, message: (e as Error).message ?? 'Publish failed' };
        } finally {
            busySlug = null;
        }
    }

    function onCutComplete(): void {
        cutModalOpen = false;
        refetch();
    }

    function scrollToInFlight(): void {
        // Expand the section first (it's only mounted when non-empty, but
        // could be collapsed by the operator) and then scroll into view.
        collapsed.in_flight = false;
        try { localStorage.setItem(COLLAPSE_LS_KEY, JSON.stringify(collapsed)); }
        catch { /* ignore */ }
        // Defer one tick so the {#if} mounts before the scroll. Locate the
        // section by data attribute — Svelte 5 doesn't allow a conditional
        // bind:this inside an each-loop.
        queueMicrotask(() => {
            const el = listAreaEl?.querySelector<HTMLElement>('[data-section="in_flight"]');
            el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    }
</script>

<div class="releases">
    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error" role="alert">{error}</div>
    {:else}
        <ReleasesSummaryCard
            summary={summary}
            inFlight={inFlight}
            readyCount={readyCount}
            onCut={() => (cutModalOpen = true)}
            cutDisabledReason={cutDisabledReason}
            onJumpToInFlight={scrollToInFlight}
        />

        <!-- Sticky filter bar — mirrors Reviews. -->
        <div class="filter-bar">
            <span class="search">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14.5" y2="14.5" />
                </svg>
                <input
                    type="text"
                    placeholder="Search reciter (Arabic or Latin)"
                    value={releasesStore.filters.q}
                    oninput={(e) => releasesStore.setQ((e.currentTarget as HTMLInputElement).value)}
                />
            </span>

            <div class="facet-group">
                <span class="facet-label">Riwayah</span>
                {#each riwayahValues as [val, count] (val)}
                    <button class="chip" class:active={releasesStore.filters.riwayah === val}
                        type="button" onclick={() => releasesStore.toggleFacet('riwayah', val)}>
                        {val} <span class="c-count">{count}</span>
                    </button>
                {/each}
            </div>

            <div class="facet-group">
                <span class="facet-label">Style</span>
                {#each styleValues as [val, count] (val)}
                    <button class="chip" class:active={releasesStore.filters.style === val}
                        type="button" onclick={() => releasesStore.toggleFacet('style', val)}>
                        {val} <span class="c-count">{count}</span>
                    </button>
                {/each}
            </div>

            <div class="facet-group">
                <span class="facet-label">Channel</span>
                {#each channelValues as [val, count] (val)}
                    <button class="chip" class:active={releasesStore.filters.channel === val}
                        type="button" onclick={() => releasesStore.toggleFacet('channel', val)}>
                        {val} <span class="c-count">{count}</span>
                    </button>
                {/each}
            </div>

            <div class="filter-trail">
                <label class="sort">
                    <span>sort</span>
                    <select
                        value={releasesStore.sortBy}
                        onchange={(e) => releasesStore.setSort(
                            (e.currentTarget as HTMLSelectElement).value as 'stalest' | 'name',
                        )}
                    >
                        <option value="stalest">stalest first</option>
                        <option value="name">name</option>
                    </select>
                </label>
                {#if releasesStore.hasActiveFilters}
                    <button class="clear-btn" type="button" onclick={() => releasesStore.clearFilters()}>
                        Clear
                    </button>
                {/if}
            </div>
        </div>

        <div class="list-area" bind:this={listAreaEl}>
            {#if narrowedToZero}
                <div class="narrowed">
                    <span>No recitations match the active filter.</span>
                    <button class="clear-link" type="button" onclick={() => releasesStore.clearFilters()}>
                        Clear filters
                    </button>
                </div>
            {/if}

            {#each SECTIONS as section (section.key)}
                {@const rows = bucketed[section.key]}
                {#if !(section.hideWhenEmpty && rows.length === 0)}
                    <section
                        class="state-section"
                        class:collapsed={collapsed[section.key]}
                        data-section={section.key}
                    >
                        <button
                            class="state-head"
                            type="button"
                            aria-expanded={!collapsed[section.key]}
                            onclick={() => toggle(section.key)}
                        >
                            <span class="state-mark mark-{section.mark}"></span>
                            <span class="state-name">{section.label}</span>
                            <span class="state-count">{rows.length}</span>
                            <span class="state-toggle" aria-hidden="true">▾</span>
                        </button>
                        {#if !collapsed[section.key]}
                            <div class="state-body">
                                {#if rows.length === 0}
                                    <div class="empty-line">No items.</div>
                                {:else}
                                    <div class="row-list">
                                        {#each rows as row (row.slug)}
                                            <ReleasesRow
                                                row={row}
                                                bucket={section.key}
                                                inFlightJob={section.key === 'in_flight' ? jobForSlug(row.slug) : null}
                                                busy={busySlug === row.slug}
                                                errorMessage={rowError?.slug === row.slug ? rowError.message : null}
                                                onPublish={onPublish}
                                            />
                                        {/each}
                                    </div>
                                {/if}
                            </div>
                        {/if}
                    </section>
                {/if}
            {/each}
        </div>
    {/if}

    {#if cutModalOpen}
        <CutReleaseModal onclose={() => (cutModalOpen = false)} onsuccess={onCutComplete} />
    {/if}
</div>

<style>
    .releases {
        position: relative;
        display: flex;
        flex-direction: column;
        padding: var(--s-3) var(--s-5) 0;
        gap: var(--s-3);
        height: 100%;
        overflow: hidden;
    }
    .list-area {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
        padding-bottom: var(--s-5);
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }

    .state {
        padding: var(--s-12) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.error { color: var(--state-error-fg); }

    .state-head {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-2) var(--s-1);
        background: transparent;
        border: 0;
        border-bottom: 1px solid var(--border-quiet);
        width: 100%;
        cursor: pointer;
        font: inherit;
        color: var(--text-primary);
        text-align: left;
        user-select: none;
    }
    .state-head:hover { background: var(--panel); }

    .state-mark {
        width: 8px;
        height: 8px;
        border-radius: 1px;
        flex: 0 0 auto;
    }
    /* Section mark colours — reuse Reviews palette to keep the visual family
     * coherent across compartments. */
    .mark-inflight  { background: var(--state-under-review-fg); }
    .mark-stale     { background: oklch(0.84 0.130 70); }
    .mark-waiting   { background: var(--state-available-fg); }
    .mark-published { background: var(--state-published-fg); }
    .mark-excluded  { background: var(--text-faint); }

    .state-name {
        font-size: var(--fs-row);
        font-weight: 500;
        color: var(--text-primary);
    }
    .state-count {
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        font-variant-numeric: tabular-nums;
    }
    .state-toggle {
        margin-left: auto;
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: 11px;
        transition: transform var(--t-fast) var(--ease-out-quart);
    }
    .state-section.collapsed .state-toggle { transform: rotate(-90deg); }

    .state-body { padding: 0; }
    .empty-line {
        font-size: var(--fs-body);
        color: var(--text-faint);
        padding: var(--s-3) var(--s-1);
    }
    .row-list { display: flex; flex-direction: column; }

    /* filter bar — same primitives as ReviewsCompartment. */
    .filter-bar {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        flex-wrap: wrap;
        padding: var(--s-1) var(--s-1) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-2);
    }
    .search {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        height: 28px;
        padding: 0 var(--s-3);
        min-width: 220px;
        color: var(--text-muted);
        flex: 0 0 auto;
    }
    .search svg { width: 14px; height: 14px; flex-shrink: 0; }
    .search input {
        flex: 1;
        background: transparent;
        border: 0;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        outline: 0;
        min-width: 120px;
    }
    .search input::placeholder { color: var(--text-faint); }
    .search:focus-within {
        border-color: var(--accent-tint);
        box-shadow: 0 0 0 2px var(--accent-tint-soft);
    }

    .facet-group {
        display: flex;
        align-items: center;
        gap: 6px;
        max-width: 100%;
        flex-wrap: wrap;
    }
    .facet-label {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
        margin-right: 2px;
    }
    .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        height: 24px;
        padding: 0 8px;
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: var(--text-secondary);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
        white-space: nowrap;
        transition: color var(--t-fast), border-color var(--t-fast), background-color var(--t-fast);
    }
    .chip:hover { border-color: var(--border-default); color: var(--text-primary); }
    .chip.active {
        color: var(--text-primary);
        border-color: var(--accent-tint);
        background: var(--accent-tint-soft);
    }
    .c-count {
        font-family: var(--font-mono);
        color: var(--text-faint);
        font-size: 10px;
        font-variant-numeric: tabular-nums;
    }
    .chip.active .c-count { color: var(--accent-strong); }

    .filter-trail {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        margin-left: auto;
    }
    .sort {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .sort select {
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font: inherit;
        font-size: 11px;
        padding: 3px 6px;
        border-radius: var(--r-1);
        cursor: pointer;
    }
    .sort select:focus { outline: 0; border-color: var(--accent-tint); }

    .clear-btn {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-muted);
        font: inherit;
        font-size: 11px;
        padding: 3px 10px;
        border-radius: var(--r-1);
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .clear-btn:hover { color: var(--text-primary); border-color: var(--border-default); }

    .narrowed {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-1);
        color: var(--text-muted);
        font-size: var(--fs-meta);
        border-bottom: 1px solid var(--border-quiet);
        margin-bottom: var(--s-2);
    }
    .clear-link {
        background: transparent;
        border: 0;
        color: var(--accent);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0;
    }
    .clear-link:hover { color: var(--accent-strong); text-decoration: underline; }
</style>
