<script lang="ts">
    /**
     * One recitation row in the Releases tab landing list.
     *
     * Two-zone flex (mirrors ``ReviewsRow.svelte``): identity grows on the
     * left, intrinsic-width meta cluster on the right.
     *   Line 1 — Latin name (primary) + Arabic name (muted, trailing).
     *   Line 2 — riwayah · style · channel (muted dotted).
     *   Right — TS / HF / GH chips + action button (bucket-dependent).
     *
     * ``bucket`` drives the action: Re-publish for stale / published_current,
     * Publish-to-HF for waiting, spinner+job link for in_flight, no button
     * for excluded. Published (current + stale) rows ALSO expose a secondary
     * "Regenerate TS" action that re-runs MFA alignment — on completion the row
     * lands in "Stale on HF" (the HF release got stale-stamped) ready to
     * re-publish. Publish is gated by ``release.publish_hf``; regen by
     * ``reviews.generate_timestamps`` + ``reciter.publish`` — all per the
     * capability registry (NOT a hardcoded role per CLAUDE.md).
     */
    import { can } from '../../../../../lib/stores/capabilities';
    import type {
        InFlightJob,
        ReleaseStatusRow,
    } from '../../../../../lib/api/admin-releases';

    export type ReleasesBucket =
        | 'in_flight'
        | 'stale_hf'
        | 'waiting'
        | 'published_current'
        | 'excluded';

    interface Props {
        row: ReleaseStatusRow;
        bucket: ReleasesBucket;
        /** Live job for this row (only set when bucket === 'in_flight'). */
        inFlightJob?: InFlightJob | null;
        /** Set to true while the row's Publish button is racing the launch
         *  response; the parent toggles it to disable the row's action. */
        busy?: boolean;
        /** Optional inline error (e.g. 409 from publish) — rendered below the
         *  meta cluster, mirrors Reviews row pattern. */
        errorMessage?: string | null;
        /** Set to true while the row's Regenerate-TS button is racing the
         *  launch response; the parent toggles it to disable the row's action. */
        regenBusy?: boolean;
        onPublish?: (_slug: string) => void;
        /** Re-run MFA alignment for a published (current/stale) reciter. */
        onRegenerate?: (_slug: string) => void;
    }
    let { row, bucket, inFlightJob = null, busy = false,
          errorMessage = null, regenBusy = false, onPublish, onRegenerate }: Props = $props();

    const canPublish = can('release.publish_hf');
    // Regen is publish-equivalent (re-runs the MFA job that auto-publishes),
    // so it needs both the generate + publish caps — same pair the Reviews-tab
    // Generate-TS action checks.
    const canGenerateTs = can('reviews.generate_timestamps');
    const canReciterPublish = can('reciter.publish');
    // Only published rows can be regenerated — waiting rows have never been
    // published (Publish is their action), in_flight/excluded have no action.
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

    function ghChipLabel(): { glyph: string; label: string; tone: 'ok' | 'warn' | 'faint' | 'excluded' } {
        if (!row.gh_release_eligible) {
            return { glyph: '–', label: 'excluded', tone: 'excluded' };
        }
        if (!row.gh) return { glyph: '·', label: 'not in cut', tone: 'faint' };
        if (row.gh.stale_since) return { glyph: '⚠', label: `stale (${row.gh.change_kind})`, tone: 'warn' };
        const map: Record<string, string> = { added: '+ added', refresh: '↻ refresh', unchanged: '· current' };
        return { glyph: '', label: map[row.gh.change_kind] ?? row.gh.change_kind, tone: 'ok' };
    }
    const ghChip = $derived(ghChipLabel());

    function actionLabel(): string {
        if (bucket === 'stale_hf') return 'Re-publish (stale)';
        if (bucket === 'waiting') return 'Publish to HF';
        if (bucket === 'published_current') return 'Re-publish';
        return '';
    }
</script>

