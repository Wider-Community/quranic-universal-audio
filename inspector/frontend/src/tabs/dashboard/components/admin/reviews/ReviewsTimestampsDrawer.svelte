<script lang="ts">
    /**
     * Reviews Timestamps drawer.
     *
     * Opens from the "Generate TS" button on a marked-ready row (generating
     * timestamps publishes the reciter on success). Three sections:
     *   1. Settings form — alignment beam, probe beams, persist-audio +
     *      gen-peaks toggles, collapsible Advanced (workers/flavor/timeout).
     *   2. Live log pane — after launch (or selecting a running job), polls
     *      ``GET /api/admin/jobs/<id>`` via ``visiblePoll`` and renders the
     *      status badge + log tail. Stops polling on terminal status.
     *   3. Job history — persisted records for this reciter; clicking one
     *      loads its durable record (settings + full logs), viewable any time
     *      after completion.
     */
    import {
        fetchJobRecord,
        fetchJobStatus,
        fetchTsJobRecords,
        generateTimestamps,
        type TimestampsJobSettings,
        type TimestampsJobStatus,
    } from '../../../../../lib/api/admin-reviews';
    import type { TsJobRecord } from '../../../../../lib/types/generated/schemas';
    import { visiblePoll } from '../../../../../lib/utils/visible-poll';

    let { slug, onclose }: { slug: string; onclose: () => void } = $props();

    // ---- form state ----
    let beam = $state(50);
    let probeBeamsRaw = $state('');
    let persistAudio = $state(false);
    let genPeaks = $state(false);
    let advancedOpen = $state(false);
    let workers = $state<number | null>(null);
    let flavor = $state('');
    let timeout = $state('');

    let launching = $state(false);
    let formError = $state<string | null>(null);

    // ---- live job + logs ----
    let activeJobId = $state<string | null>(null);
    let liveStatus = $state<TimestampsJobStatus | null>(null);
    let viewingRecord = $state<TsJobRecord | null>(null); // a past run opened read-only
    let stopPoll: (() => void) | null = null;
    // Epoch-ms start of the live job (launch time, or the resumed record's
    // started_at) + a 1 s tick so the elapsed timer re-renders while polling.
    // Kept client-side so the hot poll path stays a single HF round-trip.
    let liveStartedAt = $state<number | null>(null);
    let nowTick = $state(0);

    // ---- history ----
    let history = $state<TsJobRecord[]>([]);
    let historyLoading = $state(false);

    const TERMINAL = new Set([
        'succeeded', 'completed', 'failed', 'error', 'errored',
        'timed-out', 'timeout', 'stopped', 'canceled', 'cancelled', 'deleted',
    ]);

    function parseProbe(raw: string): number[] {
        return raw
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean)
            .map((t) => Number(t))
            .filter((n) => Number.isInteger(n) && n > 0);
    }

    const beamsPreview = $derived.by(() => {
        const out: number[] = [];
        for (const b of [beam, ...parseProbe(probeBeamsRaw)]) {
            if (Number.isInteger(b) && b > 0 && !out.includes(b)) out.push(b);
        }
        return out;
    });

    async function loadHistory(): Promise<void> {
        historyLoading = true;
        try {
            history = await fetchTsJobRecords(slug);
        } catch {
            /* non-fatal — the form still works without history */
        } finally {
            historyLoading = false;
        }
    }

    // Reset everything when the slug changes; load that reciter's history.
    $effect(() => {
        const s = slug;
        teardownPoll();
        activeJobId = null;
        liveStatus = null;
        viewingRecord = null;
        liveStartedAt = null;
        formError = null;
        void s;
        void loadHistory();
        return () => teardownPoll();
    });

    // Tick once a second while a job is live so the elapsed timer re-renders.
    $effect(() => {
        if (!isLive) return;
        nowTick = Date.now();
        const id = setInterval(() => (nowTick = Date.now()), 1000);
        return () => clearInterval(id);
    });

    function teardownPoll(): void {
        stopPoll?.();
        stopPoll = null;
    }

    function startPolling(jobId: string, startedAtMs: number | null = null): void {
        teardownPoll();
        viewingRecord = null;
        activeJobId = jobId;
        liveStartedAt = startedAtMs;
        nowTick = Date.now();
        liveStatus = { job_id: jobId, status: 'running', logs: [] };
        stopPoll = visiblePoll<TimestampsJobStatus>({
            intervalMs: 2500,
            fetcher: (signal) => fetchJobStatus(slug, jobId, signal),
            onResult: (res) => {
                liveStatus = res;
                if (TERMINAL.has(res.status)) {
                    teardownPoll();
                    void loadHistory(); // refresh the persisted record
                }
            },
            onError: () => {
                /* transient poll error — keep last good status */
            },
        });
    }

    async function onLaunch(): Promise<void> {
        if (launching) return;
        formError = null;
        if (!beamsPreview.length) {
            formError = 'beam must be a positive integer';
            return;
        }
        const settings: TimestampsJobSettings = {
            beam,
            probe_beams: parseProbe(probeBeamsRaw),
            persist_audio: persistAudio,
            gen_peaks: genPeaks,
            workers: advancedOpen ? workers : null,
            flavor: advancedOpen && flavor.trim() ? flavor.trim() : null,
            timeout: advancedOpen && timeout.trim() ? timeout.trim() : null,
        };
        launching = true;
        try {
            const { job_id } = await generateTimestamps(slug, settings);
            startPolling(job_id, Date.now());
        } catch (err) {
            formError = (err as Error).message ?? 'Failed to launch job';
        } finally {
            launching = false;
        }
    }

    async function openPastJob(rec: TsJobRecord): Promise<void> {
        const jid = rec.job_id;
        if (!jid) return;
        // A still-running past job → resume live polling; else show its record.
        if (!TERMINAL.has(rec.status ?? '')) {
            startPolling(jid, parseIso(rec.started_at));
            return;
        }
        teardownPoll();
        activeJobId = jid;
        liveStatus = null;
        liveStartedAt = null;
        let record: TsJobRecord;
        try {
            record = (await fetchJobRecord(slug, jid)) ?? rec;
        } catch {
            record = rec;
        }
        // Backfill logs from HF if the durable record never captured them
        // (job completed while the drawer was closed → the poll backstop that
        // persists logs never ran). Best-effort: silent if retention expired.
        if (!record.logs?.length) {
            try {
                const live = await fetchJobStatus(slug, jid);
                if (live.logs?.length) {
                    record = { ...record, logs: live.logs, log_truncated: live.log_truncated };
                }
            } catch {
                /* HF log retention expired — nothing to backfill */
            }
        }
        viewingRecord = record;
    }

    function shortId(id: string | undefined): string {
        return id ? id.slice(0, 10) : '—';
    }

    function fmtTime(iso: string | null | undefined): string {
        if (!iso) return '';
        const d = Date.parse(iso);
        return Number.isNaN(d) ? '' : new Date(d).toLocaleString();
    }

    function parseIso(iso: string | null | undefined): number | null {
        if (!iso) return null;
        const ms = Date.parse(iso);
        return Number.isNaN(ms) ? null : ms;
    }

    /** Human "1h 02m" / "3m 12s" / "45s" from a duration in ms. */
    function fmtDuration(ms: number | null | undefined): string {
        if (ms == null || !Number.isFinite(ms) || ms < 0) return '';
        const total = Math.floor(ms / 1000);
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
        if (m) return `${m}m ${String(s).padStart(2, '0')}s`;
        return `${s}s`;
    }

    function durationFromIso(start?: string | null, end?: string | null): number | null {
        const a = parseIso(start);
        const b = parseIso(end);
        return a != null && b != null ? b - a : null;
    }

    function histDuration(rec: TsJobRecord): string {
        return fmtDuration(durationFromIso(rec.started_at, rec.ended_at));
    }

    // The logs + status currently shown in the pane (live job OR opened record).
    const paneStatus = $derived(liveStatus?.status ?? viewingRecord?.status ?? null);
    const paneLogs = $derived(liveStatus?.logs ?? viewingRecord?.logs ?? []);
    const paneTruncated = $derived(
        liveStatus?.log_truncated ?? viewingRecord?.log_truncated ?? false,
    );
    const isLive = $derived(!!liveStatus && !TERMINAL.has(liveStatus.status));

    // Elapsed (live job) or total (opened completed record) for the pane header.
    const paneDuration = $derived.by(() => {
        if (isLive) {
            return liveStartedAt != null ? fmtDuration(nowTick - liveStartedAt) : '';
        }
        return fmtDuration(durationFromIso(viewingRecord?.started_at, viewingRecord?.ended_at));
    });

    function badgeClass(status: string | null): string {
        if (!status) return '';
        if (status === 'succeeded' || status === 'completed') return 'ok';
        if (TERMINAL.has(status)) return 'fail';
        return 'run';
    }
