<script lang="ts">
    /**
     * Top zone of the Releases compartment — current GH release at a glance.
     *
     * Three states:
     *   - Has a current release: "vX.Y.Z · M recitations · X.X MB · cut Nd ago"
     *     with an external link to the GH release page.
     *   - No release yet: "No releases yet · N ready" (N = the readyCount the
     *     parent computes from the bucketed rows).
     *   - Nothing to release: "Nothing to release yet" (parent passes
     *     readyCount=0 with no summary).
     *
     * Cut button gated by ``release.cut_gh`` (NOT ``$isOwner`` — capabilities
     * own gating per CLAUDE.md). Disabled with a tooltip when the parent
     * computes a cutDisabledReason (in-flight cut OR nothing changed since
     * last cut).
     *
     * In-flight strip renders ABOVE the version line, one row per live job.
     * Click → ``onJumpToInFlight()`` so the parent can scroll the In Progress
     * section into view.
     */
    import { can } from '../../../../../lib/stores/capabilities';
    import type {
        InFlightJob,
        ReleasesSummary,
    } from '../../../../../lib/api/admin-releases';

    interface Props {
        summary: ReleasesSummary | null;
        inFlight: InFlightJob[];
        /** Number of recitations that would land in the next cut — surfaced
         *  in the "No releases yet" state and as supplementary info on the
         *  Cut button tooltip when changes exist. */
        readyCount: number;
        onCut: () => void;
        /** Non-null when the Cut button should be disabled — string becomes
         *  the title= tooltip. Common values: "A cut is already in flight",
         *  "Nothing changed since last cut". */
        cutDisabledReason: string | null;
        onJumpToInFlight?: () => void;
    }
    let { summary, inFlight, readyCount, onCut, cutDisabledReason,
          onJumpToInFlight }: Props = $props();

    const canCut = can('release.cut_gh');

    function fmtBytes(n: number): string {
        if (!n) return '0 B';
        const u = ['B', 'KB', 'MB', 'GB', 'TB'];
        let i = 0;
        let v = n;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
        const precision = v >= 100 ? 0 : v >= 10 ? 1 : 2;
        return `${v.toFixed(precision)} ${u[i]}`;
    }

    function fmtDays(d: number | null): string {
        if (d === null) return '';
        if (d === 0) return 'today';
        if (d === 1) return '1d ago';
        if (d < 30) return `${d}d ago`;
        const months = Math.floor(d / 30);
        if (months < 12) return `${months}mo ago`;
        const years = Math.floor(d / 365);
        return `${years}y ago`;
    }

    function fmtRelative(iso: string | null): string {
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
        return `${days}d ago`;
    }

    function jobLabel(j: InFlightJob): string {
        if (j.kind === 'cut_release') return 'Cutting GH release';
        return `Publishing ${j.slug ?? '?'}`;
    }
</script>

<section class="card">
    {#if inFlight.length > 0}
        {@const solo = inFlight.length === 1 ? inFlight[0] : null}
        <button
            class="flight-strip"
            type="button"
            onclick={() => onJumpToInFlight?.()}
            title="Jump to In progress section"
        >
            <span class="flight-spinner" aria-hidden="true"></span>
            <span class="flight-label">
                {solo ? jobLabel(solo) : `${inFlight.length} jobs in flight`}
            </span>
            {#if solo?.started_at}
                <span class="flight-when">· {fmtRelative(solo.started_at)}</span>
            {/if}
        </button>
    {/if}

    <div class="card-row">
        <div class="lhs">
            {#if summary}
                <span class="lhs-label">Current GH release</span>
                <div class="lhs-line">
                    {#if summary.external_uri}
                        <a class="ver" href={summary.external_uri} target="_blank" rel="noopener">
                            {summary.version}
                        </a>
                    {:else}
                        <span class="ver">{summary.version}</span>
                    {/if}
                    <span class="sep">·</span>
                    <span class="metric">{summary.member_count} recitations</span>
                    <span class="sep">·</span>
                    <span class="metric">{fmtBytes(summary.total_bytes)}</span>
                    {#if summary.days_since_cut !== null}
                        <span class="sep">·</span>
                        <span class="metric metric-faint">cut {fmtDays(summary.days_since_cut)}</span>
                    {/if}
                </div>
            {:else if readyCount > 0}
                <span class="lhs-label">No releases yet</span>
                <div class="lhs-line">
                    <span class="metric">{readyCount} recitation{readyCount === 1 ? '' : 's'} ready to cut</span>
                </div>
            {:else}
                <span class="lhs-label">Releases</span>
                <div class="lhs-line">
                    <span class="metric metric-faint">Nothing to release yet</span>
                </div>
            {/if}
        </div>

        {#if $canCut}
            <button
                class="cut-btn"
                type="button"
                onclick={onCut}
                disabled={cutDisabledReason !== null}
                title={cutDisabledReason ?? ''}
            >
                {summary ? 'Cut new release' : 'Cut first release'}
            </button>
        {/if}
    </div>
</section>

<style>
    .card {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding: var(--s-3);
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
    }

    .card-row {
        display: flex;
        align-items: center;
        gap: var(--s-3);
    }

    .lhs {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .lhs-label {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .lhs-line {
        display: flex;
        align-items: baseline;
        gap: var(--s-2);
        flex-wrap: wrap;
        font-size: var(--fs-row);
        color: var(--text-primary);
    }
    .ver {
        font-family: var(--font-mono);
        font-weight: 600;
        color: var(--text-primary);
        text-decoration: none;
    }
    a.ver:hover { color: var(--accent); text-decoration: underline; }
    .sep { color: var(--text-faint); }
    .metric {
        color: var(--text-secondary);
        font-size: var(--fs-meta);
        font-variant-numeric: tabular-nums;
    }
    .metric-faint { color: var(--text-faint); }

    .cut-btn {
        background: var(--accent);
        color: var(--text-on-accent);
        border: 0;
        border-radius: var(--r-1);
        padding: 6px 14px;
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 500;
        cursor: pointer;
        white-space: nowrap;
        transition: background-color var(--t-fast);
    }
    .cut-btn:hover:not(:disabled) { background: var(--accent-strong); }
    .cut-btn:disabled {
        background: var(--panel);
        color: var(--text-faint);
        border: 1px solid var(--border-quiet);
        cursor: not-allowed;
    }

    /* In-flight strip — sits above the version line. Matches the chip-style
     * affordance from Reviews; click jumps the list. */
    .flight-strip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        align-self: flex-start;
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent-tint);
        border-radius: 999px;
        color: var(--accent-strong);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 3px 10px;
        cursor: pointer;
        transition: background-color var(--t-fast);
    }
    .flight-strip:hover { background: var(--accent-tint); }
    .flight-spinner {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--accent);
        animation: pulse 1.2s ease-in-out infinite;
    }
    .flight-label { font-weight: 500; }
    .flight-when {
        color: var(--accent);
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50%      { opacity: 0.35; }
    }
</style>
