<script lang="ts">
    /**
     * One recitation row in the Releases tab landing list.
     *
     * Two-zone flex (mirrors ``ReviewsRow.svelte``): a select checkbox +
     * identity grow on the left, intrinsic-width meta cluster on the right.
     *   Line 1 — Latin name (primary) + Arabic name (muted, trailing).
     *   Line 2 — riwayah · style · channel (muted dotted).
     *   Right — TS / HF / GH chips + bucket-dependent trailing affordance.
     *
     * Publishing is select-only: publishable rows (waiting / stale_hf / failed /
     * published_current) show a checkbox and the parent's action bar fires one
     * batch job for the selection. ``in_flight`` rows show a minimal job status
     * (badge + elapsed + Open-on-HF + Cancel); ``failed`` rows show the publish
     * error inline. Published (current + stale)
     * rows also expose a secondary "Regenerate TS" action that re-runs MFA
     * alignment, gated by ``reviews.generate_timestamps`` + ``reciter.publish``
     * per the capability registry (NOT a hardcoded role per CLAUDE.md).
     */
    import { can } from '../../../../../lib/stores/capabilities';
    import type {
        InFlightJob,
        ReleaseStatusRow,
    } from '../../../../../lib/api/admin-releases';

    export type ReleasesBucket =
        | 'in_flight'
        | 'failed'
        | 'stale_hf'
        | 'waiting'
        | 'published_current';

    interface Props {
        row: ReleaseStatusRow;
        bucket: ReleasesBucket;
        /** Live job for this row (only set when bucket === 'in_flight'). */
        inFlightJob?: InFlightJob | null;
        /** Whether this row can be selected for a batch publish. */
        selectable?: boolean;
        /** Whether this row is currently selected. */
        selected?: boolean;
        /** Optional inline error (e.g. a failed cancel) — rendered below the
         *  meta cluster, mirrors Reviews row pattern. */
        errorMessage?: string | null;
        /** Set to true while the row's Regenerate-TS button is racing the
         *  launch response; the parent toggles it to disable the row's action. */
        regenBusy?: boolean;
        /** True while a cancel for this row's in-flight job is racing. */
        canceling?: boolean;
        onToggleSelect?: (_slug: string) => void;
        /** Re-run MFA alignment for a published (current/stale) reciter. */
        onRegenerate?: (_slug: string) => void;
        /** Cancel this row's in-flight job. */
        onCancel?: (_jobId: string) => void;
    }
    let { row, bucket, inFlightJob = null, selectable = false, selected = false,
          errorMessage = null, regenBusy = false, canceling = false,
          onToggleSelect, onRegenerate, onCancel }: Props = $props();

    // Regen is publish-equivalent (re-runs the MFA job that auto-publishes),
    // so it needs both the generate + publish caps — same pair the Reviews-tab
    // Generate-TS action checks.
    const canGenerateTs = can('reviews.generate_timestamps');
    const canReciterPublish = can('reciter.publish');
    // Only published rows can be regenerated — waiting rows have never been
    // published (Publish is their action); in_flight rows have no action.
    const showRegen = $derived(bucket === 'published_current' || bucket === 'stale_hf');

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
        const years = Math.floor(days / 365);
        return `${years}y`;
    }

    /** Render a short version slug — HF versions are commit SHAs (long), TS
     *  versions are job IDs (also long). Truncate to 7 chars mono for chips. */
    function shortVer(v: string | null | undefined): string {
        if (!v) return '';
        const s = String(v);
        return s.length > 8 ? s.slice(0, 7) : s;
    }

    /** Human tag for the staleness cause — "metadata" (a catalog edit, cheap
     *  to reconcile) vs "timestamps" (a TS regen, needs a republish). */
    function staleReasonLabel(reason: string | null | undefined): string {
        if (reason === 'catalog_edit') return 'metadata';
        if (reason === 'ts_regen') return 'timestamps';
        return 'stale';
    }

    function ghChipLabel(): {
        glyph: string;
        label: string;
        tone: 'pending' | 'settled' | 'warn' | 'faint';
    } {
        if (!row.gh) return { glyph: '·', label: 'not in cut', tone: 'faint' };
        if (row.gh.stale_since) {
            return { glyph: '⚠', label: `stale · ${staleReasonLabel(row.gh.stale_reason)}`, tone: 'warn' };
        }
        // added/refresh will change in the next cut (violet "pending change");
        // unchanged is settled into the current cut (muted, reads as at-rest).
        if (row.gh.change_kind === 'unchanged') return { glyph: '·', label: 'current', tone: 'settled' };
        const map: Record<string, string> = { added: '+ added', refresh: '↻ refresh' };
        return { glyph: '', label: map[row.gh.change_kind] ?? row.gh.change_kind, tone: 'pending' };
    }
    const ghChip = $derived(ghChipLabel());