<div class="row" class:row--inflight={bucket === 'in_flight'}>
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

        <span class="chip chip-hf" class:chip-stale={row.hf?.stale_since} title={row.hf ? `HF ${shortVer(row.hf.version)} · ${fmtRelative(row.hf.produced_at)}${row.hf.stale_since ? ' · stale' : ''}` : 'Not published'}>
            <span class="chip-key">HF</span>
            {#if row.hf}
                <span class="chip-val">{fmtRelative(row.hf.produced_at)}</span>
                {#if row.hf.stale_since}<span class="chip-stale-dot" aria-label="stale"></span>{/if}
            {:else}
                <span class="chip-val chip-faint">—</span>
            {/if}
        </span>

        <span class="chip chip-gh chip-{ghChip.tone}" title={`GH: ${ghChip.label}`}>
            <span class="chip-key">GH</span>
            <span class="chip-val">{ghChip.glyph}{ghChip.glyph ? ' ' : ''}{ghChip.label}</span>
        </span>

        {#if bucket === 'in_flight'}
            <span class="action-flight" title={`Job ${inFlightJob?.job_id ?? ''}`}>
                <span class="flight-dot" aria-hidden="true"></span>
                in flight{inFlightJob?.started_at ? ` · ${fmtRelative(inFlightJob.started_at)}` : ''}
            </span>
        {:else if bucket === 'excluded'}
            <span class="action-faint" title="Channel is not in the GH release allow-list">
                read-only
            </span>
        {:else}
            <span class="actions">
                {#if showRegen && onRegenerate && $canGenerateTs && $canReciterPublish}
                    <button
                        class="btn btn-ghost"
                        type="button"
                        onclick={(e) => { e.stopPropagation(); onRegenerate?.(row.slug); }}
                        disabled={busy || regenBusy}
                        title="Re-run MFA alignment — re-publish afterwards to refresh HF/GH"
                    >
                        {regenBusy ? 'Launching…' : 'Regenerate TS'}
                    </button>
                {/if}
                {#if onPublish && $canPublish}
                    <button
                        class="btn"
                        class:btn-warn={bucket === 'stale_hf'}
                        type="button"
                        onclick={(e) => { e.stopPropagation(); onPublish?.(row.slug); }}
                        disabled={busy || regenBusy || !row.ts}
                        title={!row.ts ? 'Generate timestamps before publishing' : ''}
                    >
                        {busy ? 'Launching…' : actionLabel()}
                    </button>
                {/if}
            </span>
        {/if}
    </div>

    {#if errorMessage}
        <div class="row-err" role="alert">{errorMessage}</div>
    {/if}
</div>

<style>
    .row {
        display: grid;
        grid-template-columns: 1fr auto;
        align-items: center;
        column-gap: var(--s-5);
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        transition: background-color var(--t-fast);
    }
    .row:last-child { border-bottom: 0; }
    .row:hover { background: var(--panel); }
    .row--inflight { background: var(--accent-tint-soft); }
    .row--inflight:hover { background: var(--accent-tint); }

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
    .chip-stale {
        background: oklch(0.97 0.04 80);
        border-color: oklch(0.84 0.130 70);
    }
    .chip-stale-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        background: oklch(0.84 0.130 70);
        margin-left: 2px;
    }
    .chip-ok {
        background: var(--accent-tint-soft);
        border-color: var(--accent-tint);
        color: var(--accent-strong);
    }
    .chip-warn {
        background: oklch(0.97 0.04 80);
        border-color: oklch(0.84 0.130 70);
        color: oklch(0.40 0.10 70);
    }
    .chip-excluded {
        background: var(--panel);
        color: var(--text-faint);
        border-color: var(--border-quiet);
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
    .btn-warn {
        border-color: oklch(0.84 0.130 70);
        color: oklch(0.42 0.10 70);
    }
    .btn-warn:hover:not(:disabled) {
        background: oklch(0.97 0.04 80);
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }

    .action-flight {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: var(--fs-meta);
        color: var(--accent-strong);
        font-family: var(--font-mono);
    }
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

    .action-faint {
        font-size: var(--fs-meta);
        color: var(--text-faint);
        font-style: italic;
    }

    .row-err {
        grid-column: 1 / -1;
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
        margin-top: 4px;
    }
</style>
