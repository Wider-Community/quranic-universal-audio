<script lang="ts">
    /**
     * Requests compartment: status facets + a review queue. Clicking a pending
     * row expands an inline review panel (proposed-changes diff + requester
     * note + owner-only resolve actions). Expanding a pending request marks it
     * "viewed" for the caller (clears the unviewed dot/pill). Maintainers are
     * read-only; only owners see Send back / Discard.
     */
    import {
        fetchRequests,
        markRequestViewed,
        type RequestStatus,
    } from '../../../../lib/api/admin-requests';
    import { rejectRequestHard, rejectRequestSoft } from '../../../../lib/api/requests';
    import { isOwner } from '../../../../lib/stores/current-user';
    import type {
        AdminRequestRow,
        AdminRequestsResponse,
    } from '../../../../lib/types/generated/schemas';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';
    import { relativeTime } from '../../../../lib/utils/relative-time';
    import { visiblePoll } from '../../../../lib/utils/visible-poll';
    import { adminDashboard } from '../../stores/admin-dashboard.svelte';

    const STALE_DAYS = 7;

    let status = $state<RequestStatus>('open');
    let resp = $state<AdminRequestsResponse | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let expandedId = $state<string | null>(null);

    // Per-expanded-row resolve state (owner only).
    let reason = $state('');
    let busyId = $state<string | null>(null);
    let actionError = $state<string | null>(null);

    function applyResult(r: AdminRequestsResponse): void {
        resp = r;
        adminDashboard.setUnviewedRequests(r.unviewed_count ?? 0);
        loading = false;
        error = null;
    }

    // Fetch the active facet on mount + whenever it changes, and keep it warm
    // while the modal stays open. visiblePoll fetches immediately on start.
    $effect(() => {
        const s = status;
        loading = true;
        error = null;
        expandedId = null;
        const teardown = visiblePoll<AdminRequestsResponse>({
            intervalMs: 30_000,
            fetcher: (signal) => fetchRequests(s, signal),
            onResult: applyResult,
            onError: (e) => {
                loading = false;
                error = (e as Error).message ?? 'Failed to load requests';
            },
        });
        return () => teardown();
    });

    async function toggle(row: AdminRequestRow): Promise<void> {
        if (expandedId === row.id) {
            expandedId = null;
            return;
        }
        expandedId = row.id;
        reason = '';
        actionError = null;

        // Mark viewed on first open of an unviewed open request (optimistic).
        if (status === 'open' && !row.viewed) {
            row.viewed = true;
            adminDashboard.setUnviewedRequests(adminDashboard.unviewedRequests - 1);
            try {
                await markRequestViewed(row.id);
            } catch {
                // Best-effort: the next poll reconciles the authoritative count.
            }
        }
    }

    async function resolve(row: AdminRequestRow, kind: 'soft' | 'hard'): Promise<void> {
        if (!row.slug || reason.trim().length < 10 || busyId) return;
        busyId = row.id;
        actionError = null;
        try {
            if (kind === 'soft') await rejectRequestSoft(row.slug, reason.trim());
            else await rejectRequestHard(row.slug, reason.trim());
            expandedId = null;
            reason = '';
            applyResult(await fetchRequests(status));
        } catch (e) {
            // Includes the resolved-while-open race (404 / InvalidTransition):
            // surface it, then refetch so the list reflects reality.
            actionError =
                (e as Error).message ?? 'This request may already be resolved.';
            try {
                applyResult(await fetchRequests(status));
            } catch {
                /* leave the error visible */
            }
        } finally {
            busyId = null;
        }
    }

    function comboLabel(row: AdminRequestRow): string {
        const r = row.riwayah ? titleCaseSlug(row.riwayah) : '';
        const s = row.style ? titleCaseSlug(row.style) : '';
        return [r, s].filter(Boolean).join('  ·  ');
    }

    function changeSummary(row: AdminRequestRow): string {
        const n = row.changes?.length ?? 0;
        if (n === 0) return 'no metadata changes';
        return `${n} proposed change${n === 1 ? '' : 's'}`;
    }

    function fmt(v: string | number | null | undefined): string {
        return v === null || v === undefined || v === '' ? '—' : String(v);
    }

    function isStale(row: AdminRequestRow): boolean {
        if (!row.submitted_at) return false;
        const ms = Date.now() - Date.parse(row.submitted_at);
        return ms > STALE_DAYS * 86_400_000;
    }

    const FACETS: { id: RequestStatus; label: string }[] = [
        { id: 'open', label: 'Open' },
        { id: 'accepted', label: 'Accepted' },
        { id: 'returned', label: 'Sent back' },
        { id: 'discarded', label: 'Discarded' },
    ];

    const rows = $derived(resp?.rows ?? []);
    const counts = $derived(
        resp?.counts ?? { open: 0, accepted: 0, returned: 0, discarded: 0 },
    );
    function facetCount(id: RequestStatus): number {
        return (counts as Record<string, number>)[id] ?? 0;
    }
