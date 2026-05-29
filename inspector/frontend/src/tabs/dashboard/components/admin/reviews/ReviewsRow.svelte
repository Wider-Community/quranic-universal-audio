<script lang="ts">
    /**
     * One recitation row in the Reviews tab landing list (table-format).
     *
     * Emits a ``<tr>`` so all rows across all state sections share the same
     * column widths (defined in ReviewsCompartment.svelte with
     * ``table-layout: fixed`` + ``<colgroup>``). Cells, in order:
     *   1. Reciter — Latin name dominant (primary, 15px) + Arabic trailing
     *      inline (muted, 13px). Per user feedback: English not smaller, first.
     *   2. Riwayah · 3. Style · 4. Channel — taxonomy chips
     *   5. Reviewer — initials avatar + login (or em dash when unclaimed)
     *   6. Age — relative time in mono
     *   7. Actions — Segments + Ops buttons
     *
     * Row body click → General drawer. Segments button switches to the
     * top-level Segments tab with this slug pre-selected. Ops opens the
     * Ops drawer.
     */
    import { reviewsStore } from '../../../../../lib/stores/reviews.svelte';
    import type { AdminReviewRow } from '../../../../../lib/types/generated/schemas';
    import { setActiveTab } from '../../../../../lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from '../../../../../lib/utils/constants';
    import { initials } from '../../../../../lib/utils/initials';
    import { selectedReciter } from '../../../../segments/stores/chapter';
    import { adminDashboard } from '../../../stores/admin-dashboard.svelte';

    let { row }: { row: AdminReviewRow } = $props();

    const isActive = $derived(reviewsStore.selectedSlug === row.slug);
    const isOpsActive = $derived(isActive && reviewsStore.openDrawer === 'ops');

    function relativeAge(iso: string | null | undefined): string {
        if (!iso) return '';
        const then = Date.parse(iso);
        if (Number.isNaN(then)) return '';
        const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
        if (secs < 60) return `${secs}s`;
        const mins = Math.floor(secs / 60);
        if (mins < 60) return `${mins}m`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h`;
        const days = Math.floor(hrs / 24);
        if (days < 14) return `${days}d`;
        const weeks = Math.floor(days / 7);
        if (weeks < 8) return `${weeks}w`;
        const months = Math.floor(days / 30);
        if (months < 24) return `${months}mo`;
        const years = Math.floor(days / 365);
        return `${years}y`;
    }

    const ageISO = $derived(row.open_claim?.claimed_at ?? row.state_since ?? null);
    const age = $derived(relativeAge(ageISO));

    // Stale-reviewer signal: any row with an active claim (under_review,
    // including marked-ready) whose claim opened more than 7 days ago. The
    // age cell on Available / Published rows tracks ``state_since`` which is
    // a different concept — we only want this nudge when someone is actively
    // sitting on a slug. Computed from the same ISO the relative label uses
    // so they can't disagree.
    const STALE_THRESHOLD_SECS = 7 * 24 * 60 * 60;
    function secondsAgo(iso: string | null | undefined): number {
        if (!iso) return 0;
        const then = Date.parse(iso);
        if (Number.isNaN(then)) return 0;
        return Math.max(0, Math.floor((Date.now() - then) / 1000));
    }
    const isStale = $derived(
        row.state === 'under_review'
            && !!row.open_claim?.claimed_at
            && secondsAgo(row.open_claim.claimed_at) > STALE_THRESHOLD_SECS,
    );

    const reviewerLogin = $derived(row.open_claim?.login ?? null);
    const hasReviewer = $derived(reviewerLogin !== null);

    // Marked-ready unread dot — server-authoritative ``row.unread``, AND
    // suppressed locally the moment any drawer for this slug opens (the
    // session-set drop hides the dot before the optimistic POST returns).
    const showUnread = $derived(
        !!row.unread && !reviewsStore.isViewedThisSession(row.slug),
    );

    /** Open a drawer and, on the first open for this slug, optimistically
     * decrement the dashboard counter so the entry-button dot / tab pill
     * also drop in sync. The compartment's next fetch reconciles. */
    function openDrawer(kind: 'general' | 'ops'): void {
        const wasUnread = showUnread;
        reviewsStore.open(row.slug, kind);
        if (wasUnread) {
            adminDashboard.setUnviewedReviews(adminDashboard.unviewedReviews - 1);
        }
    }

    function onRowClick(): void {
        openDrawer('general');
    }

    function onOps(e: MouseEvent): void {
        e.stopPropagation();
        openDrawer('ops');
    }

    function onSegments(e: MouseEvent): void {
        e.stopPropagation();
        try {
            localStorage.setItem(LS_KEYS.SEG_RECITER, row.slug);
        } catch {
            /* localStorage unavailable — store-set still works for this session */
        }
        selectedReciter.set(row.slug);
        setActiveTab(TAB_NAMES.SEGMENTS);
        adminDashboard.close();
    }
</script>

<tr
    class="row"
    class:active={isActive}
    tabindex="0"
    onclick={onRowClick}
    onkeydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onRowClick();
        }
    }}
>
    <td class="cell reciter">
        <div class="reciter-inner">
            {#if showUnread}
                <span class="unread" aria-label="new marked-ready" title="New marked ready"></span>
            {/if}
            {#if row.name_en}
                <span class="reciter-lt">{row.name_en}</span>
            {/if}
            {#if row.name_ar}
                <span class="reciter-ar" dir="rtl">{row.name_ar}</span>
            {/if}
        </div>
    </td>
    <td class="cell taxonomy"><span class="chip">{row.riwayah}</span></td>
    <td class="cell taxonomy"><span class="chip">{row.style}</span></td>
    <td class="cell taxonomy"><span class="chip channel">{row.channel}</span></td>
    <td class="cell reviewer" class:unassigned={!hasReviewer}>
        <span class="avatar">{hasReviewer ? initials(reviewerLogin) : ''}</span>
        <span class="who">{hasReviewer ? reviewerLogin : '—'}</span>
    </td>
    <td class="cell age" class:stale={isStale}>
        {#if isStale}
            <span
                class="stale-warn"
                aria-label="Claim open more than 7 days"
                title="Claim open more than 7 days — consider reassigning or releasing"
            >⚠</span>
        {/if}
        {age}
    </td>
    <td class="cell actions">
        <button class="btn" type="button" onclick={onSegments}>Segments</button>
        <button
            class="btn"
            class:armed={isOpsActive}
            type="button"
            onclick={onOps}
        >Ops</button>
    </td>
</tr>

<style>
    .row {
        cursor: pointer;
        transition: background-color var(--t-fast);
    }
    .row:hover { background: var(--panel); }
    .row:focus-visible {
        outline: 0;
        background: var(--panel);
        box-shadow: inset 0 0 0 1px var(--accent-tint);
    }
    .row.active {
        background: var(--panel);
        box-shadow: inset 0 0 0 1px var(--accent-tint);
    }

    .cell {
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        vertical-align: middle;
    }
    .row:last-child .cell { border-bottom: 0; }

    /* reciter — Latin primary first, Arabic trailing muted. The cell itself
     * stays a `table-cell` so the colgroup width applies; flex lives on the
     * inner wrapper. (Setting `display: flex` on a <td> opts it out of the
     * table layout entirely and collapses the fixed column widths.) */
    .cell.reciter { overflow: hidden; }
    .reciter-inner {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        min-width: 0;
        overflow: hidden;
    }
    /* Unread mark — mirrors the Requests-tab .unread dot for visual parity.
     * Centered against the row baseline (baseline alignment on the flex
     * parent would push it under the text), so override to center. */
    .reciter-inner .unread {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
        flex-shrink: 0;
        align-self: center;
    }
    .reciter-lt {
        font-size: 14px;
        color: var(--text-primary);
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }
    .reciter-ar {
        font-size: 13px;
        color: var(--text-muted);
        unicode-bidi: isolate;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }

    .cell.taxonomy { color: var(--text-secondary); }
    .chip {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: var(--r-1);
        background: var(--panel-2);
        color: var(--text-secondary);
        font-size: 10.5px;
        font-family: var(--font-mono);
        letter-spacing: 0.02em;
        font-variant-numeric: tabular-nums;
        border: 1px solid transparent;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
    }
    .chip.channel {
        background: transparent;
        border-color: var(--border-quiet);
        color: var(--text-muted);
    }

    .cell.reviewer {
        font-size: var(--fs-body);
        color: var(--text-secondary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .cell.reviewer .avatar {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--accent-tint);
        color: var(--accent-strong);
        font-size: 9.5px;
        font-weight: 600;
        vertical-align: -5px;
        margin-right: 6px;
    }
    .cell.reviewer.unassigned { color: var(--text-faint); }
    .cell.reviewer.unassigned .avatar {
        background: transparent;
        border: 1px dashed var(--border-default);
    }

    .cell.age {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
        text-align: right;
        white-space: nowrap;
    }
    /* Stale-reviewer nudge: any under_review row whose claim opened > 7d ago
     * surfaces a warning glyph beside the age. The age text itself shifts to
     * the warning tone so the row scans as "this needs attention" at a
     * glance, without the visual weight of a dedicated cell. */
    .cell.age.stale { color: var(--state-error-fg); }
    .stale-warn {
        display: inline-block;
        margin-right: 4px;
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--state-error-fg);
        cursor: help;
    }

    .cell.actions { white-space: nowrap; }
    .cell.actions .btn {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 3px 10px;
        border-radius: var(--r-1);
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background-color var(--t-fast);
    }
    .cell.actions .btn + .btn { margin-left: var(--s-1); }
    .cell.actions .btn:hover {
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .cell.actions .btn.armed {
        border-color: var(--accent);
        color: var(--accent-strong);
        background: var(--accent-tint-soft);
    }
</style>
