<script lang="ts">
    /**
     * One recitation row in the Reviews tab landing list.
     *
     * Single-line dense layout: Arabic name dominant + Latin trailing inline,
     * taxonomy chips (Riwayah · Style · Channel), reviewer (or em-dash on
     * Published rows whose claim closed), age in mono, two action buttons
     * [Segments] [Ops].
     *
     * - Row body click → General drawer (M2, wired below)
     * - Segments button → close modal + open the Segments tab with this slug
     *   pre-selected (uses the existing dashboardState.openDetail helper)
     * - Ops button → Ops drawer (M3, still a stub)
     */
    import { reviewsStore } from '../../../../../lib/stores/reviews.svelte';
    import { adminDashboard } from '../../../stores/admin-dashboard.svelte';
    import { openDetail as openSegmentsDetail } from '../../../stores/dashboard-state';
    import type { AdminReviewRow } from '../../../../../lib/types/generated/schemas';

    let { row }: { row: AdminReviewRow } = $props();

    const isActive = $derived(reviewsStore.selectedSlug === row.slug);

    function initials(login: string | null | undefined): string {
        if (!login) return '?';
        const trimmed = login.trim();
        if (!trimmed) return '?';
        // first two alphanumerics, uppercased
        const chars = trimmed.replace(/[^a-z0-9]/gi, '').slice(0, 2).toUpperCase();
        return chars || trimmed.slice(0, 2).toUpperCase();
    }

    // Relative age from an ISO timestamp. Coarse-grained — minute precision
    // would be noise at this density.
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

    // Time-in-state from open_claim.claimed_at if there's an open claim,
    // else from state_since (Published rows whose claim closed land here).
    const ageISO = $derived(row.open_claim?.claimed_at ?? row.state_since ?? null);
    const age = $derived(relativeAge(ageISO));

    const reviewerLogin = $derived(row.open_claim?.login ?? null);
    const hasReviewer = $derived(reviewerLogin !== null);

    function onRowClick(): void {
        reviewsStore.open(row.slug, 'general');
    }

    function onOps(e: MouseEvent): void {
        e.stopPropagation();
        // M3: reviewsStore.open(row.slug, 'ops')
    }

    function onSegments(e: MouseEvent): void {
        e.stopPropagation();
        // Take the user to the Segments tab with this recitation pre-selected,
        // then dismiss the admin modal so the deep-link lands cleanly.
        openSegmentsDetail(row.reciter_id, row.slug);
        adminDashboard.close();
    }
</script>

<div
    class="row"
    class:active={isActive}
    role="button"
    tabindex="0"
    onclick={onRowClick}
    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRowClick(); } }}
>
    <div class="reciter">
        {#if row.name_ar}
            <span class="reciter-ar" dir="rtl">{row.name_ar}</span>
        {/if}
        {#if row.name_en}
            <span class="reciter-lt">{row.name_en}</span>
        {/if}
    </div>

    <ul class="taxonomy">
        <li class="chip">{row.riwayah}</li>
        <li class="chip">{row.style}</li>
        <li class="chip channel">{row.channel}</li>
    </ul>

    <div class="reviewer" class:unassigned={!hasReviewer}>
        <span class="avatar">{hasReviewer ? initials(reviewerLogin) : ''}</span>
        <span class="who">{hasReviewer ? reviewerLogin : '—'}</span>
    </div>

    <div class="age">{age}</div>

    <div class="row-actions">
        <button class="btn" type="button" onclick={onSegments}>Segments</button>
        <button class="btn" type="button" onclick={onOps}>Ops</button>
    </div>
</div>

<style>
    .row {
        display: grid;
        grid-template-columns: minmax(240px, 1fr) auto auto auto auto;
        gap: var(--s-4);
        align-items: center;
        padding: var(--s-2) var(--s-1);
        border-bottom: 1px solid var(--border-quiet);
        cursor: pointer;
        transition: background-color var(--t-fast);
    }
    .row:hover { background: var(--panel); }
    .row:focus-visible {
        outline: 0;
        background: var(--panel);
        box-shadow: inset 0 0 0 1px var(--accent-tint);
        border-radius: var(--r-1);
    }
    .row.active {
        background: var(--panel);
        box-shadow: inset 0 0 0 1px var(--accent-tint);
        border-radius: var(--r-1);
    }

    .reciter {
        min-width: 0;
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        flex-wrap: nowrap;
        overflow: hidden;
    }
    .reciter-ar {
        font-size: 17px;
        color: var(--text-primary);
        line-height: 1.25;
        unicode-bidi: isolate;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }
    .reciter-lt {
        font-size: 11px;
        color: var(--text-faint);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 0 1 auto;
    }

    .taxonomy {
        list-style: none;
        display: flex;
        gap: var(--s-1);
        flex-wrap: nowrap;
        padding: 0;
        margin: 0;
    }
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
    }
    .chip.channel {
        background: transparent;
        border-color: var(--border-quiet);
        color: var(--text-muted);
    }

    .reviewer {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 130px;
        font-size: var(--fs-body);
        color: var(--text-secondary);
    }
    .reviewer .avatar {
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--accent-tint);
        color: var(--accent-strong);
        font-size: 9.5px;
        font-weight: 600;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        letter-spacing: 0;
        flex: 0 0 auto;
    }
    .reviewer.unassigned { color: var(--text-faint); }
    .reviewer.unassigned .avatar {
        background: transparent;
        border: 1px dashed var(--border-default);
    }

    .age {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
        min-width: 52px;
        text-align: right;
    }

    .row-actions {
        display: flex;
        gap: var(--s-1);
    }
    .row-actions .btn {
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
    .row-actions .btn:hover {
        border-color: var(--border-default);
        color: var(--text-primary);
    }
</style>
