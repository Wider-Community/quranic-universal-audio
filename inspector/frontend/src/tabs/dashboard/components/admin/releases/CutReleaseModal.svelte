<script lang="ts">
    /**
     * Cut-release dry-run document.
     *
     * Reads top-to-bottom like the output of `release cut --dry-run`:
     *   1. Version transition hero      v0.4.2  →  v0.4.3
     *   2. Diff strip                   +1 added · ~3 refreshed · ·14 carried
     *   3. Rendered release             collapsible Added / Refreshed tables,
     *                                   Schemas accordion, inline license + links —
     *                                   a faithful native render of what ships to
     *                                   GitHub (display names, no slugs)
     *   4. Operator inputs              bottom-border-only fields
     *   5. Action footer                Cancel · Cut vX.Y.Z →
     *
     * Owner-only by capability gate at the route layer; ``isOwner`` here
     * controls the manual-version override field by convention.
     *
     * The submit flow echoes ``expected_version_at_preview`` so the server
     * 409s a stale preview after a concurrent TS regen (caller re-opens).
     */
    import { isOwner } from '../../../../../lib/stores/current-user';
    import Modal from '../../../../../lib/components/Modal.svelte';
    import {
        type ReleasePreviewResponse,
        type ReleasePreviewRow,
        cutRelease,
        fetchReleasePreview,
    } from '../../../../../lib/api/admin-releases';

    interface Props {
        onclose: () => void;
        onsuccess: () => void;
    }
    let { onclose, onsuccess }: Props = $props();

    let preview = $state<ReleasePreviewResponse | null>(null);
    let loading = $state(true);
    let error = $state<string | null>(null);
    let submitting = $state(false);
    let submitError = $state<string | null>(null);

    let operatorNote = $state('');
    let manualVersion = $state('');

    async function loadPreview(): Promise<void> {
        loading = true;
        error = null;
        try {
            preview = await fetchReleasePreview();
            if (preview.needs_manual_version) manualVersion = '';
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load preview';
        } finally {
            loading = false;
        }
    }

    $effect(() => { void loadPreview(); });

    const versionRegex = /^v\d+\.\d+\.\d+$/;
    const effectiveVersion = $derived(
        manualVersion.trim() || preview?.computed_version || '',
    );
    const submitDisabled = $derived(
        submitting ||
            loading ||
            error !== null ||
            (preview?.needs_manual_version && !versionRegex.test(manualVersion.trim())) ||
            (!preview?.computed_version && !versionRegex.test(manualVersion.trim())),
    );

    // Member rollup cap — beyond this we fold into "… and N more" so a 50-row
    // release stays scannable. The full list is committed to the release; this
    // is a display-only cap.
    const MEMBER_PREVIEW_CAP = 5;

    async function onConfirm(): Promise<void> {
        if (submitDisabled || !preview) return;
        submitting = true;
        submitError = null;
        try {
            await cutRelease({
                version: manualVersion.trim() || undefined,
                operator_note: operatorNote.trim() || undefined,
                expected_version_at_preview: preview.expected_version_at_preview,
            });
            onsuccess();
        } catch (e) {
            const msg = (e as Error).message ?? 'Cut failed';
            submitError = msg.includes('drift') || msg.includes('preview')
                ? `${msg} — re-open the modal to refresh the preview.`
                : msg;
        } finally {
            submitting = false;
        }
    }
</script>

