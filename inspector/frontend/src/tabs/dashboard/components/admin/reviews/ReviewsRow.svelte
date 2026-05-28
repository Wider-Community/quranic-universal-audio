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
    import { adminDashboard } from '../../../stores/admin-dashboard.svelte';
    import { LS_KEYS, TAB_NAMES } from '../../../../../lib/utils/constants';
    import { setActiveTab } from '../../../../../lib/utils/active-tab';
    import { selectedReciter } from '../../../../segments/stores/chapter';
    import type { AdminReviewRow } from '../../../../../lib/types/generated/schemas';

    let { row }: { row: AdminReviewRow } = $props();

    const isActive = $derived(reviewsStore.selectedSlug === row.slug);
    const isOpsActive = $derived(isActive && reviewsStore.openDrawer === 'ops');

    function initials(login: string | null | undefined): string {
        if (!login) return '?';
        const trimmed = login.trim();
        if (!trimmed) return '?';
        const chars = trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase();
        return chars || trimmed.slice(0, 2).toUpperCase();
    }

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

    const reviewerLogin = $derived(row.open_claim?.login ?? null);
    const hasReviewer = $derived(reviewerLogin !== null);

    function onRowClick(): void {
        reviewsStore.open(row.slug, 'general');
    }

    function onOps(e: MouseEvent): void {
        e.stopPropagation();
        reviewsStore.open(row.slug, 'ops');
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
        {#if row.name_en}
            <span class="reciter-lt">{row.name_en}</span>
        {/if}
        {#if row.name_ar}
            <span class="reciter-ar" dir="rtl">{row.name_ar}</span>
        {/if}
    </td>
    <td class="cell taxonomy"><span class="chip">{row.riwayah}</span></td>
    <td class="cell taxonomy"><span class="chip">{row.style}</span></td>
    <td class="cell taxonomy"><span class="chip channel">{row.channel}</span></td>
    <td class="cell reviewer" class:unassigned={!hasReviewer}>
        <span class="avatar">{hasReviewer ? initials(reviewerLogin) : ''}</span>
        <span class="who">{hasReviewer ? reviewerLogin : '—'}</span>
    </td>
    <td class="cell age">{age}</td>
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

    /* reciter — Latin primary first, Arabic trailing muted */
    .cell.reciter {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        min-width: 0;
        overflow: hidden;
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
