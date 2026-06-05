<script lang="ts">
    /**
     * Cut-release dry-run document.
     *
     * Reads top-to-bottom like the output of `release cut --dry-run`:
     *   1. Version transition hero
     *   2. Diff strip
     *   3. Read-only rendered release Markdown
     *   4. Owner-only manual version override
     *   5. Action footer
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

    async function onConfirm(): Promise<void> {
        if (submitDisabled || !preview) return;
        submitting = true;
        submitError = null;
        try {
            await cutRelease({
                version: manualVersion.trim() || undefined,
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

            <section class="release-preview" aria-label="Release body preview">
                <pre>{preview.changelog_preview_md}</pre>
            </section>

            {#if $isOwner}
                <section class="inputs">
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
                </section>
            {/if}
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
    .release-preview {
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        background: var(--panel-2);
        max-height: min(56vh, 620px);
        overflow: auto;
    }
    .release-preview pre {
        margin: 0;
        padding: var(--s-4);
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        line-height: 1.55;
        color: var(--text-secondary);
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

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
    .field input {
        border: 0;
        border-bottom: 1px solid var(--border-quiet);
        border-radius: 0;
        padding: 6px 0;
        background: transparent;
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-body);
        transition: border-bottom-color var(--t-fast);
    }
    .field input    { font-family: var(--font-mono); }
    .field input::placeholder { color: var(--text-faint); }
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