{#snippet memberTable(rows: ReleasePreviewRow[])}
    <table class="member-table">
        <thead>
            <tr><th>Reciter</th><th>Riwāyah</th><th>Style</th><th>Channel</th><th>Coverage</th></tr>
        </thead>
        <tbody>
            {#each rows.slice(0, MEMBER_PREVIEW_CAP) as row (row.slug)}
                <tr>
                    <td class="mt-id">
                        <span class="mt-en">{row.name_en ?? row.slug}</span>
                        {#if row.name_ar}<span class="mt-ar" dir="rtl">{row.name_ar}</span>{/if}
                    </td>
                    <td>{row.riwayah}</td>
                    <td>{row.style}</td>
                    <td>{row.channel}</td>
                    <td class="mt-cov">{row.coverage_surahs != null ? `${row.coverage_surahs} surahs` : '—'}</td>
                </tr>
            {/each}
            {#if rows.length > MEMBER_PREVIEW_CAP}
                <tr class="mt-more"><td colspan="5">… and {rows.length - MEMBER_PREVIEW_CAP} more</td></tr>
            {/if}
        </tbody>
    </table>
{/snippet}

<Modal open={true} size="wide" title="Cut release" elevated on:close={onclose}>
    {#if loading}
        <div class="state-block faint">Computing release preview…</div>
    {:else if error}
        <div class="state-block err">{error}</div>
    {:else if preview}
        <div class="doc">
            <header class="hero">
                <div class="version-line">
                    {#if preview.previous_version === null}
                        <span class="ver-prev em-dash">—</span>
                    {:else}
                        <span class="ver-prev">{preview.previous_version}</span>
                    {/if}
                    <span class="ver-arrow">→</span>
                    {#if preview.computed_version || manualVersion.trim()}
                        <span class="ver-next">{effectiveVersion}</span>
                    {:else}
                        <span class="ver-next ver-pending">?</span>
                    {/if}
                </div>
                {#if preview.previous_version === null}
                    <div class="hero-sub">first release</div>
                {:else if !preview.computed_version}
                    <div class="hero-sub warn">
                        Nothing changed since
                        <span class="mono">{preview.previous_version}</span> · supply a version below to force-cut
                    </div>
                {/if}
            </header>

            <div class="diff-strip">
                <span class="d">
                    <span class="d-num d-add">+{preview.change_counts.added}</span>
                    <span class="d-label">added</span>
                </span>
                <span class="d">
                    <span class="d-num d-ref">~{preview.change_counts.refresh}</span>
                    <span class="d-label">refreshed</span>
                </span>
                <span class="d">
                    <span class="d-num d-un">·{preview.change_counts.unchanged}</span>
                    <span class="d-label faint">carried</span>
                </span>
            </div>

            <section class="release-doc">
                {#if preview.added.length > 0}
                    <details class="acc" open>
                        <summary>➕ Added — {preview.added.length} recitation{preview.added.length === 1 ? '' : 's'}</summary>
                        {@render memberTable(preview.added)}
                    </details>
                {/if}
                {#if preview.refreshed.length > 0}
                    <details class="acc">
                        <summary>↻ Refreshed — {preview.refreshed.length} recitation{preview.refreshed.length === 1 ? '' : 's'}</summary>
                        {@render memberTable(preview.refreshed)}
                    </details>
                {/if}
                {#if preview.change_counts.unchanged > 0}
                    <p class="carried">{preview.change_counts.unchanged} carried / unchanged.</p>
                {/if}

                <details class="acc">
                    <summary>📐 Schemas</summary>
                    <ul class="schema-list">
                        <li><code>verse_timestamps.json.gz</code> — Tier 1. <code>"surah:ayah": [start, end]</code> (ms).</li>
                        <li><code>word_timestamps.json.gz</code> — Tier 2. + per-word <code>[widx, start, end]</code>.</li>
                        <li><code>letter_timestamps.json.gz</code> — Tier 3. + per-letter <code>[widx, char, start, end]</code>.</li>
                    </ul>
                    <p class="schema-refs">Static references: <code>surah_info.json</code>, <code>qpc_hafs.json</code>.</p>
                </details>

                <div class="release-foot">
                    <span class="lic"><strong>License:</strong> {preview.license}</span>
                    {#if preview.links.repo}
                        <a href={preview.links.repo} target="_blank" rel="noopener">Repository</a>
                    {/if}
                    {#if preview.links.hf_dataset}
                        <a href={preview.links.hf_dataset} target="_blank" rel="noopener">HF dataset</a>
                    {/if}
                </div>
            </section>

            <section class="inputs">
                <div class="field">
                    <label class="field-label" for="cm-note">
                        Operator note <span class="faint">(optional)</span>
                    </label>
                    <textarea
                        id="cm-note"
                        rows="2"
                        placeholder="e.g. MFA model upgraded to v3 — all recitations refreshed"
                        bind:value={operatorNote}
                    ></textarea>
                </div>

                {#if $isOwner}
                    <div
                        class="field"
                        class:field-required={preview.needs_manual_version}
                    >
                        <label class="field-label" for="cm-version">
                            Manual version override
                            {#if preview.needs_manual_version}
                                <span class="required">required</span>
                            {:else}
                                <span class="faint">(owner-only)</span>
                            {/if}
                        </label>
                        <input
                            id="cm-version"
                            type="text"
                            placeholder="v1.0.0 — only for MAJOR bumps (model upgrade)"
                            bind:value={manualVersion}
                        />
                        <div class="hint">
                            MAJOR bumps are manual-only (schema or model change).
                            Auto only bumps MINOR / PATCH.
                        </div>
                    </div>
                {/if}
            </section>
        </div>
    {/if}

    <div slot="footer" class="footer-stack">
        {#if submitError}
            <div class="submit-err">{submitError}</div>
        {/if}
        <div class="action-row">
            <button type="button" class="btn ghost" onclick={onclose}>
                Cancel
            </button>
            <button
                type="button"
                class="btn armed"
                onclick={onConfirm}
                disabled={submitDisabled}
            >
                {#if submitting}
                    <span class="pulse" aria-hidden="true"></span>
                    <span>Launching</span>
                {:else}
                    <span>Cut</span>
                    <span class="btn-ver">{effectiveVersion || '?'}</span>
                    <span class="btn-arrow" aria-hidden="true">→</span>
                {/if}
            </button>
        </div>
    </div>
</Modal>

<style>
    /* ---------- shells ---------- */
    .state-block {
        padding: var(--s-6);
        font-size: var(--fs-body);
    }
    .state-block.faint { color: var(--text-muted); }
    .state-block.err   { color: var(--state-error-fg); font-family: var(--font-mono); }

    .doc {
        display: flex;
        flex-direction: column;
        gap: var(--s-6);
        padding: var(--s-6) var(--s-8);
        max-width: 880px;
        margin: 0 auto;
    }

    /* ---------- Zone 1 — hero ---------- */
    .hero {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding-bottom: var(--s-4);
        border-bottom: 1px solid var(--border-quiet);
    }
    .version-line {
        display: inline-flex;
        align-items: baseline;
        gap: var(--s-3);
        font-family: var(--font-mono);
        font-size: 26px;
        line-height: 1.1;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.005em;
    }
    .ver-prev   { color: var(--text-muted); }
    .ver-prev.em-dash { color: var(--text-faint); }
    .ver-arrow  { color: var(--text-faint); font-size: 22px; }
    .ver-next {
        color: var(--accent-strong);
        font-weight: 600;
    }
    .ver-next.ver-pending {
        color: var(--state-error-fg);
        font-weight: 500;
    }
    .hero-sub {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        letter-spacing: 0.01em;
    }
    .hero-sub.warn { color: var(--state-error-fg); }
    .hero-sub .mono {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }

    /* ---------- Zone 2 — diff strip ---------- */
    .diff-strip {
        display: inline-flex;
        align-items: baseline;
        gap: var(--s-6);
        font-family: var(--font-mono);
        font-size: var(--fs-body);
        font-variant-numeric: tabular-nums;
    }
    .d {
        display: inline-flex;
        align-items: baseline;
        gap: 6px;
    }
    .d-num { font-weight: 600; }
    .d-add { color: var(--state-published-fg); }
    .d-ref { color: var(--state-error-fg); }
    .d-un  { color: var(--text-muted); }
    .d-label {
        color: var(--text-secondary);
        font-family: var(--font-sans);
        font-size: var(--fs-meta);
    }
    .d-label.faint { color: var(--text-faint); }

    /* ---------- Zone 3 — rendered release ---------- */
    .release-doc {
        display: flex;
        flex-direction: column;
        gap: var(--s-3);
    }
    .acc {
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        background: var(--panel-2);
    }
    .acc > summary {
        cursor: pointer;
        padding: var(--s-2) var(--s-3);
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        user-select: none;
        list-style: none;
    }
    .acc > summary::-webkit-details-marker { display: none; }
    .acc > summary::before {
        content: '▸';
        display: inline-block;
        margin-right: 8px;
        color: var(--text-faint);
        transition: transform var(--t-fast) var(--ease-out-quart);
    }
    .acc[open] > summary::before { transform: rotate(90deg); }
    .acc[open] > summary { border-bottom: 1px solid var(--border-quiet); }

    .member-table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-meta);
    }
    .member-table th {
        text-align: left;
        font-family: var(--font-mono);
        font-weight: 500;
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: var(--text-faint);
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
    }
    .member-table td {
        padding: var(--s-2) var(--s-3);
        border-bottom: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        vertical-align: baseline;
    }
    .member-table tr:last-child td { border-bottom: 0; }
    .mt-id { display: flex; flex-direction: column; gap: 1px; }
    .mt-en { color: var(--text-primary); }
    .mt-ar { color: var(--text-muted); unicode-bidi: isolate; }
    .mt-cov { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .mt-more td {
        color: var(--text-faint);
        font-style: italic;
    }

    .carried {
        margin: 0;
        padding-left: var(--s-1);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .schema-list {
        margin: 0;
        padding: var(--s-3) var(--s-3) var(--s-2) var(--s-6);
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        line-height: 1.5;
    }
    .schema-list code, .schema-refs code {
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-primary);
    }
    .schema-refs {
        margin: 0;
        padding: 0 var(--s-3) var(--s-3) var(--s-3);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .release-foot {
        display: flex;
        align-items: baseline;
        gap: var(--s-4);
        flex-wrap: wrap;
        padding-top: var(--s-1);
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .release-foot strong { color: var(--text-secondary); font-weight: 500; }
    .release-foot a { color: var(--accent); text-decoration: none; }
    .release-foot a:hover { color: var(--accent-strong); text-decoration: underline; }

    /* ---------- Zone 4 — inputs ---------- */
    .inputs {
        display: flex;
        flex-direction: column;
        gap: var(--s-5);
    }
    .field {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .field-label {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-faint);
        font-weight: 500;
    }
    .field-label .faint    { color: var(--text-faint); text-transform: none; letter-spacing: 0; }
    .field-label .required {
        margin-left: 6px;
        color: var(--state-error-fg);
        text-transform: none;
        letter-spacing: 0;
        font-family: var(--font-mono);
    }
    .field textarea,
    .field input {
        border: 0;
        border-bottom: 1px solid var(--border-quiet);
        border-radius: 0;
        padding: 6px 0;
        background: transparent;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        resize: vertical;
        transition: border-bottom-color var(--t-fast);
    }
    .field textarea { font-family: var(--font-sans); }
    .field input    { font-family: var(--font-mono); }
    .field textarea::placeholder,
    .field input::placeholder { color: var(--text-faint); }
    .field textarea:focus,
    .field input:focus {
        outline: none;
        border-bottom-color: var(--accent);
    }
    .field-required input {
        border-bottom-color: var(--state-error-fg);
    }
    .field-required input:focus {
        border-bottom-color: var(--accent);
    }
    .hint {
        font-size: var(--fs-meta);
        color: var(--text-faint);
        line-height: 1.5;
    }

    /* ---------- Zone 5 — footer ---------- */
    .footer-stack {
        width: 100%;
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
    }
    .submit-err {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
        line-height: 1.4;
    }
    .action-row {
        display: flex;
        justify-content: flex-end;
        gap: var(--s-2);
    }
    .btn {
        font: inherit;
        font-size: var(--fs-body);
        padding: 6px 14px;
        border-radius: var(--r-1);
        cursor: pointer;
        white-space: nowrap;
        transition: border-color var(--t-fast),
                    color var(--t-fast),
                    background-color var(--t-fast);
        display: inline-flex;
        align-items: center;
        gap: 8px;
    }
    .btn.ghost {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
    }
    .btn.ghost:hover {
        border-color: var(--border-default);
        color: var(--text-primary);
    }
    .btn.armed {
        background: var(--accent-tint);
        border: 1px solid var(--accent);
        color: var(--accent-strong);
    }
    .btn.armed:hover:not(:disabled) {
        background: oklch(0.785 0.130 220 / 0.22);
        border-color: var(--accent-strong);
    }
    .btn.armed:disabled {
        background: transparent;
        border-color: var(--border-quiet);
        color: var(--text-faint);
        cursor: not-allowed;
    }
    .btn-ver {
        font-family: var(--font-mono);
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }
    .btn-arrow { font-family: var(--font-mono); color: inherit; opacity: 0.8; }
    .pulse {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: currentColor;
        animation: pulse var(--t-slow) ease-in-out infinite;
        margin-right: 2px;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1;    transform: scale(1); }
        50%      { opacity: 0.35; transform: scale(0.85); }
    }
</style>