</script>

<div class="row" class:row--inflight={bucket === 'in_flight'} class:row--selected={selected}>
    {#if selectable}
        <label class="select" title="Select for batch publish">
            <input
                type="checkbox"
                checked={selected}
                onchange={() => onToggleSelect?.(row.slug)}
            />
        </label>
    {:else}
        <span class="select-spacer" aria-hidden="true"></span>
    {/if}
    <div class="identity">
        <div class="id-name">
            {#if row.name_en}
                <span class="name-en">{row.name_en}</span>
            {/if}
            {#if row.name_ar}
                <span class="name-ar" dir="rtl">{row.name_ar}</span>
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
        <span class="chip chip-ts" title={row.ts ? `TS ${row.ts.version} · ${fmtRelative(row.ts.produced_at)}` : 'No timestamps yet'}>
            <span class="chip-key">TS</span>
            {#if row.ts}
                <span class="chip-val">{fmtRelative(row.ts.produced_at)}</span>
            {:else}
                <span class="chip-val chip-faint">—</span>
            {/if}
        </span>

        <span class="chip chip-hf" class:chip-stale={row.hf?.stale_since} title={row.hf ? `HF ${shortVer(row.hf.version)} · ${fmtRelative(row.hf.produced_at)}${row.hf.stale_since ? ` · stale (${staleReasonLabel(row.hf.stale_reason)})${row.hf.suggested_action ? ` — ${row.hf.suggested_action.label}` : ''}` : ''}` : 'Not published'}>
            <span class="chip-key">HF</span>
            {#if row.hf}
                <span class="chip-val">{fmtRelative(row.hf.produced_at)}</span>
                {#if row.hf.stale_since}
                    <span class="chip-stale-dot" aria-label="stale"></span>
                    <span class="reason-tag">{staleReasonLabel(row.hf.stale_reason)}</span>
                {/if}
            {:else}
                <span class="chip-val chip-faint">—</span>
            {/if}
        </span>

        <span class="chip chip-gh chip-{ghChip.tone}" title={`GH: ${ghChip.label}${row.gh?.suggested_action ? ` — ${row.gh.suggested_action.label}` : ''}`}>
            <span class="chip-key">GH</span>
            <span class="chip-val">{ghChip.glyph}{ghChip.glyph ? ' ' : ''}{ghChip.label}</span>
        </span>

        {#if bucket === 'in_flight'}
            <span class="flight" title={`Job ${inFlightJob?.job_id ?? ''}`}>
                <span class="badge run"><span class="flight-dot" aria-hidden="true"></span>running</span>
                {#if inFlightJob?.started_at}
                    <span class="flight-when">{fmtRelative(inFlightJob.started_at)}</span>
                {/if}
                {#if inFlightJob?.url}
                    <a class="hf-link" href={inFlightJob.url} target="_blank" rel="noopener noreferrer"
                        title="Open the job on Hugging Face — logs stream live there">Open on HF ↗</a>
                {/if}
                {#if inFlightJob?.job_id && onCancel}
                    <button
                        class="cancel-job"
                        type="button"
                        onclick={(e) => { e.stopPropagation(); onCancel?.(inFlightJob.job_id); }}
                        disabled={canceling}
                        title="Cancel this job — in-progress work is lost"
                    >{canceling ? 'Cancelling…' : 'Cancel'}</button>
                {/if}
            </span>
        {:else if showRegen && onRegenerate && $canGenerateTs && $canReciterPublish}
            <span class="actions">
                <button
                    class="btn btn-ghost"
                    type="button"
                    onclick={(e) => { e.stopPropagation(); onRegenerate?.(row.slug); }}
                    disabled={regenBusy}
                    title="Re-run MFA alignment — re-publish afterwards to refresh HF/GH"
                >
                    {regenBusy ? 'Launching…' : 'Regenerate TS'}
                </button>
            </span>
        {/if}
    </div>

    {#if row.publish_error}
        <div class="row-err" role="alert">Last publish failed: {row.publish_error.message}</div>
    {/if}
    {#if errorMessage}
        <div class="row-err" role="alert">{errorMessage}</div>
    {/if}
</div>

<style>
    .row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        column-gap: var(--s-3);
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        transition: background-color var(--t-fast);
    }
    .row:last-child { border-bottom: 0; }
    .row:hover { background: var(--panel); }
    .row--inflight { background: var(--accent-tint-soft); }
    .row--inflight:hover { background: var(--accent-tint); }
    .row--selected { background: var(--accent-tint-soft); }
    .row--selected:hover { background: var(--accent-tint); }

    /* Select column — checkbox for publishable rows, a fixed-width spacer
       otherwise so identity columns stay aligned across buckets. */
    .select,
    .select-spacer {
        width: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
    }
    .select { cursor: pointer; }
    .select input { accent-color: var(--accent); cursor: pointer; margin: 0; }

    .identity {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }
    .id-name {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        min-width: 0;
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
    .id-meta {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        min-width: 0;
    }
    .id-meta .combo { color: var(--text-secondary); white-space: nowrap; }
    .id-meta .combo.channel { color: var(--text-muted); }
    .id-meta .sep { color: var(--text-faint); }

    .row-meta {
        flex-shrink: 0;
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        white-space: nowrap;
    }

    /* Status chips — compact pill style with two-tone key/value. Mirrors the
     * inline metadata chips in Reviews; one chip per track keeps the row
     * scannable left-to-right. */
    .chip {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        height: 22px;
        padding: 0 7px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        font-size: 11px;
        font-family: var(--font-mono);
        color: var(--text-secondary);
        white-space: nowrap;
    }
    .chip-key {
        font-weight: 600;
        font-size: 9.5px;
        color: var(--text-faint);
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .chip-val { font-variant-numeric: tabular-nums; }
    .chip-faint { color: var(--text-faint); }
    /* Stale HF release — amber, the dark-theme error/attention hue. */
    .chip-stale {
        background: var(--state-error-bg);
        border-color: oklch(0.86 0.130 75 / 0.4);
        color: var(--state-error-fg);
    }
    .chip-stale-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: var(--state-error-fg);
        margin-left: 2px;
    }
    /* Why the row is stale — "metadata" (cheap refresh) vs "timestamps"
       (republish). Inherits the amber stale palette from .chip-stale. */
    .reason-tag {
        margin-left: 4px;
        font-family: var(--font-mono);
        font-size: 9.5px;
        font-weight: 600;
        letter-spacing: 0.02em;
        text-transform: uppercase;
        opacity: 0.85;
    }
    /* GH tones — added/refresh pend a change (violet), unchanged is settled
       (muted), stale needs attention (amber), the rest are demoted (faint). */
    .chip-pending {
        background: var(--state-available-bg);
        border-color: oklch(0.84 0.110 300 / 0.4);
        color: var(--state-available-fg);
    }
    .chip-settled {
        background: var(--panel);
        border-color: var(--border-quiet);
        color: var(--text-muted);
    }
    .chip-warn {
        background: var(--state-error-bg);
        border-color: oklch(0.86 0.130 75 / 0.4);
        color: var(--state-error-fg);
    }

    .actions {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
    }

    .btn {
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
    .btn:hover:not(:disabled) {
        border-color: var(--accent);
        color: var(--accent-strong);
    }
    /* Secondary action — quieter than the primary Publish button so the
     * publish CTA stays dominant on published rows. */
    .btn-ghost {
        color: var(--text-muted);
        padding: 4px 10px;
    }
    .btn-ghost:hover:not(:disabled) {
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }

    /* In-flight job status — minimal: badge + elapsed + Open-on-HF + Cancel. */
    .flight {
        display: inline-flex;
        align-items: center;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        font-family: var(--font-mono);
    }
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: 9.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        border-radius: 999px;
        padding: 2px 8px;
        background: var(--panel-2);
        color: var(--text-secondary);
    }
    .badge.run { color: var(--accent-strong); background: var(--accent-tint-soft); }
    .flight-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
        animation: rel-pulse 1.2s ease-in-out infinite;
    }
    @keyframes rel-pulse {
        0%, 100% { opacity: 1; }
        50%      { opacity: 0.35; }
    }
    .flight-when {
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }
    .hf-link {
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.02em;
        color: var(--accent-strong);
        text-decoration: none;
        white-space: nowrap;
    }
    .hf-link:hover { text-decoration: underline; }
    /* Cancel — destructive secondary affordance, error-tinted so the intent is
       unambiguous next to "Open on HF ↗". */
    .cancel-job {
        font-family: var(--font-mono);
        font-size: 10px;
        font-weight: 600;
        background: transparent;
        color: var(--state-error-fg);
        border: 1px solid oklch(0.86 0.130 75 / 0.4);
        border-radius: var(--r-1);
        padding: 2px 8px;
        cursor: pointer;
        white-space: nowrap;
    }
    .cancel-job:hover:not(:disabled) { background: var(--state-error-bg); }
    .cancel-job:disabled { opacity: 0.6; cursor: not-allowed; }


    .row-err {
        grid-column: 1 / -1;
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
        margin-top: 4px;
    }
</style>
