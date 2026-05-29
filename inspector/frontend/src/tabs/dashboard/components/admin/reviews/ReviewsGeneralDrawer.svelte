<script lang="ts">
    /**
     * Reviews General drawer.
     *
     * Opens on row body click. Carries everything that's "ambient reference"
     * for one recitation, not tied to a single action: current claim with
     * remove, full reviewer history, fully expanded chronological timeline,
     * lazy-loaded validation counts, passive timestamps-job-id list.
     *
     * Detail payload is one GET; validation counts are a separate lazy GET
     * triggered only when the accordion block expands (the underlying call
     * walks the bucket and is too expensive to eager-fetch).
     */
    import {
        fetchAdminReviewDetail,
        fetchAdminReviewValidation,
    } from '../../../../../lib/api/admin-reviews';
    import { isOwner } from '../../../../../lib/stores/current-user';
    import type {
        AdminReviewDetail,
        AdminReviewValidation,
    } from '../../../../../lib/types/generated/schemas';
    import {
        CHECKLIST_ORDER,
        type ChecklistKey,
        markReadyCopy,
    } from '../../../../segments/copy/mark-ready';
    import { IssueRegistry } from '../../../../segments/domain/registry';
    import ExpandedTimeline from './ExpandedTimeline.svelte';
    import ReviewerActionsPopover from './ReviewerActionsPopover.svelte';

    /** Read a checklist-item label from the same copy module the reviewer
     *  saw. Single source of truth for human-facing strings. */
    function checklistLabelFor(key: ChecklistKey): string {
        const item = markReadyCopy.checklist.find((c) => c.key === key);
        return item?.label ?? key;
    }

    let {
        slug,
        onclose,
        onaction,
    }: {
        slug: string;
        onclose: () => void;
        /** Fired after an action that mutates state — caller refetches list. */
        onaction?: () => void;
    } = $props();

    let detail = $state<AdminReviewDetail | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);

    /** Owner-only reviewer-actions popover (Change / Remove). The trigger is
     * the current-reviewer chip; the popover handles its own dismissal +
     * fires ``onaction`` on success so the drawer + parent list refetch. */
    let popoverOpen = $state(false);

    let valExpanded = $state(false);
    let validation = $state<AdminReviewValidation | null>(null);
    let valLoading = $state(false);
    let valError = $state<string | null>(null);

    // Refetch the detail when the selected slug changes. AbortController
    // prevents stale responses overwriting a fresher one mid-flight.
    $effect(() => {
        const target = slug;
        const ac = new AbortController();
        loading = true;
        error = null;
        detail = null;
        popoverOpen = false;
        valExpanded = false;
        validation = null;
        valError = null;
        fetchAdminReviewDetail(target, ac.signal)
            .then((d) => {
                if (ac.signal.aborted) return;
                if (d === null) {
                    error = 'unknown slug';
                } else {
                    detail = d;
                }
                loading = false;
            })
            .catch((e: unknown) => {
                if (ac.signal.aborted) return;
                error = (e as Error).message ?? 'Failed to load detail';
                loading = false;
            });
        return () => ac.abort();
    });

    function initials(login: string | null | undefined): string {
        if (!login) return '?';
        const trimmed = login.trim();
        if (!trimmed) return '?';
        return (trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2) || trimmed.slice(0, 2)).toUpperCase();
    }

    function fmtDate(iso: string | null | undefined): string {
        if (!iso) return '';
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return iso;
        return d.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
        });
    }

    function fmtDuration(
        fromISO: string | null | undefined,
        toISO: string | null | undefined,
    ): string {
        if (!fromISO || !toISO) return '';
        const from = Date.parse(fromISO);
        const to = Date.parse(toISO);
        if (Number.isNaN(from) || Number.isNaN(to)) return '';
        const secs = Math.max(0, Math.floor((to - from) / 1000));
        const days = Math.floor(secs / 86400);
        if (days >= 1) return `${days}d`;
        const hours = Math.floor(secs / 3600);
        if (hours >= 1) return `${hours}h`;
        const mins = Math.floor(secs / 60);
        return `${mins}m`;
    }

    function fmtRelative(iso: string | null | undefined): string {
        if (!iso) return '';
        const then = Date.parse(iso);
        if (Number.isNaN(then)) return '';
        const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
        if (secs < 60) return `${secs}s ago`;
        const mins = Math.floor(secs / 60);
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        const days = Math.floor(hrs / 24);
        if (days < 7) return `${days}d ago`;
        const weeks = Math.floor(days / 7);
        if (weeks < 8) return `${weeks}w ago`;
        const months = Math.floor(days / 30);
        return `${months}mo ago`;
    }

    // Reviewer history = every claim row OTHER than the current open one.
    const reviewerHistory = $derived(
        (detail?.claim_history ?? []).filter((c) => c.released_at !== null),
    );

    // Validation categories rendered in accordion order from the FE registry
    // (the parity test guarantees alignment with the Python source).
    type CategoryView = { kind: string; title: string; count: number };
    const categoryRows = $derived<CategoryView[]>(
        Object.values(IssueRegistry)
            .slice()
            .sort((a, b) => a.accordionOrder - b.accordionOrder)
            .map((def) => ({
                kind: def.kind,
                title: def.displayTitle,
                count: validation?.category_counts?.[def.kind] ?? 0,
            })),
    );

    async function loadValidation(): Promise<void> {
        if (validation !== null || valLoading) return;
        valLoading = true;
        valError = null;
        try {
            validation = await fetchAdminReviewValidation(slug);
        } catch (e) {
            valError = (e as Error).message ?? "Couldn't compute counts.";
        } finally {
            valLoading = false;
        }
    }

    function toggleValidation(): void {
        valExpanded = !valExpanded;
        if (valExpanded) void loadValidation();
    }

    /** Fired by the popover after a successful Reassign / Force-release.
     * Refetch the drawer detail in place so the current-claim block reflects
     * the new state, then bubble up to the parent so the list refetches. */
    async function onReviewerActionDone(): Promise<void> {
        try {
            const fresh = await fetchAdminReviewDetail(slug);
            if (fresh !== null) detail = fresh;
        } catch {
            /* drawer's bottom-level error already surfaces stale data; the
             * parent list refetch is the durable reconciliation path */
        }
        onaction?.();
    }
