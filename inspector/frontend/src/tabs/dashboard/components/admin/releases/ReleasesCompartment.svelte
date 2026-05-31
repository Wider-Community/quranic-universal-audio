<script lang="ts">
    /**
     * Releases compartment (admin Releases tab).
     *
     * Two panes:
     *   1. **Per-recitation status grid** — every recitation with TS/HF/GH
     *      badges. Row action: "Publish to HF" (also surfaces as "Re-publish"
     *      when the HF row is stale).
     *   2. **Global card** — latest GH release + "Cut new release" button that
     *      opens the two-step preview/confirm modal.
     *
     * Status pulled from ``/api/admin/releases/status``; mutations through
     * publishHf() per-row and the CutReleaseModal globally.
     */
    import { isOwner } from '../../../../../lib/stores/current-user';
    import {
        type LatestGhRelease,
        type ReleaseStatusRow,
        fetchReleasesStatus,
        publishHf,
    } from '../../../../../lib/api/admin-releases';
    import CutReleaseModal from './CutReleaseModal.svelte';

    let rows = $state<ReleaseStatusRow[]>([]);
    let latestGh = $state<LatestGhRelease | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let cutModalOpen = $state(false);
    let busySlug = $state<string | null>(null);
    let rowError = $state<{ slug: string; message: string } | null>(null);
    let filterText = $state('');

    async function load(): Promise<void> {
        loading = true;
        error = null;
        try {
            const r = await fetchReleasesStatus();
            rows = r.recitations;
            latestGh = r.latest_gh_release;
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load releases status';
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        void load();
    });

    const filteredRows = $derived(
        filterText.trim()
            ? rows.filter((r) => {
                  const q = filterText.trim().toLowerCase();
                  return (
                      r.slug.toLowerCase().includes(q) ||
                      (r.name_en ?? '').toLowerCase().includes(q) ||
                      r.riwayah.toLowerCase().includes(q) ||
                      r.channel.toLowerCase().includes(q)
                  );
              })
            : rows,
    );

    function canPublishHf(r: ReleaseStatusRow): boolean {
        // Need a current TS row; re-publish is allowed (refreshes the HF parquet).
        return r.ts !== null;
    }

    async function onPublish(slug: string): Promise<void> {
        if (busySlug !== null) return;
        busySlug = slug;
        rowError = null;
        try {
            await publishHf(slug);
            // Refresh after a brief moment so the new job_id reflects.
            await load();
        } catch (e) {
            rowError = { slug, message: (e as Error).message ?? 'Publish failed' };
        } finally {
            busySlug = null;
        }
    }

    function onCutComplete(): void {
        cutModalOpen = false;
        void load();
    }

    function formatDate(iso: string | null | undefined): string {
        if (!iso) return '—';
        try {
            return new Date(iso).toLocaleDateString();
        } catch {
            return iso;
        }
    }

    function tsBadge(r: ReleaseStatusRow): { kind: 'ok' | 'none'; label: string } {
        if (!r.ts) return { kind: 'none', label: '—' };
        return { kind: 'ok', label: 'Available' };
    }

    function hfBadge(
        r: ReleaseStatusRow,
    ): { kind: 'ok' | 'stale' | 'none'; label: string } {
        if (!r.hf) return { kind: 'none', label: '—' };
        if (r.hf.stale_since) return { kind: 'stale', label: 'Stale' };
        return { kind: 'ok', label: 'Published' };
    }

    function ghBadge(
        r: ReleaseStatusRow,
    ): { kind: 'ok' | 'stale' | 'excluded' | 'none'; label: string } {
        if (!r.gh_release_eligible) return { kind: 'excluded', label: 'Excluded' };
        if (!r.gh) return { kind: 'none', label: '—' };
        if (r.gh.stale_since) {
            return { kind: 'stale', label: `Stale (${r.gh.change_kind})` };
        }
        return { kind: 'ok', label: r.gh.change_kind };
    }

    function publishButtonLabel(r: ReleaseStatusRow): string {
        if (!r.hf) return 'Publish to HF';
        if (r.hf.stale_since) return 'Re-publish (stale)';
        return 'Re-publish';
    }
</script>

