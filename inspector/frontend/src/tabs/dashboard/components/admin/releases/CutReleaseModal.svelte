<script lang="ts">
    /**
     * Two-step preview → confirm modal for cutting a global GH release.
     *
     * Step 1: shows the auto-computed version + diff (added / refreshed) +
     * rendered CHANGELOG preview. If the preview comes back with
     * ``needs_manual_version`` (nothing has changed since the previous
     * release), the version field is required and there's no fallback.
     *
     * Step 2 (confirm): owner enters optional operator_note + an optional
     * manual version override, then submits. The server validates the
     * echoed ``expected_version_at_preview`` to catch a preview-then-TS-regen
     * race (409 → caller re-previews).
     *
     * Owner-only by capability gate at the route layer; the FE still relies
     * on ``isOwner`` for the chrome since the manual-override field is
     * owner-only (maintainers could in principle hold ``release.cut_gh``
     * but the convention keeps the field owner-gated).
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

    let operatorNote = $state('');
    let manualVersion = $state('');

    async function loadPreview(): Promise<void> {
        loading = true;
        error = null;
        try {
            preview = await fetchReleasePreview();
            // Pre-fill the manual-version field when an override is required.
            if (preview.needs_manual_version) {
                manualVersion = '';
            }
        } catch (e) {
            error = (e as Error).message ?? 'Failed to load preview';
        } finally {
            loading = false;
        }
    }

    $effect(() => {
        void loadPreview();
    });

    // The submit button is disabled until either the preview gave us a
    // computed version OR the operator typed an override that looks like vX.Y.Z.
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
                operator_note: operatorNote.trim() || undefined,
                expected_version_at_preview: preview.expected_version_at_preview,
            });
            onsuccess();
        } catch (e) {
            const msg = (e as Error).message ?? 'Cut failed';
            // 409 on drift → tell operator to re-preview.
            submitError = msg.includes('drift') || msg.includes('preview')
                ? `${msg} — please re-open the modal to refresh the preview.`
                : msg;
        } finally {
            submitting = false;
        }
    }
</script>

<Modal open={true} size="wide" title="Cut new release" elevated on:close={onclose}>
    {#if loading}
        <div class="cm-loading">Computing release preview…</div>
    {:else if error}
        <div class="cm-error">{error}</div>
    {:else if preview}
        <div class="cm-pane">
            <div class="cm-row">
                <div class="cm-label">Previous release</div>
                <div class="cm-value">
                    {preview.previous_version ?? '— (this would be v0.1.0)'}
                </div>
            </div>
            <div class="cm-row">
                <div class="cm-label">Auto-computed version</div>
                <div class="cm-value">
                    {#if preview.computed_version}
                        <strong>{preview.computed_version}</strong>
                    {:else}
                        <span class="cm-warn">
                            No automatic bump (nothing changed since
                            {preview.previous_version ?? 'last release'}).
                            Enter a version below to force-cut.
                        </span>
                    {/if}
                </div>
            </div>
            <div class="cm-row">
                <div class="cm-label">Diff</div>
                <div class="cm-value">
                    <span class="cm-chip cm-chip--add">
                        +{preview.change_counts.added} added
                    </span>
                    <span class="cm-chip cm-chip--ref">
                        ~{preview.change_counts.refresh} refreshed
                    </span>
                    <span class="cm-chip cm-chip--un">
                        ·{preview.change_counts.unchanged} unchanged
                    </span>
                </div>
            </div>

            <h4 class="cm-subhead">CHANGELOG preview</h4>
            <pre class="cm-changelog">{preview.changelog_preview_md}</pre>

            <div class="cm-row cm-row--input">
                <label class="cm-label" for="cm-note">
                    Operator note <span class="cm-faint">(optional)</span>
                </label>
                <textarea
                    id="cm-note"
                    rows="3"
                    placeholder="e.g. MFA model upgraded to v3 — all recitations refreshed"
                    bind:value={operatorNote}
                ></textarea>
            </div>

            {#if $isOwner}
                <div class="cm-row cm-row--input">
                    <label class="cm-label" for="cm-version">
                        Manual version override
                        {#if preview.needs_manual_version}
                            <span class="cm-required">required</span>
                        {:else}
                            <span class="cm-faint">(owner-only)</span>
                        {/if}
                    </label>
                    <input
                        id="cm-version"
                        type="text"
                        placeholder="e.g. v1.0.0 — only for MAJOR bumps (model upgrade)"
                        bind:value={manualVersion}
                    />
                    <div class="cm-hint">
                        Plan: MAJOR bumps are manual-only (schema or model change).
                        Auto only bumps MINOR/PATCH.
                    </div>
                </div>
            {/if}

            {#if submitError}
                <div class="cm-error">{submitError}</div>
            {/if}

            <footer class="cm-footer">
                <span class="cm-resolved">
                    Will cut as <strong>{effectiveVersion || '?'}</strong>
                </span>
                <div class="cm-btn-row">
                    <button type="button" class="cm-btn-secondary" onclick={onclose}>
                        Cancel
                    </button>
                    <button
                        type="button"
                        class="cm-btn-primary"
                        onclick={onConfirm}
                        disabled={submitDisabled}
                    >
                        {submitting ? 'Launching…' : 'Cut release'}
                    </button>
                </div>
            </footer>
        </div>
    {/if}
</Modal>

<style>
    .cm-loading, .cm-error {
        padding: var(--s-3); color: var(--text-secondary);
    }
    .cm-error { color: var(--accent-danger, #c0392b); }
    .cm-pane { display: flex; flex-direction: column; gap: var(--s-2); }
    .cm-row { display: flex; align-items: flex-start; gap: var(--s-3); }
    .cm-row--input { flex-direction: column; align-items: stretch; }
    .cm-label { min-width: 180px; color: var(--text-secondary); font-size: var(--fs-body); }
    .cm-value { flex: 1; color: var(--text-primary); font-size: var(--fs-body); }
    .cm-warn { color: #b85d00; }
    .cm-faint { color: var(--text-faint); }
    .cm-required { color: var(--accent-danger, #c0392b); font-size: var(--fs-small); margin-left: 4px; }
    .cm-chip {
        display: inline-block; padding: 1px 6px; margin-right: 4px;
        font-family: var(--font-mono); font-size: var(--fs-small);
        border-radius: 3px;
    }
    .cm-chip--add { background: #d4edda; color: #155724; }
    .cm-chip--ref { background: #fff3cd; color: #856404; }
    .cm-chip--un { background: var(--surface-2); color: var(--text-secondary); }
    .cm-subhead { margin: var(--s-2) 0 var(--s-1) 0; font-size: var(--fs-h5); color: var(--text-primary); }
    .cm-changelog {
        max-height: 320px; overflow: auto;
        padding: var(--s-2); background: var(--surface-1);
        border: 1px solid var(--border-subtle); border-radius: var(--r-1);
        font-family: var(--font-mono); font-size: var(--fs-small);
        white-space: pre-wrap; color: var(--text-primary);
    }
    .cm-row--input textarea, .cm-row--input input {
        padding: var(--s-1) var(--s-2);
        border: 1px solid var(--border); border-radius: var(--r-1);
        background: var(--surface-1); color: var(--text-primary);
        font-size: var(--fs-body); font-family: inherit;
    }
    .cm-hint { font-size: var(--fs-small); color: var(--text-faint); margin-top: 2px; }
    .cm-footer {
        display: flex; align-items: center; justify-content: space-between;
        margin-top: var(--s-2); padding-top: var(--s-2);
        border-top: 1px solid var(--border-subtle);
    }
    .cm-resolved { color: var(--text-secondary); }
    .cm-resolved strong { font-family: var(--font-mono); color: var(--text-primary); }
    .cm-btn-row { display: flex; gap: var(--s-2); }
    .cm-btn-secondary, .cm-btn-primary {
        padding: var(--s-1) var(--s-3); border-radius: var(--r-1);
        font-size: var(--fs-body); cursor: pointer;
    }
    .cm-btn-secondary {
        background: transparent; color: var(--text-secondary);
        border: 1px solid var(--border);
    }
    .cm-btn-primary {
        background: var(--accent); color: var(--text-on-accent); border: 0;
    }
    .cm-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