</script>

<aside class="drawer" aria-label="Recitation detail">
    <header class="drawer-head">
        <div class="drawer-context">
            <div class="drawer-title">General</div>
            {#if detail}
                {#if detail.name_ar}
                    <div class="recitation-ar" dir="rtl">{detail.name_ar}</div>
                {/if}
                {#if detail.name_en}
                    <div class="recitation-lt">{detail.name_en}</div>
                {/if}
                <div class="recitation-meta">
                    {detail.riwayah} · {detail.style} · {detail.channel} · {detail.state.replace(/_/g, ' ')}
                </div>
            {/if}
        </div>
        <button class="drawer-close" type="button" onclick={onclose} aria-label="Close">
            ×
        </button>
    </header>

    <div class="drawer-body">
        {#if loading}
            <div class="state">Loading…</div>
        {:else if error}
            <div class="state error" role="alert">{error}</div>
        {:else if detail}
            <!-- Current reviewer -->
            <section class="dsection">
                <h3 class="dsection-head">Current reviewer</h3>
                {#if detail.current_claim}
                    <div class="claim-wrap">
                        {#if $isOwner}
                            <button
                                class="current-claim clickable"
                                class:open={popoverOpen}
                                type="button"
                                onclick={() => (popoverOpen = !popoverOpen)}
                                aria-haspopup="dialog"
                                aria-expanded={popoverOpen}
                                title="Click to change or remove the reviewer"
                            >
                                <span class="avatar">{initials(detail.current_claim.login)}</span>
                                <div class="meta">
                                    <div class="who">{detail.current_claim.login ?? 'Unknown'}</div>
                                    <div class="since">
                                        claimed {fmtDate(detail.current_claim.claimed_at)} · {fmtRelative(detail.current_claim.claimed_at)}
                                        {#if detail.current_claim.marked_ready_at}
                                            · marked ready {fmtRelative(detail.current_claim.marked_ready_at)}
                                        {/if}
                                    </div>
                                </div>
                                <span class="caret" aria-hidden="true">▾</span>
                            </button>
                            {#if popoverOpen}
                                <ReviewerActionsPopover
                                    {slug}
                                    currentLogin={detail.current_claim.login ?? null}
                                    onclose={() => (popoverOpen = false)}
                                    onaction={onReviewerActionDone}
                                />
                            {/if}
                        {:else}
                            <!-- Maintainers see the reviewer display as static
                                 text; claim mutations are owner-only. -->
                            <div class="current-claim">
                                <span class="avatar">{initials(detail.current_claim.login)}</span>
                                <div class="meta">
                                    <div class="who">{detail.current_claim.login ?? 'Unknown'}</div>
                                    <div class="since">
                                        claimed {fmtDate(detail.current_claim.claimed_at)} · {fmtRelative(detail.current_claim.claimed_at)}
                                        {#if detail.current_claim.marked_ready_at}
                                            · marked ready {fmtRelative(detail.current_claim.marked_ready_at)}
                                        {/if}
                                    </div>
                                </div>
                            </div>
                        {/if}
                    </div>
                {:else}
                    <div class="empty-block">No open claim on this recitation.</div>
                {/if}
            </section>

            <!-- Mark-ready submission (visible only when the reviewer has
                 submitted the form on the open claim, OR when an owner used
                 the bypass to skip the form). Labels come from the same copy
                 module the reviewer saw — single source of truth.

                 Bypass submissions (`sub.bypass_used`) carry `checklist=null`;
                 we render an "owner bypass" pill and a single explanatory
                 line in place of the checklist tick list. The two comment
                 boxes still render when populated, regardless of mode. -->
            {#if detail.current_claim?.mark_ready_submission}
                {@const sub = detail.current_claim.mark_ready_submission}
                {@const checklist = sub.checklist}
                <section class="dsection mr-submission" class:mr-bypass={sub.bypass_used}>
                    <h3 class="dsection-head">
                        Mark-ready submission
                        {#if sub.bypass_used}
                            <span class="mr-bypass-pill" title="Submitted with the owner-bypass capability">
                                owner bypass
                            </span>
                        {/if}
                        {#if detail.current_claim.marked_ready_at}
                            <span class="aside">submitted {fmtRelative(detail.current_claim.marked_ready_at)}</span>
                        {/if}
                    </h3>
                    {#if sub.bypass_used || !checklist}
                        <p class="mr-bypass-line">
                            Submitted via owner bypass — the form checklist and the
                            zero-count validation gates were skipped.
                        </p>
                    {:else}
                        <ul class="mr-checklist">
                            {#each CHECKLIST_ORDER as key (key)}
                                <li class="mr-check-row" class:done={checklist[key]}>
                                    <span class="mr-check-glyph" aria-hidden="true">
                                        {checklist[key] ? '✓' : '·'}
                                    </span>
                                    <span class="mr-check-label">{checklistLabelFor(key)}</span>
                                </li>
                            {/each}
                        </ul>
                    {/if}
                    {#if (sub.comment_checks ?? '').trim()}
                        <div class="mr-comment">
                            <div class="mr-comment-label">{markReadyCopy.comments.checks.label}</div>
                            <blockquote class="mr-comment-body">{sub.comment_checks}</blockquote>
                        </div>
                    {/if}
                    {#if (sub.comment_issues ?? '').trim()}
                        <div class="mr-comment">
                            <div class="mr-comment-label">{markReadyCopy.comments.issues.label}</div>
                            <blockquote class="mr-comment-body">{sub.comment_issues}</blockquote>
                        </div>
                    {/if}
                </section>
            {/if}

            <!-- Reviewer history -->
            <section class="dsection">
                <h3 class="dsection-head">
                    Reviewer history
                    <span class="aside">{reviewerHistory.length} closed</span>
                </h3>
                {#if reviewerHistory.length === 0}
                    <div class="empty-block">No prior claims.</div>
                {:else}
                    <ul class="history-list">
                        {#each reviewerHistory as h (`${h.assignee_id}_${h.claimed_at}`)}
                            <li class="history-row">
                                <span class="avatar small">{initials(h.login)}</span>
                                <div class="meta">
                                    <div class="who">{h.login ?? 'Unknown'}</div>
                                    <div class="dates">
                                        {fmtDate(h.claimed_at)} · {fmtDate(h.released_at)}
                                        {#if h.close_reason}<span class="close-reason">{h.close_reason.replace(/_/g, ' ')}</span>{/if}
                                    </div>
                                </div>
                                <div class="duration">{fmtDuration(h.claimed_at, h.released_at)}</div>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </section>

            <!-- Timeline -->
            {@const transitions = detail.transitions ?? []}
            <section class="dsection">
                <h3 class="dsection-head">
                    Timeline
                    <span class="aside">{transitions.length} events</span>
                </h3>
                <ExpandedTimeline {transitions} newestFirst />
            </section>

            <!-- Validation (lazy) -->
            <section class="dsection">
                <button
                    class="collapsible-head"
                    type="button"
                    aria-expanded={valExpanded}
                    onclick={toggleValidation}
                >
                    <span class="chev" class:open={valExpanded}>▸</span>
                    <span class="dsection-head no-margin">Validation counts</span>
                    {#if validation?.has_data === false}
                        <span class="aside">no data</span>
                    {:else if validation}
                        {@const total = Object.values(validation.category_counts ?? {}).reduce(
                            (a, b) => a + b,
                            0,
                        )}
                        <span class="aside">{total} total</span>
                    {:else}
                        <span class="aside">click to load</span>
                    {/if}
                </button>
                {#if valExpanded}
                    <div class="val-body">
                        {#if valLoading}
                            <div class="state small">Computing…</div>
                        {:else if valError}
                            <div class="state error small" role="alert">{valError}</div>
                        {:else if validation && !validation.has_data}
                            <div class="empty-block">No detailed.json on the bucket yet.</div>
                        {:else if validation}
                            <ul class="cat-list">
                                {#each categoryRows as row (row.kind)}
                                    <li class="cat-row" class:zero={row.count === 0}>
                                        <span class="cat-title">{row.title}</span>
                                        <span class="cat-count">{row.count}</span>
                                    </li>
                                {/each}
                            </ul>
                        {/if}
                    </div>
                {/if}
            </section>

            <!-- Jobs -->
            {@const jobIds = detail.timestamps_job_ids ?? []}
            <section class="dsection">
                <h3 class="dsection-head">
                    Jobs
                    <span class="aside">{jobIds.length} timestamps</span>
                </h3>
                {#if jobIds.length === 0}
                    <div class="empty-block">No jobs run for this recitation yet.</div>
                {:else}
                    <ul class="job-list">
                        {#each jobIds as jid (jid)}
                            <li class="job-row">
                                <span class="job-name">timestamps-refresh</span>
                                <span class="job-id">{jid}</span>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </section>
        {/if}
    </div>
</aside>

<style>
    .drawer {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        width: 62%;
        max-width: 720px;
        min-width: 440px;
        background: var(--panel);
        border-left: 1px solid var(--border-quiet);
        z-index: 5;
        display: flex;
        flex-direction: column;
        overflow: hidden;
    }
    .drawer-head {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        padding: var(--s-4) var(--s-5);
        border-bottom: 1px solid var(--border-quiet);
        gap: var(--s-3);
    }
    .drawer-context { min-width: 0; flex: 1; }
    .drawer-title {
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin-bottom: var(--s-2);
    }
    .recitation-ar {
        font-size: 17px;
        color: var(--text-primary);
        unicode-bidi: isolate;
        line-height: 1.25;
    }
    .recitation-lt {
        font-size: 11px;
        color: var(--text-muted);
        margin-top: 2px;
    }
    .recitation-meta {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        margin-top: 4px;
        letter-spacing: 0.02em;
    }
    .drawer-close {
        background: transparent;
        border: 0;
        color: var(--text-faint);
        cursor: pointer;
        font-size: 18px;
        line-height: 1;
        padding: 0 var(--s-2);
    }
    .drawer-close:hover { color: var(--text-primary); }

    .drawer-body {
        flex: 1;
        min-height: 0;
        overflow: auto;
        padding: var(--s-5);
    }

    .state {
        padding: var(--s-8) 0;
        text-align: center;
        color: var(--text-muted);
        font-size: var(--fs-meta);
    }
    .state.small { padding: var(--s-3) 0; text-align: left; }
    .state.error { color: var(--state-error-fg); }

    .dsection { margin-bottom: var(--s-6); }
    .dsection:last-child { margin-bottom: 0; }
    .dsection-head {
        font-size: 10.5px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 0 0 var(--s-3);
        display: flex;
        align-items: center;
        gap: var(--s-2);
        justify-content: space-between;
        font-weight: 500;
    }
    .dsection-head.no-margin { margin: 0; }
    .dsection-head .aside {
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: 10.5px;
        letter-spacing: 0.02em;
        text-transform: none;
    }

    /* current claim — owner-clickable trigger or maintainer-static display.
     * .claim-wrap holds the relative-positioning anchor for the absolute
     * popover; mirrors RolePicker's .rp-wrap pattern. */
    .claim-wrap {
        position: relative;
        display: block;
    }
    .current-claim {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        width: 100%;
        padding: var(--s-3);
        background: var(--panel-2);
        border: 1px solid transparent;
        border-radius: var(--r-2);
        text-align: left;
        font: inherit;
        color: inherit;
    }
    /* Only owners get the clickable affordance — subtle hover ring matches
     * RolePicker's .rp-trigger:hover treatment so the click target reads
     * the same as the role pill on other surfaces. */
    .current-claim.clickable {
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .current-claim.clickable:hover,
    .current-claim.clickable.open {
        border-color: var(--accent-tint);
        background: var(--panel);
    }
    .current-claim .meta { flex: 1; min-width: 0; }
    .current-claim .who {
        font-size: var(--fs-body);
        color: var(--text-primary);
    }
    .current-claim .since {
        font-size: 11px;
        color: var(--text-muted);
        margin-top: 2px;
    }
    .current-claim .caret {
        font-size: 10px;
        color: var(--text-faint);
        line-height: 1;
        flex-shrink: 0;
    }
    .current-claim.clickable:hover .caret { color: var(--text-muted); }

    .avatar {
        width: 28px; height: 28px;
        border-radius: 50%;
        background: var(--accent-tint);
        color: var(--accent-strong);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 600;
        flex: 0 0 auto;
    }
    .avatar.small { width: 22px; height: 22px; font-size: 10px; background: var(--panel-2); color: var(--text-muted); }

    /* reviewer history */
    .history-list { list-style: none; padding: 0; margin: 0; }
    .history-row {
        display: grid;
        grid-template-columns: 28px 1fr auto;
        gap: var(--s-3);
        padding: var(--s-2) 0;
        border-bottom: 1px dashed var(--border-quiet);
        align-items: center;
    }
    .history-row:last-child { border-bottom: 0; }
    .history-row .meta { min-width: 0; }
    .history-row .who { color: var(--text-secondary); font-size: var(--fs-body); }
    .history-row .dates {
        color: var(--text-muted);
        font-family: var(--font-mono);
        font-size: 10.5px;
        margin-top: 2px;
    }
    .history-row .close-reason {
        color: var(--text-faint);
        font-style: italic;
        margin-left: 6px;
    }
    .history-row .duration {
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
    }

    /* validation */
    .collapsible-head {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        background: transparent;
        border: 0;
        padding: var(--s-1) 0 var(--s-3);
        cursor: pointer;
        font: inherit;
        text-align: left;
        color: var(--text-primary);
    }
    .collapsible-head:hover { color: var(--text-secondary); }
    .chev {
        color: var(--text-faint);
        font-family: var(--font-mono);
        font-size: 10px;
        display: inline-block;
        transition: transform var(--t-fast) var(--ease-out-quart);
    }
    .chev.open { transform: rotate(90deg); }
    .val-body { margin-top: var(--s-2); }
    .cat-list { list-style: none; padding: 0; margin: 0; }
    .cat-row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        padding: 4px 0;
        border-bottom: 1px solid var(--border-quiet);
        font-size: var(--fs-body);
    }
    .cat-row:last-child { border-bottom: 0; }
    .cat-row.zero { color: var(--text-faint); }
    .cat-title { color: var(--text-secondary); }
    .cat-row.zero .cat-title { color: var(--text-faint); }
    .cat-count {
        font-family: var(--font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        color: var(--text-primary);
    }
    .cat-row.zero .cat-count { color: var(--text-faint); }

    /* jobs */
    .job-list { list-style: none; padding: 0; margin: 0; }
    .job-row {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        padding: 4px 0;
        border-bottom: 1px solid var(--border-quiet);
    }
    .job-row:last-child { border-bottom: 0; }
    .job-name {
        font-size: var(--fs-body);
        color: var(--text-secondary);
    }
    .job-id {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        word-break: break-all;
    }

    .empty-block {
        font-size: var(--fs-meta);
        color: var(--text-faint);
        padding: var(--s-2) 0;
    }

    /* ---------- Mark-ready submission ---------- */
    .mr-submission {
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
    }
    .mr-submission.mr-bypass {
        border-color: oklch(from var(--state-warn-fg) l c h / 0.4);
        background: oklch(from var(--state-warn-fg) l c h / 0.05);
    }
    .mr-bypass-pill {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        margin-left: var(--s-2);
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--state-warn-fg);
        background: oklch(from var(--state-warn-fg) l c h / 0.12);
        border: 1px solid oklch(from var(--state-warn-fg) l c h / 0.4);
        border-radius: var(--r-pill);
    }
    .mr-bypass-line {
        margin: 0 0 var(--s-3);
        font-size: var(--fs-meta);
        font-style: italic;
        color: var(--text-secondary);
        line-height: var(--lh-normal);
    }
    .mr-checklist {
        list-style: none;
        margin: 0 0 var(--s-3);
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .mr-check-row {
        display: flex;
        align-items: flex-start;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        line-height: var(--lh-normal);
    }
    .mr-check-row.done .mr-check-label {
        color: var(--text-primary);
    }
    .mr-check-glyph {
        flex: 0 0 14px;
        font-family: var(--font-mono);
        font-size: 12px;
        color: var(--text-faint);
        text-align: center;
        line-height: 1.5;
    }
    .mr-check-row.done .mr-check-glyph {
        color: var(--accent);
        font-weight: 600;
    }
    .mr-comment {
        margin-top: var(--s-3);
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .mr-comment-label {
        font-size: 10.5px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .mr-comment-body {
        margin: 0;
        padding: var(--s-2) var(--s-3);
        background: var(--panel);
        border-left: 2px solid var(--border-default);
        border-radius: var(--r-1);
        font-size: var(--fs-meta);
        color: var(--text-primary);
        line-height: var(--lh-normal);
        white-space: pre-wrap;
        word-break: break-word;
    }
</style>
