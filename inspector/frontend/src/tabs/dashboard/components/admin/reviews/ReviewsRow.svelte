<script lang="ts">
    /**
     * One recitation row in the Reviews tab landing list.
     *
     * Two-zone flex row (mirrors the Requests-tab ``.req-head``): a growing
     * identity block on the left, an intrinsic-width meta cluster on the
     * right, vertically centered against the two identity lines.
     *   Line 1 — unread dot + Latin name (primary, first) + Arabic name
     *            (muted, trailing) + reviewer (initials avatar + login).
     *   Line 2 — riwayah · style · channel as muted dotted text.
     *   Right  — age (relative, mono; stale ⚠ when a claim is > 7d old) +
     *            actions (Segments, plus Generate TS on marked-ready rows).
     *
     * Row body click → General drawer. Segments button switches to the
     * top-level Segments tab with this slug pre-selected. Generate TS
     * launches the MFA timestamps job — shown only on marked-ready rows
     * because generating timestamps publishes the reciter on success.
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
    // Generate TS publishes on success, so it's offered only once the reviewer
    // has marked the reciter ready — not on every under_review row.
    const isMarkedReady = $derived(
        row.state === 'under_review' && !!row.open_claim?.marked_ready_at,
    );
    const isTsActive = $derived(isActive && reviewsStore.openDrawer === 'timestamps');

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
    function openDrawer(kind: 'general'): void {
        const wasUnread = showUnread;
        reviewsStore.open(row.slug, kind);
        if (wasUnread) {
            adminDashboard.setUnviewedReviews(adminDashboard.unviewedReviews - 1);
        }
    }

    function onRowClick(): void {
        openDrawer('general');
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

    function onGenerateTimestamps(e: MouseEvent): void {
        e.stopPropagation();
        reviewsStore.open(row.slug, 'timestamps');
    }
</script>

<div
    class="row"
    class:active={isActive}
    role="button"
    tabindex="0"
    onclick={onRowClick}
    onkeydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onRowClick();
        }
    }}
>
    <div class="identity">
        <div class="id-name">
            {#if showUnread}
                <span class="unread" aria-label="needs attention" title="New since you last viewed — marked ready or a finished timestamps job"></span>
            {/if}
            {#if row.name_en}
                <span class="name-en">{row.name_en}</span>
            {/if}
            {#if row.name_ar}
                <span class="name-ar" dir="rtl">{row.name_ar}</span>
            {/if}
            {#if hasReviewer}
                <span class="reviewer">
                    <span class="avatar">{initials(reviewerLogin)}</span>
                    <span class="who">{reviewerLogin}</span>
                </span>
            {/if}
        </div>
        <div class="id-meta">
            <span class="combo">{row.riwayah}</span>
            <span class="sep">·</span>
            <span class="combo">{row.style}</span>
            <span class="sep">·</span>
            <span class="combo channel">{row.channel}</span>
        </div>
    </div>
    <div class="row-meta">
        <span class="age" class:stale={isStale}>
            {#if isStale}
                <span
                    class="stale-warn"
                    aria-label="Claim open more than 7 days"
                    title="Claim open more than 7 days — consider reassigning or releasing"
                >⚠</span>
            {/if}
            {age}
        </span>
        <div class="actions">
            <button class="btn" type="button" onclick={onSegments}>Segments</button>
            {#if isMarkedReady}
                <button
                    class="btn"
                    class:armed={isTsActive}
                    type="button"
                    onclick={onGenerateTimestamps}
                    title="Generate timestamps & publish — settings, logs & history"
                >Generate TS</button>
            {/if}
        </div>
    </div>
</div>

<style>
    /* Two-zone flex row (mirrors the Requests-tab .req-head): identity grows,
     * meta cluster keeps its intrinsic width on the right. align-items:center
     * vertically centers the right cluster against the two identity lines. */
    .row {
        display: flex;
        align-items: center;
        gap: var(--s-5);
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        cursor: pointer;
        transition: background-color var(--t-fast);
    }
    .row:last-child { border-bottom: 0; }
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

    .identity {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    /* Line 1 — Latin primary first, Arabic trailing muted, reviewer last. */
    .id-name {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        min-width: 0;
    }
    /* Unread mark — mirrors the Requests-tab .unread dot. Centered against
     * the text baseline (baseline alignment would push it under the text). */
    .unread {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
        flex-shrink: 0;
        align-self: center;
    }
    .name-en {
        font-size: 14px;
        color: var(--text-primary);
        line-height: 1.3;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }
    .name-ar {
        font-size: 13px;
        color: var(--text-muted);
        unicode-bidi: isolate;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }
    /* Reviewer rides the identity line as a small avatar + login. Omitted
     * entirely when unclaimed (Available / Published rows) — no placeholder. */
    .reviewer {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
        align-self: center;
        white-space: nowrap;
    }
    .reviewer .avatar {
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
    }
    .reviewer .who {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }

    /* Line 2 — riwayah · style · channel as muted dotted text. */
    .id-meta {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        min-width: 0;
    }
    .id-meta .combo {
        color: var(--text-secondary);
        white-space: nowrap;
    }
    .id-meta .combo.channel { color: var(--text-muted); }
    .id-meta .sep { color: var(--text-faint); }

    /* Right cluster — age + actions, free to clip at the right edge. */
    .row-meta {
        flex-shrink: 0;
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        white-space: nowrap;
    }

    .age {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    /* Stale-reviewer nudge: any under_review row whose claim opened > 7d ago
     * surfaces a warning glyph beside the age, and the age text shifts to the
     * warning tone so the row scans as "needs attention" at a glance. */
    .age.stale { color: var(--state-error-fg); }
    .stale-warn {
        display: inline-block;
        margin-right: 4px;
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--state-error-fg);
        cursor: help;
    }

    .actions {
        display: inline-flex;
        align-items: center;
        gap: var(--s-1);
    }
    .actions .btn {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 4px 12px;
        border-radius: var(--r-1);
        cursor: pointer;
        white-space: nowrap;
        transition: border-color var(--t-fast), color var(--t-fast), background-color var(--t-fast);
    }
    .actions .btn:hover {
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .actions .btn.armed {
        border-color: var(--accent);
        color: var(--accent-strong);
        background: var(--accent-tint-soft);
    }
</style>
