<script lang="ts">
    /**
     * One recitation row in the Releases tab.
     *
     * Layout: select checkbox + identity (left) · TS/HF/GH chips + readiness
     * pill + action cluster (right). Below the row, a single in-row expansion
     * (button-switched, one open per row — the compartment enforces one open
     * across the whole list).
     *
     * Action cluster, by bucket:
     *   - in_flight        → running badge + elapsed + Open-on-HF + Cancel
     *   - ready_to_generate→ reviewer chip + Generate (ts expand) + Send back
     *   - all others       → Generate/Regenerate (ts expand)
     *   - every bucket     → Timeline · Reviewers · Jobs · Segments (redirect)
     *
     * Publishing is select-only (checkbox + the compartment's batch action bar).
     * Gen/Regen TS is near-global — it opens the inline ``ReleasesTsSettings``
     * expand; the cap pair (reviews.generate_timestamps + reciter.publish) gates
     * it per the registry, NOT a hardcoded role.
     */
    import { can } from '../../../../../lib/stores/capabilities';
    import type {
        InFlightJob,
        ReleaseStatusRow,
    } from '../../../../../lib/api/admin-releases';
    import { setActiveTab } from '../../../../../lib/utils/active-tab';
    import { LS_KEYS, TAB_NAMES } from '../../../../../lib/utils/constants';
    import { initials } from '../../../../../lib/utils/initials';
    import { selectedReciter } from '../../../../segments/stores/chapter';
    import { adminDashboard } from '../../../stores/admin-dashboard.svelte';
    import ReleasesRowExpansion, { type RowExpandMode } from './ReleasesRowExpansion.svelte';

    export type ReleasesBucket =
        | 'in_flight'
        | 'failed'
        | 'ready_to_generate'
        | 'behind_edits'
        | 'republish_hf'
        | 'publish_hf'
        | 'published_current';

    interface Props {
        row: ReleaseStatusRow;
        bucket: ReleasesBucket;
        inFlightJob?: InFlightJob | null;
        selectable?: boolean;
        selected?: boolean;
        /** The expansion mode open for THIS row, or null when closed. */
        expandedMode?: RowExpandMode | null;
        /** Job id to poll live in the jobs view (set after a launch on this row). */
        activeJobId?: string | null;
        canceling?: boolean;
        sendBackBusy?: boolean;
        errorMessage?: string | null;
        onToggleSelect?: (_slug: string) => void;
        /** Toggle the in-row expansion to ``mode`` (or close if already open). */
        onToggleMode?: (_slug: string, _mode: RowExpandMode) => void;
        /** A gen/regen job launched from this row's TS expand. */
        onLaunched?: (_slug: string, _jobId: string) => void;
        onCancel?: (_jobId: string) => void;
        onSendBack?: (_slug: string) => void;
    }
    let { row, bucket, inFlightJob = null, selectable = false, selected = false,
          expandedMode = null, activeJobId = null, canceling = false,
          sendBackBusy = false, errorMessage = null,
          onToggleSelect, onToggleMode, onLaunched, onCancel, onSendBack }: Props = $props();

    const canGenerateTs = can('reviews.generate_timestamps');
    const canReciterPublish = can('reciter.publish');
    // Gen/Regen is available on every bucket except in_flight (the job is running).
    const showTs = $derived(bucket !== 'in_flight');
    const tsLabel = $derived(row.ts === null ? 'Generate' : 'Regenerate');

    const audioMissing = $derived(row.readiness?.audio_missing ?? 0);
    const peaksMissing = $derived(row.readiness?.peaks_missing ?? 0);
    const audioMissingChapters = $derived(row.readiness?.audio_missing_chapters ?? []);
    const peaksMissingChapters = $derived(row.readiness?.peaks_missing_chapters ?? []);
    const hasMissing = $derived(audioMissing > 0 || peaksMissing > 0);
    const flaggedCount = $derived(row.flagged_issues_count ?? 0);

    function fmtRelative(iso: string | null | undefined): string {
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
        return `${Math.floor(days / 365)}y`;
    }

    function shortVer(v: string | null | undefined): string {
        if (!v) return '';
        const s = String(v);
        return s.length > 8 ? s.slice(0, 7) : s;
    }

    function staleReasonLabel(reason: string | null | undefined): string {
        if (reason === 'catalog_edit') return 'metadata';
        if (reason === 'ts_regen') return 'timestamps';
        if (reason === 'segments_edited') return 'edited';
        return 'stale';
    }

    function tsChipTitle(): string {
        if (!row.ts) return 'No timestamps yet';
        let t = `TS ${row.ts.version} · ${fmtRelative(row.ts.produced_at)}`;
        if (row.ts.stale_since) {
            const n = row.ts.edits_since ?? 0;
            t += ` · ${n} edit${n === 1 ? '' : 's'} since generation`;
        }
        return t;
    }

    function ghChipLabel(): { glyph: string; label: string; tone: 'pending' | 'settled' | 'warn' | 'faint' } {
        if (!row.gh) return { glyph: '·', label: 'not in cut', tone: 'faint' };
        if (row.gh.stale_since) {
            return { glyph: '⚠', label: `stale · ${staleReasonLabel(row.gh.stale_reason)}`, tone: 'warn' };
        }
        if (row.gh.change_kind === 'unchanged') return { glyph: '·', label: 'current', tone: 'settled' };
        const map: Record<string, string> = { added: '+ added', refresh: '↻ refresh' };
        return { glyph: '', label: map[row.gh.change_kind] ?? row.gh.change_kind, tone: 'pending' };
    }
    const ghChip = $derived(ghChipLabel());

    function readinessTitle(): string {
        const parts: string[] = [];
        if (audioMissing > 0) parts.push(`audio: ${audioMissingChapters.join(', ')}`);
        if (peaksMissing > 0) parts.push(`peaks: ${peaksMissingChapters.join(', ')}`);
        return `Missing in bucket (populated offline) — ${parts.join(' · ')}`;
    }

    function onSegments(): void {
        try {
            localStorage.setItem(LS_KEYS.SEG_RECITER, row.slug);
        } catch {
            /* localStorage unavailable — store-set still works for this session */
        }
        selectedReciter.set(row.slug);
        setActiveTab(TAB_NAMES.SEGMENTS);
        adminDashboard.close();
    }

    const INFO_MODES: { mode: RowExpandMode; label: string }[] = [
        { mode: 'timeline', label: 'Timeline' },
        { mode: 'reviewers', label: 'Review' },
        { mode: 'jobs', label: 'Jobs' },
    ];