<section class="rel-comp">
    <header class="rel-head">
        <h3>Releases</h3>
        <div class="rel-head-row">
            <div class="rel-latest">
                {#if latestGh}
                    <strong>Latest GH release:</strong>
                    {#if latestGh.external_uri}
                        <a href={latestGh.external_uri} target="_blank" rel="noopener">
                            {latestGh.version}
                        </a>
                    {:else}
                        {latestGh.version}
                    {/if}
                    <span class="rel-faint">({formatDate(latestGh.produced_at)})</span>
                {:else}
                    <span class="rel-faint">No GH release cut yet</span>
                {/if}
            </div>
            {#if $isOwner}
                <button
                    type="button"
                    class="rel-cut-btn"
                    onclick={() => (cutModalOpen = true)}
                    disabled={loading || error !== null}
                >
                    Cut new release…
                </button>
            {/if}
        </div>
    </header>

    {#if loading}
        <div class="rel-loading">Loading…</div>
    {:else if error}
        <div class="rel-error">{error}</div>
    {:else}
        <div class="rel-filter">
            <input
                type="search"
                placeholder="Filter by slug, name, riwayah, channel…"
                bind:value={filterText}
            />
            <span class="rel-faint">{filteredRows.length} / {rows.length}</span>
        </div>
        <div class="rel-table-wrap">
            <table class="rel-table">
                <thead>
                    <tr>
                        <th>Slug</th>
                        <th>Name</th>
                        <th>Channel</th>
                        <th>TS</th>
                        <th>HF</th>
                        <th>GH</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each filteredRows as r (r.slug)}
                        {@const tb = tsBadge(r)}
                        {@const hb = hfBadge(r)}
                        {@const gb = ghBadge(r)}
                        <tr>
                            <td class="mono">{r.slug}</td>
                            <td>{r.name_en ?? r.slug}</td>
                            <td class="mono small">{r.channel}</td>
                            <td><span class="rel-badge rel-badge--{tb.kind}">{tb.label}</span></td>
                            <td><span class="rel-badge rel-badge--{hb.kind}">{hb.label}</span></td>
                            <td><span class="rel-badge rel-badge--{gb.kind}">{gb.label}</span></td>
                            <td class="rel-actions">
                                {#if canPublishHf(r)}
                                    <button
                                        type="button"
                                        class="rel-pub-btn"
                                        onclick={() => onPublish(r.slug)}
                                        disabled={busySlug !== null}
                                    >
                                        {busySlug === r.slug ? 'Launching…' : publishButtonLabel(r)}
                                    </button>
                                {:else}
                                    <span class="rel-faint">No TS</span>
                                {/if}
                                {#if rowError && rowError.slug === r.slug}
                                    <div class="rel-row-err">{rowError.message}</div>
                                {/if}
                            </td>
                        </tr>
                    {/each}
                    {#if filteredRows.length === 0}
                        <tr>
                            <td colspan="7" class="rel-empty">No recitations match this filter.</td>
                        </tr>
                    {/if}
                </tbody>
            </table>
        </div>
    {/if}

    {#if cutModalOpen}
        <CutReleaseModal onclose={() => (cutModalOpen = false)} onsuccess={onCutComplete} />
    {/if}
</section>

<style>
    .rel-comp { display: flex; flex-direction: column; gap: var(--s-3); padding: var(--s-3) 0; }
    .rel-head { display: flex; flex-direction: column; gap: var(--s-2); }
    .rel-head h3 { margin: 0; font-size: var(--fs-h4); color: var(--text-primary); }
    .rel-head-row { display: flex; align-items: center; justify-content: space-between; gap: var(--s-3); }
    .rel-latest { color: var(--text-secondary); font-size: var(--fs-body); }
    .rel-latest strong { color: var(--text-primary); margin-right: var(--s-1); }
    .rel-latest a { color: var(--accent); text-decoration: none; }
    .rel-latest a:hover { text-decoration: underline; }
    .rel-faint { color: var(--text-faint); }
    .rel-cut-btn {
        background: var(--accent); color: var(--text-on-accent);
        border: 0; border-radius: var(--r-1); padding: var(--s-1) var(--s-3);
        font-size: var(--fs-body); cursor: pointer;
    }
    .rel-cut-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .rel-loading, .rel-error { padding: var(--s-3); color: var(--text-secondary); }
    .rel-error { color: var(--accent-danger, #c0392b); }
    .rel-filter { display: flex; align-items: center; gap: var(--s-2); }
    .rel-filter input {
        flex: 1; padding: var(--s-1) var(--s-2);
        border: 1px solid var(--border); border-radius: var(--r-1);
        background: var(--surface-1); color: var(--text-primary);
        font-size: var(--fs-body);
    }
    .rel-table-wrap { overflow-x: auto; }
    .rel-table { width: 100%; border-collapse: collapse; font-size: var(--fs-body); }
    .rel-table th, .rel-table td {
        text-align: left; padding: var(--s-1) var(--s-2);
        border-bottom: 1px solid var(--border-subtle);
        vertical-align: middle;
    }
    .rel-table th { color: var(--text-secondary); font-weight: 500; font-size: var(--fs-small); }
    .mono { font-family: var(--font-mono); font-size: var(--fs-small); }
    .small { font-size: var(--fs-small); }
    .rel-empty { color: var(--text-faint); text-align: center; padding: var(--s-4); }
    .rel-actions { white-space: nowrap; }
    .rel-pub-btn {
        background: transparent; color: var(--accent);
        border: 1px solid var(--accent); border-radius: var(--r-1);
        padding: 2px var(--s-2); font-size: var(--fs-small); cursor: pointer;
    }
    .rel-pub-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .rel-row-err {
        color: var(--accent-danger, #c0392b); font-size: var(--fs-small);
        margin-top: 2px;
    }
    .rel-badge {
        display: inline-block; padding: 1px var(--s-1);
        font-size: var(--fs-small); border-radius: 3px;
        font-family: var(--font-mono);
    }
    .rel-badge--ok { background: var(--accent-tint); color: var(--accent); }
    .rel-badge--stale { background: #fff3cd; color: #856404; }
    .rel-badge--excluded { background: #f5c6cb; color: #721c24; }
    .rel-badge--none { color: var(--text-faint); }
</style>