</script>

<div class="reqs">
    <div class="reqs-toolbar">
        <div class="status-filters">
            {#each FACETS as f (f.id)}
                <button
                    class="chip"
                    class:active={status === f.id}
                    class:empty={facetCount(f.id) === 0}
                    onclick={() => (status = f.id)}
                >
                    {f.label}
                    <span class="c-count">{facetCount(f.id)}</span>
                </button>
            {/each}
        </div>
        <span class="toolbar-spacer"></span>
        <span class="toolbar-total">{rows.length} {status === 'open' ? 'open' : 'shown'}</span>
    </div>

    {#if loading}
        <div class="state">Loading…</div>
    {:else if error}
        <div class="state error">{error}</div>
    {:else if rows.length === 0}
        <div class="state empty">
            <div class="glyph">⌖</div>
            <h4>{status === 'open' ? 'No open requests' : 'Nothing here'}</h4>
            <p>
                {status === 'open'
                    ? 'When a contributor requests a reciter combination, it lands here for review.'
                    : 'No requests with this status yet.'}
            </p>
        </div>
    {:else}
        <ol class="queue">
            {#each rows as row (row.id)}
                <li class="req" class:open={expandedId === row.id}>
                    <button
                        class="req-head"
                        aria-expanded={expandedId === row.id}
                        onclick={() => toggle(row)}
                    >
                        <span class="who">
                            {#if status === 'open' && !row.viewed}
                                <span class="unread" aria-label="Unviewed"></span>
                            {/if}
                            {#if row.name_ar}
                                <span class="name-ar" dir="rtl">{row.name_ar}</span>
                            {/if}
                            <span class="name-en">{row.name_en ?? row.slug}</span>
                        </span>
                        <span class="combo">{comboLabel(row)}</span>
                        <span class="changes" class:none={(row.changes?.length ?? 0) === 0}>
                            {changeSummary(row)}
                        </span>
                        <span class="req-meta">
                            {#if row.auto_claim}
                                <span class="req-tag self" title="Requester will be auto-assigned as reviewer when alignment completes">self-review</span>
                            {/if}
                            <span class="requester" class:redacted={!row.requester_login}>
                                {row.requester_login ? `@${row.requester_login}` : (row.requester_role ?? 'contributor')}
                            </span>
                            {#if status === 'open'}
                                <time class="req-age" class:stale={isStale(row)} datetime={row.submitted_at}>
                                    {relativeTime(row.submitted_at)}
                                </time>
                                <span class="chev">▸</span>
                            {:else}
                                <span class="outcome {status}">
                                    {status === 'accepted' ? 'Accepted' : status === 'returned' ? 'Sent back' : 'Discarded'}
                                </span>
                            {/if}
                        </span>
                    </button>

                    {#if expandedId === row.id}
                        <div class="review">
                            <div class="review-grid">
                                <div>
                                    <h4>Proposed changes</h4>
                                    {#if (row.changes?.length ?? 0) === 0}
                                        <p class="no-changes">No metadata changes — alignment request only.</p>
                                    {:else}
                                        <dl class="diff">
                                            {#each row.changes ?? [] as c (c.field)}
                                                <div class="diff-row" class:rtl={c.field === 'name_ar'}>
                                                    <dt>{c.label}</dt>
                                                    <dd>
                                                        <span class="from">{fmt(c.from)}</span>
                                                        <span class="arrow">→</span>
                                                        <span class="to">{fmt(c.to)}</span>
                                                    </dd>
                                                </div>
                                            {/each}
                                        </dl>
                                    {/if}
                                </div>

                                <div class="review-side">
                                    <p class="submitted-by">
                                        {#if row.requester_login}
                                            Submitted by <strong>@{row.requester_login}</strong>
                                        {:else}
                                            Submitted by <strong>a {row.requester_role ?? 'contributor'}</strong>
                                        {/if}
                                        {#if row.submitted_at}· {relativeTime(row.submitted_at)}{/if}
                                    </p>

                                    {#if row.comments}
                                        <p class="note">
                                            <span class="note-label">Requester note</span>
                                            {row.comments}
                                        </p>
                                    {/if}

                                    {#if row.conflict}
                                        <p class="notice">
                                            Another delivery of {row.name_en ?? 'this reciter'} already uses
                                            this riwayah · style. The edit still applies on acceptance.
                                        </p>
                                    {/if}

                                    {#if status === 'open'}
                                        {#if $isOwner}
                                            <div class="resolve">
                                                <textarea
                                                    bind:value={reason}
                                                    rows="2"
                                                    maxlength="500"
                                                    placeholder="Reason (≥10 chars) — recorded in the audit log"
                                                ></textarea>
                                                {#if actionError}
                                                    <p class="action-error">{actionError}</p>
                                                {/if}
                                                <div class="resolve-foot">
                                                    <span class="resolve-hint">Required for both actions.</span>
                                                    <div class="resolve-actions">
                                                        <button
                                                            class="btn"
                                                            disabled={reason.trim().length < 10 || busyId === row.id}
                                                            onclick={() => resolve(row, 'soft')}
                                                        >Send back</button>
                                                        <button
                                                            class="btn danger"
                                                            disabled={reason.trim().length < 10 || busyId === row.id}
                                                            onclick={() => resolve(row, 'hard')}
                                                        >Discard</button>
                                                    </div>
                                                </div>
                                            </div>
                                        {:else}
                                            <p class="ro-note">Resolving a request is owner-only.</p>
                                        {/if}
                                    {:else}
                                        <div class="resolution">
                                            <span class="res-by">
                                                {#if row.resolved_by_login}
                                                    {status === 'accepted' ? 'Accepted' : status === 'returned' ? 'Sent back' : 'Discarded'}
                                                    by <strong>@{row.resolved_by_login}</strong>
                                                {:else if status === 'accepted'}
                                                    Accepted by the alignment pipeline
                                                {:else}
                                                    {status === 'returned' ? 'Sent back' : 'Discarded'}
                                                    by <strong>a {row.resolved_by_role ?? 'maintainer'}</strong>
                                                {/if}
                                                {#if row.resolved_at}· {relativeTime(row.resolved_at)}{/if}
                                            </span>
                                            {#if row.resolution_reason}
                                                <span class="res-reason">— {row.resolution_reason}</span>
                                            {/if}
                                        </div>
                                    {/if}
                                </div>
                            </div>
                        </div>
                    {/if}
                </li>
            {/each}
        </ol>
    {/if}
</div>

<style>
    .reqs { display: flex; flex-direction: column; height: 100%; min-height: 0; }

    .state { padding: var(--s-12) 0; text-align: center; color: var(--text-muted); font-size: var(--fs-meta); }
    .state.error { color: var(--state-error-fg); }
    .state.empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--s-2); }
    .state.empty .glyph { font-size: 26px; opacity: 0.5; }
    .state.empty h4 { margin: 0; font-size: var(--fs-row); font-weight: 500; color: var(--text-secondary); }
    .state.empty p { margin: 0; font-size: var(--fs-meta); color: var(--text-faint); max-width: 44ch; }

    .reqs-toolbar {
        display: flex; align-items: center; gap: var(--s-4);
        padding: var(--s-4) var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
        flex-shrink: 0;
    }
    .status-filters { display: inline-flex; gap: var(--s-2); }
    .chip {
        display: inline-flex; align-items: center; gap: var(--s-2);
        height: 28px; padding: 0 var(--s-3);
        background: transparent; border: 1px solid var(--border-quiet);
        border-radius: 999px; color: var(--text-secondary); font-size: var(--fs-meta);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .chip:hover { border-color: var(--border-strong); color: var(--text-primary); }
    .chip .c-count { font-family: var(--font-mono); font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--text-faint); }
    .chip.active { background: var(--accent-tint); border-color: var(--accent); color: var(--accent); }
    .chip.active .c-count { color: var(--accent); }
    .chip.empty { opacity: 0.45; }
    .toolbar-spacer { flex: 1; }
    .toolbar-total { font-size: var(--fs-meta); color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }

    .queue { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; min-height: 0; }
    .req { border-bottom: 1px solid var(--border-quiet); }
    .req:last-child { border-bottom: none; }

    .req-head {
        display: grid;
        grid-template-columns: minmax(0, 1.6fr) 0.9fr 1fr auto;
        align-items: center;
        gap: var(--s-4);
        width: 100%;
        padding: var(--s-4) var(--s-5);
        text-align: left;
        background: transparent; border: 0; cursor: pointer;
        transition: background var(--t-fast);
    }
    .req-head:hover { background: var(--panel); }
    .req.open > .req-head { background: var(--panel); }

    .who { display: flex; align-items: baseline; gap: var(--s-3); min-width: 0; }
    .unread { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); flex-shrink: 0; align-self: center; }
    .name-ar { font-size: var(--fs-h3); color: var(--text-primary); line-height: 1.25; white-space: nowrap; }
    .name-en { font-size: var(--fs-meta); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .combo { font-size: var(--fs-meta); color: var(--text-secondary); white-space: nowrap; }
    .changes { font-size: var(--fs-meta); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .changes.none { color: var(--text-faint); font-style: italic; }

    .req-meta { display: inline-flex; align-items: center; gap: var(--s-3); justify-content: flex-end; white-space: nowrap; }
    .req-tag { display: inline-flex; align-items: center; gap: 5px; padding: 1px 8px; border-radius: 999px; font-size: 10px; font-weight: 500; color: var(--text-secondary); background: oklch(0.62 0.02 268 / 0.16); }
    .req-tag.self { color: var(--accent); background: var(--accent-tint); }
    .req-tag.self::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: var(--accent); }
    .requester { font-size: var(--fs-meta); color: var(--text-secondary); }
    .requester.redacted { color: var(--text-faint); font-style: italic; }
    .req-age { font-size: 10.5px; color: var(--text-faint); font-variant-numeric: tabular-nums; }
    .req-age.stale { color: var(--state-error-fg); }
    .chev { color: var(--text-faint); font-size: 11px; transition: transform var(--t-base) var(--ease-out-quart); }
    .req.open .chev { transform: rotate(90deg); color: var(--text-muted); }

    .outcome { display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 500; }
    .outcome::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
    .outcome.accepted { color: var(--state-published-fg); background: var(--state-published-bg); }
    .outcome.returned { color: var(--state-error-fg); background: oklch(0.86 0.13 75 / 0.14); }
    .outcome.returned::before { border-radius: 1px; }
    .outcome.discarded { color: var(--state-discarded-fg); background: var(--state-discarded-bg); }

    .review {
        padding: var(--s-2) var(--s-5) var(--s-5);
        background: var(--panel);
        border-top: 1px solid var(--border-quiet);
        animation: review-in var(--t-base) var(--ease-out-quart);
    }
    @keyframes review-in {
        from { opacity: 0; transform: translateY(-4px); }
        to { opacity: 1; transform: none; }
    }
    .review-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: var(--s-6); align-items: start; }
    .review h4 { margin: 0 0 var(--s-3); font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); font-weight: 500; }

    .diff { margin: 0; }
    .diff-row { display: grid; grid-template-columns: 120px 1fr; gap: var(--s-3); align-items: baseline; padding: var(--s-2) 0; border-bottom: 1px solid var(--border-quiet); }
    .diff-row:last-child { border-bottom: none; }
    .diff-row dt { color: var(--text-muted); font-size: var(--fs-meta); }
    .diff-row dd { margin: 0; font-size: var(--fs-body); }
    .diff-row .from { color: var(--text-faint); text-decoration: line-through; }
    .diff-row .arrow { margin: 0 var(--s-2); color: var(--text-faint); }
    .diff-row .to { color: var(--text-primary); }
    .diff-row.rtl .to { direction: rtl; unicode-bidi: isolate; }
    .no-changes { font-size: var(--fs-meta); color: var(--text-faint); font-style: italic; padding: var(--s-2) 0; }

    .review-side { display: flex; flex-direction: column; gap: var(--s-4); }
    .submitted-by { margin: 0; font-size: var(--fs-meta); color: var(--text-muted); }
    .submitted-by strong { color: var(--text-secondary); font-weight: 500; }
    .note { margin: 0; padding: var(--s-3); background: var(--canvas-inset); border: 1px solid var(--border-quiet); border-radius: var(--r-2); font-size: var(--fs-body); color: var(--text-secondary); line-height: var(--lh-normal); }
    .note .note-label { display: block; font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); margin-bottom: 4px; }
    .notice { margin: 0; padding: var(--s-3); background: var(--state-requested-bg); color: var(--state-requested-fg); border-radius: var(--r-2); font-size: var(--fs-meta); line-height: var(--lh-normal); }
    .ro-note { margin: 0; font-size: var(--fs-meta); color: var(--text-faint); font-style: italic; }

    .resolve { display: flex; flex-direction: column; gap: var(--s-2); padding-top: var(--s-3); border-top: 1px solid var(--border-quiet); }
    .resolve textarea { width: 100%; resize: vertical; min-height: 52px; padding: var(--s-2) var(--s-3); background: var(--canvas-inset); border: 1px solid var(--border-default); border-radius: var(--r-2); color: var(--text-primary); font: var(--fs-body)/var(--lh-normal) var(--font-sans); }
    .resolve textarea:focus { outline: none; border-color: var(--accent); }
    .resolve textarea::placeholder { color: var(--text-faint); }
    .action-error { margin: 0; font-size: var(--fs-meta); color: var(--state-error-fg); }
    .resolve-foot { display: flex; align-items: center; justify-content: space-between; gap: var(--s-3); }
    .resolve-hint { font-size: 10.5px; color: var(--text-faint); }
    .resolve-actions { display: inline-flex; gap: var(--s-2); }
    .btn { padding: 6px 14px; border-radius: var(--r-2); font: 500 var(--fs-meta)/1 var(--font-sans); border: 1px solid var(--border-default); background: transparent; color: var(--text-secondary); cursor: pointer; transition: color var(--t-fast), border-color var(--t-fast), background var(--t-fast); }
    .btn:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .btn:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn.danger { color: var(--state-error-fg); border-color: oklch(0.86 0.13 75 / 0.4); }
    .btn.danger:hover { background: oklch(0.86 0.13 75 / 0.12); border-color: var(--state-error-fg); }

    .resolution { display: flex; flex-wrap: wrap; align-items: baseline; gap: var(--s-2); padding: var(--s-3); background: var(--canvas-inset); border: 1px solid var(--border-quiet); border-radius: var(--r-2); font-size: var(--fs-meta); color: var(--text-muted); line-height: var(--lh-normal); }
    .resolution strong { color: var(--text-secondary); font-weight: 500; }
    .resolution .res-reason { color: var(--text-secondary); }

    @media (prefers-reduced-motion: reduce) {
        .review { animation: none; }
        .chev { transition: none; }
    }
</style>