</script>

<div class="row-wrap" class:row--selected={selected}>
    <div class="row" class:row--inflight={bucket === 'in_flight'}>
        {#if selectable}
            <label class="select" title="Select for batch publish">
                <input type="checkbox" checked={selected} onchange={() => onToggleSelect?.(row.slug)} />
            </label>
        {:else}
            <span class="select-spacer" aria-hidden="true"></span>
        {/if}

        <div class="identity">
            <div class="id-name">
                {#if row.name_en}<span class="name-en">{row.name_en}</span>{/if}
                {#if row.name_ar}<span class="name-ar" dir="rtl">{row.name_ar}</span>{/if}
                {#if bucket === 'ready_to_generate' && row.reviewer_login}
                    <span class="reviewer">
                        <span class="r-avatar">{initials(row.reviewer_login)}</span>
                        <span class="r-who">{row.reviewer_login}</span>
                    </span>
                {/if}
            </div>
            <div class="id-meta">
                <span class="combo">{row.riwayah}</span><span class="sep">·</span>
                <span class="combo">{row.style}</span><span class="sep">·</span>
                <span class="combo channel">{row.channel}</span>
                {#if hasMissing}
                    <span class="readiness-pill" title={readinessTitle()}>
                        {#if audioMissing > 0}audio {audioMissing}{/if}
                        {#if audioMissing > 0 && peaksMissing > 0} · {/if}
                        {#if peaksMissing > 0}peaks {peaksMissing}{/if}
                        missing
                    </span>
                {/if}
                {#if bucket === 'ready_to_generate' && flaggedCount > 0}
                    <span class="flagged-pill"
                        title={`${flaggedCount} segment${flaggedCount === 1 ? '' : 's'} flagged for a second look in the Segments editor`}>
                        {flaggedCount} flagged
                    </span>
                {/if}
            </div>
        </div>

        <div class="row-meta">
            <span class="chip chip-ts" class:chip-stale={row.ts?.stale_since} title={tsChipTitle()}>
                <span class="chip-key">TS</span>
                {#if row.ts}
                    <span class="chip-val">{fmtRelative(row.ts.produced_at)}</span>
                    {#if row.ts.stale_since}<span class="reason-tag">{staleReasonLabel(row.ts.stale_reason)}</span>{/if}
                {:else}<span class="chip-val chip-faint">—</span>{/if}
            </span>

            <span class="chip chip-hf" class:chip-stale={row.hf?.stale_since}
                title={row.hf ? `HF ${shortVer(row.hf.version)} · ${fmtRelative(row.hf.produced_at)}` : 'Not published'}>
                <span class="chip-key">HF</span>
                {#if row.hf}
                    <span class="chip-val">{fmtRelative(row.hf.produced_at)}</span>
                    {#if row.hf.stale_since}<span class="reason-tag">{staleReasonLabel(row.hf.stale_reason)}</span>{/if}
                {:else}<span class="chip-val chip-faint">—</span>{/if}
            </span>

            <span class="chip chip-gh chip-{ghChip.tone}" title={`GH: ${ghChip.label}`}>
                <span class="chip-key">GH</span>
                <span class="chip-val">{ghChip.glyph}{ghChip.glyph ? ' ' : ''}{ghChip.label}</span>
            </span>

            {#if bucket === 'in_flight'}
                <span class="flight" title={`Job ${inFlightJob?.job_id ?? ''}`}>
                    <span class="badge run"><span class="flight-dot" aria-hidden="true"></span>running</span>
                    {#if inFlightJob?.started_at}<span class="flight-when">{fmtRelative(inFlightJob.started_at)}</span>{/if}
                    {#if inFlightJob?.url}
                        <a class="hf-link" href={inFlightJob.url} target="_blank" rel="noopener noreferrer">Open on HF ↗</a>
                    {/if}
                    {#if inFlightJob?.job_id && onCancel}
                        <button class="cancel-job" type="button" disabled={canceling}
                            onclick={() => onCancel?.(inFlightJob.job_id)}>{canceling ? 'Cancelling…' : 'Cancel'}</button>
                    {/if}
                </span>
            {:else}
                <span class="actions">
                    {#if showTs && $canGenerateTs && $canReciterPublish}
                        <button class="btn btn-ts" class:armed={expandedMode === 'ts'} type="button"
                            onclick={() => onToggleMode?.(row.slug, 'ts')}>{tsLabel}</button>
                    {/if}
                    {#if bucket === 'ready_to_generate' && onSendBack}
                        <button class="btn" type="button" disabled={sendBackBusy}
                            onclick={() => onSendBack?.(row.slug)}
                            title="Reject — send back to Under review for more work">
                            {sendBackBusy ? '…' : 'Send back'}
                        </button>
                    {/if}
                    {#each INFO_MODES as m (m.mode)}
                        <button class="btn btn-ghost" class:armed={expandedMode === m.mode} type="button"
                            onclick={() => onToggleMode?.(row.slug, m.mode)}>{m.label}</button>
                    {/each}
                    <button class="btn btn-ghost" type="button" onclick={onSegments}>Segments ↗</button>
                </span>
            {/if}
        </div>
    </div>

    {#if row.publish_error}
        <div class="row-err" role="alert">Last publish failed: {row.publish_error.message}</div>
    {/if}
    {#if errorMessage}<div class="row-err" role="alert">{errorMessage}</div>{/if}

    {#if expandedMode}
        <ReleasesRowExpansion
            {row}
            mode={expandedMode}
            {activeJobId}
            onlaunched={(jobId) => onLaunched?.(row.slug, jobId)}
        />
    {/if}
</div>

<style>
    .row-wrap { border-bottom: 1px solid var(--border-quiet); }
    .row-wrap:last-child { border-bottom: 0; }
    .row-wrap.row--selected { background: var(--accent-tint-soft); }

    .row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        column-gap: var(--s-3);
        padding: var(--s-2) var(--s-3);
        transition: background-color var(--t-fast);
    }
    .row:hover { background: var(--panel); }
    .row--inflight { background: var(--accent-tint-soft); }

    .select, .select-spacer { width: 16px; display: inline-flex; align-items: center; justify-content: center; }
    .select { cursor: pointer; }
    .select input { accent-color: var(--accent); cursor: pointer; margin: 0; }

    .identity { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
    .id-name { display: flex; align-items: baseline; gap: var(--s-2); min-width: 0; }
    .name-en { font-size: 14px; color: var(--text-primary); line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 0 1 auto; }
    .name-ar { font-size: 13px; color: var(--text-muted); unicode-bidi: isolate; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 0 1 auto; }
    .reviewer { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; align-self: center; }
    .r-avatar {
        display: inline-flex; align-items: center; justify-content: center;
        width: 18px; height: 18px; border-radius: 50%;
        background: var(--accent-tint); color: var(--accent-strong); font-size: 9px; font-weight: 600;
    }
    .r-who { font-size: var(--fs-meta); color: var(--text-secondary); }

    .id-meta { display: flex; align-items: baseline; gap: var(--s-2); font-size: var(--fs-meta); min-width: 0; }
    .id-meta .combo { color: var(--text-secondary); white-space: nowrap; }
    .id-meta .combo.channel { color: var(--text-muted); }
    .id-meta .sep { color: var(--text-faint); }
    /* Non-blocking warn — amber pill, hue + word, never gates an action. */
    .readiness-pill {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--state-error-fg);
        background: var(--state-error-bg);
        border: 1px solid oklch(0.86 0.130 75 / 0.4);
        border-radius: 999px;
        padding: 1px 7px;
        white-space: nowrap;
    }
    /* Outstanding flagged segments on a Ready-to-generate row — same non-blocking
       pill pattern as the readiness warn. */
    .flagged-pill {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 600;
        color: var(--state-error-fg);
        background: var(--state-error-bg);
        border: 1px solid oklch(0.86 0.130 75 / 0.4);
        border-radius: 999px;
        padding: 1px 7px;
        white-space: nowrap;
    }

    .row-meta { flex-shrink: 0; display: inline-flex; align-items: center; gap: var(--s-2); white-space: nowrap; }

    .chip {
        display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 7px;
        background: var(--panel-2); border: 1px solid var(--border-quiet); border-radius: 999px;
        font-size: 11px; font-family: var(--font-mono); color: var(--text-secondary); white-space: nowrap;
    }
    .chip-key { font-weight: 600; font-size: 9.5px; color: var(--text-faint); letter-spacing: 0.05em; text-transform: uppercase; }
    .chip-val { font-variant-numeric: tabular-nums; }
    .chip-faint { color: var(--text-faint); }
    .chip-stale { background: var(--state-error-bg); border-color: oklch(0.86 0.130 75 / 0.4); color: var(--state-error-fg); }
    .reason-tag { margin-left: 4px; font-size: 9.5px; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase; opacity: 0.85; }
    .chip-pending { background: var(--state-available-bg); border-color: oklch(0.84 0.110 300 / 0.4); color: var(--state-available-fg); }
    .chip-settled { background: var(--panel); border-color: var(--border-quiet); color: var(--text-muted); }
    .chip-warn { background: var(--state-error-bg); border-color: oklch(0.86 0.130 75 / 0.4); color: var(--state-error-fg); }

    .actions { display: inline-flex; align-items: center; gap: var(--s-1); }
    .btn {
        background: transparent; border: 1px solid var(--border-quiet); color: var(--text-secondary);
        font: inherit; font-size: var(--fs-meta); padding: 3px 10px; border-radius: var(--r-1);
        cursor: pointer; white-space: nowrap;
        transition: border-color var(--t-fast), color var(--t-fast), background-color var(--t-fast);
    }
    .btn:hover:not(:disabled) { border-color: var(--border-default); color: var(--text-primary); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-ghost { color: var(--text-muted); }
    .btn.armed { border-color: var(--accent); color: var(--accent-strong); background: var(--accent-tint-soft); }
    .btn-ts:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-strong); }

    .flight { display: inline-flex; align-items: center; gap: var(--s-2); font-size: var(--fs-meta); font-family: var(--font-mono); }
    .badge { display: inline-flex; align-items: center; gap: 5px; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; border-radius: 999px; padding: 2px 8px; background: var(--panel-2); color: var(--text-secondary); }
    .badge.run { color: var(--accent-strong); background: var(--accent-tint-soft); }
    .flight-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); animation: rel-pulse 1.2s ease-in-out infinite; }
    @keyframes rel-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
    .flight-when { color: var(--text-muted); font-variant-numeric: tabular-nums; }
    .hf-link { font-size: 10px; font-weight: 600; color: var(--accent-strong); text-decoration: none; white-space: nowrap; }
    .hf-link:hover { text-decoration: underline; }
    .cancel-job {
        font-family: var(--font-mono); font-size: 10px; font-weight: 600; background: transparent;
        color: var(--state-error-fg); border: 1px solid oklch(0.86 0.130 75 / 0.4);
        border-radius: var(--r-1); padding: 2px 8px; cursor: pointer; white-space: nowrap;
    }
    .cancel-job:hover:not(:disabled) { background: var(--state-error-bg); }
    .cancel-job:disabled { opacity: 0.6; cursor: not-allowed; }

    .row-err { font-size: var(--fs-meta); color: var(--state-error-fg); padding: 0 var(--s-3) var(--s-2); }

    @media (prefers-reduced-motion: reduce) {
        .flight-dot { animation: none; }
    }
</style>