</script>

<aside class="drawer" aria-label="Generate timestamps">
    <header class="drawer-head">
        <div class="drawer-context">
            <div class="drawer-title">Generate timestamps</div>
            <div class="recitation-meta">{slug}</div>
        </div>
        <button class="drawer-close" type="button" onclick={onclose} aria-label="Close">×</button>
    </header>

    <div class="drawer-body">
        <!-- Settings -->
        <section class="dsection">
            <div class="form">
                <div class="settings-top">
                    <h3 class="dsection-head settings-head">Settings</h3>
                    <div class="beam-row">
                        <label class="field beam-field">
                            <span>Alignment beam</span>
                            <input class="num" type="number" min="1" bind:value={beam} />
                        </label>
                        <label class="field">
                            <span>Probe beams <em>optional</em></span>
                            <input type="text" bind:value={probeBeamsRaw} placeholder="e.g. 2, 5" />
                        </label>
                    </div>
                </div>

                <div class="toggles">
                    <label class="check">
                        <input type="checkbox" bind:checked={persistAudio} />
                        <span>Persist CDN audio to bucket <em>Xing-injected</em></span>
                    </label>
                    <label class="check sub" class:disabled={!persistAudio}>
                        <input type="checkbox" bind:checked={genPeaks} disabled={!persistAudio} />
                        <span>Generate v3 peaks for persisted chapters</span>
                    </label>
                </div>

                <button
                    type="button"
                    class="adv-toggle"
                    onclick={() => (advancedOpen = !advancedOpen)}
                    aria-expanded={advancedOpen}
                >
                    {advancedOpen ? '▾' : '▸'} Advanced
                </button>
                {#if advancedOpen}
                    <div class="advanced">
                        <label class="field">
                            <span>Workers <em>blank → server default</em></span>
                            <input class="num" type="number" min="1" max="64" bind:value={workers} />
                        </label>
                        <div class="beam-row">
                            <label class="field">
                                <span>Flavor</span>
                                <input type="text" bind:value={flavor} placeholder="cpu-upgrade" />
                            </label>
                            <label class="field beam-field">
                                <span>Timeout</span>
                                <input type="text" bind:value={timeout} placeholder="2h" />
                            </label>
                        </div>
                    </div>
                {/if}

                {#if formError}
                    <div class="form-error" role="alert">{formError}</div>
                {/if}
                <button
                    type="button"
                    class="launch"
                    onclick={onLaunch}
                    disabled={launching}
                >{launching ? 'Launching…' : 'Generate timestamps'}</button>
            </div>
        </section>

        <!-- Live / opened logs -->
        {#if activeJobId}
            <section class="dsection">
                <h3 class="dsection-head">
                    Logs — {shortId(activeJobId)}
                    {#if paneStatus}
                        <span class="badge {badgeClass(paneStatus)}">{paneStatus}</span>
                    {/if}
                    {#if paneDuration}
                        <span class="dur" title={isLive ? 'elapsed' : 'duration'}>{paneDuration}</span>
                    {/if}
                    {#if isLive}<span class="live-dot" title="polling">●</span>{/if}
                </h3>
                {#if paneLogs.length}
                    <pre class="logs">{paneTruncated ? '… (earlier lines truncated)\n' : ''}{paneLogs.join('\n')}</pre>
                {:else}
                    <div class="muted">No log lines yet.</div>
                {/if}
            </section>
        {/if}

        <!-- History -->
        <section class="dsection">
            <h3 class="dsection-head">History</h3>
            {#if historyLoading}
                <div class="muted">Loading…</div>
            {:else if !history.length}
                <div class="muted">No previous runs.</div>
            {:else}
                <ul class="history">
                    {#each history as rec (rec.job_id)}
                        <li>
                            <button
                                type="button"
                                class="hist-row"
                                class:active={rec.job_id === activeJobId}
                                onclick={() => openPastJob(rec)}
                            >
                                <span class="badge {badgeClass(rec.status ?? null)}">{rec.status}</span>
                                <span class="hist-id">{shortId(rec.job_id)}</span>
                                <span class="hist-meta">
                                    beams [{(rec.settings?.beams ?? []).join(', ')}]
                                    {#if rec.settings?.persist_audio}· audio{/if}
                                    {#if rec.settings?.gen_peaks}· peaks{/if}
                                </span>
                                {#if histDuration(rec)}
                                    <span class="hist-dur" title="duration">{histDuration(rec)}</span>
                                {/if}
                                <span class="hist-time">{fmtTime(rec.started_at)}</span>
                            </button>
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>
    </div>
</aside>

<style>
    .drawer {
        position: absolute;
        top: 0; right: 0; bottom: 0;
        width: 46%;
        max-width: 540px;
        min-width: 420px;
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
    .recitation-meta {
        font-size: 11px;
        color: var(--text-muted);
        font-family: var(--font-mono);
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

    .dsection { margin-bottom: var(--s-6); }
    .dsection:last-child { margin-bottom: 0; }
    .dsection-head {
        font-size: 10.5px;
        font-family: var(--font-mono);
        color: var(--text-faint);
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 0 0 var(--s-3);
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: var(--s-2);
    }

    .form {
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
        max-width: 470px;
    }
    /* "Settings" rides alongside the input row instead of claiming its own
       line — kills the empty band under a lone heading. */
    .settings-top {
        display: flex;
        align-items: flex-end;
        gap: var(--s-4);
    }
    .settings-head { margin: 0 0 9px; flex-shrink: 0; }
    .settings-top .beam-row { flex: 1; }
    /* Numeric beam sits beside the wider probe list — a 2-digit value never
       needs full width, and the pairing kills the stacked-box monotony. */
    .beam-row {
        display: grid;
        grid-template-columns: 7rem 1fr;
        gap: var(--s-3);
        align-items: end;
    }
    .field { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
    .field span {
        font-size: 10.5px;
        color: var(--text-faint);
        font-family: var(--font-mono);
        letter-spacing: 0.02em;
        text-transform: uppercase;
        display: flex;
        gap: 0.4em;
        align-items: baseline;
    }
    .field span em {
        font-style: normal;
        text-transform: none;
        letter-spacing: 0;
        color: var(--text-faint);
        opacity: 0.7;
        font-size: 9.5px;
    }
    .field input {
        background: var(--canvas);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: 7px 10px;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        transition: border-color var(--t-fast) var(--ease-out-quart),
                    box-shadow var(--t-fast) var(--ease-out-quart);
    }
    .field input.num { font-variant-numeric: tabular-nums; }
    .field input::placeholder { color: var(--text-faint); }
    .field input:hover { border-color: var(--border-default); }
    .field input:focus {
        outline: 0;
        border-color: var(--accent);
        box-shadow: 0 0 0 3px var(--accent-tint-soft);
    }
    .toggles { display: flex; flex-direction: column; gap: var(--s-2); }
    .check {
        display: flex;
        align-items: flex-start;
        gap: var(--s-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        line-height: 1.4;
        cursor: pointer;
    }
    /* Dependent toggle nests under its parent so the relationship is structural. */
    .check.sub {
        margin-left: var(--s-5);
        padding-left: var(--s-3);
        border-left: 1px solid var(--border-quiet);
    }
    .check.disabled { opacity: 0.45; cursor: default; }
    .check span em {
        font-style: normal;
        color: var(--text-faint);
        font-size: 10px;
    }
    .check input { margin-top: 1px; accent-color: var(--accent); cursor: inherit; }

    .adv-toggle {
        align-self: flex-start;
        background: transparent;
        border: 0;
        color: var(--text-muted);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
        padding: 0;
        transition: color var(--t-fast) var(--ease-out-quart);
    }
    .adv-toggle:hover { color: var(--text-primary); }
    .advanced {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
        padding: var(--s-3);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        background: var(--panel-2);
        margin-top: calc(-1 * var(--s-2));
    }

    .form-error { color: var(--state-error-fg); font-size: var(--fs-meta); }
    /* Primary commit — full-width anchor of the form, not a floating button. */
    .launch {
        width: 100%;
        margin-top: var(--s-1);
        background: var(--accent);
        color: var(--accent-fg);
        border: 0;
        padding: 9px 16px;
        border-radius: var(--r-2);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-body);
        font-weight: 600;
        letter-spacing: 0.01em;
        transition: background var(--t-fast) var(--ease-out-quart);
    }
    .launch:hover:not(:disabled) { background: var(--accent-strong); }
    .launch:disabled { opacity: 0.6; cursor: not-allowed; }

    .badge {
        font-family: var(--font-mono);
        font-size: 9.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        border-radius: 999px;
        padding: 1px 7px;
        background: var(--panel-2);
        color: var(--text-muted);
    }
    .badge.ok { color: var(--accent-strong); background: var(--accent-tint-soft); }
    .badge.fail { color: var(--state-error-fg); background: var(--state-error-bg, var(--panel-2)); }
    .badge.run { color: var(--text-secondary); }
    .live-dot { color: var(--accent); font-size: 9px; animation: pulse 1.4s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }
    .dur {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }

    .logs {
        margin: 0;
        max-height: 320px;
        overflow: auto;
        background: var(--canvas);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: var(--s-3);
        font-family: var(--font-mono);
        font-size: 11px;
        line-height: 1.45;
        color: var(--text-secondary);
        white-space: pre-wrap;
        word-break: break-word;
    }
    .muted { color: var(--text-muted); font-size: var(--fs-meta); }

    .history { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .hist-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        text-align: left;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 6px 10px;
        cursor: pointer;
        font: inherit;
        color: var(--text-secondary);
    }
    .hist-row:hover { border-color: var(--border-default); }
    .hist-row.active { border-color: var(--accent); }
    .hist-id { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); }
    .hist-meta { font-size: 10.5px; color: var(--text-muted); flex: 1; }
    .hist-dur { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); white-space: nowrap; font-variant-numeric: tabular-nums; }
    .hist-time { font-size: 10px; color: var(--text-faint); font-family: var(--font-mono); white-space: nowrap; }
</style>
