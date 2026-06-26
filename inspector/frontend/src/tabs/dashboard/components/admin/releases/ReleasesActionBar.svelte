<script lang="ts">
    /**
     * Sticky selection action bar for the Releases tab.
     *
     * Appears at the bottom of the compartment when one or more publishable
     * rows are selected. Publishing always goes through here (a single
     * selection is just a batch of one) — there are no per-row publish buttons.
     * Gated by ``release.publish_hf``.
     *
     * Includes a collapsible "Dataset publishing settings" accordion that exposes
     * the pad_start / pad_end / min_gap knobs forwarded to the publish API.
     */
    import { can } from '../../../../../lib/stores/capabilities';

    interface Props {
        count: number;
        /** Total publishable rows currently visible, for "Select all". */
        selectableCount: number;
        busy?: boolean;
        error?: string | null;
        onPublish: (settings: { pad_start: number; pad_end: number; min_gap: number }) => void;
        onSelectAll: () => void;
        onClear: () => void;
    }
    let { count, selectableCount, busy = false, error = null,
          onPublish, onSelectAll, onClear }: Props = $props();

    const canPublish = can('release.publish_hf');
    const allSelected = $derived(count >= selectableCount && selectableCount > 0);

    // Dataset publishing settings state — mirrors the server-side defaults.
    let settingsOpen = $state(false);
    let padStart = $state(100);
    let padEnd = $state(300);
    let minGap = $state(100);

    function handlePublish(): void {
        onPublish({ pad_start: padStart, pad_end: padEnd, min_gap: minGap });
    }
</script>

{#if count > 0 && $canPublish}
    <div class="action-bar-wrap">
        {#if settingsOpen}
            <div class="pub-settings" role="group" aria-label="Dataset publishing settings">
                <div class="settings-row">
                    <label class="field">
                        <span class="lbl">pad start (ms)</span>
                        <input type="number" min="0" bind:value={padStart} />
                    </label>
                    <label class="field">
                        <span class="lbl">pad end (ms)</span>
                        <input type="number" min="0" bind:value={padEnd} />
                    </label>
                    <label class="field">
                        <span class="lbl">min gap (ms)</span>
                        <input type="number" min="0" bind:value={minGap} />
                    </label>
                    <span class="settings-hint">Audio headroom added before/after each verse clip; minimum silence kept between adjacent clips.</span>
                </div>
            </div>
        {/if}
        <div class="action-bar" role="region" aria-label="Batch publish">
            {#if error}
                <span class="bar-err" role="alert">{error}</span>
            {/if}
            <span class="count"><strong>{count}</strong> selected</span>
            {#if !allSelected}
                <button class="link" type="button" onclick={onSelectAll}>
                    Select all {selectableCount}
                </button>
            {/if}
            <button class="link" type="button" onclick={onClear}>Clear</button>
            <button
                class="settings-toggle"
                class:active={settingsOpen}
                type="button"
                onclick={() => (settingsOpen = !settingsOpen)}
                aria-expanded={settingsOpen}
                aria-controls="pub-settings-panel"
            >
                {settingsOpen ? '− Publishing settings' : '+ Publishing settings'}
            </button>
            <button class="publish" type="button" onclick={handlePublish} disabled={busy}>
                {busy ? 'Launching…' : `Publish ${count} to HF`}
            </button>
        </div>
    </div>
{/if}

<style>
    .action-bar-wrap {
        position: sticky;
        bottom: 0;
        z-index: 2;
        display: flex;
        flex-direction: column;
        margin-top: var(--s-2);
    }
    .pub-settings {
        background: var(--panel-2);
        border: 1px solid var(--accent-tint);
        border-bottom: 0;
        border-radius: var(--r-2) var(--r-2) 0 0;
        padding: var(--s-3) var(--s-4);
    }
    .settings-row {
        display: flex;
        align-items: center;
        gap: var(--s-4);
        flex-wrap: wrap;
    }
    .field {
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .field .lbl {
        font-family: var(--font-mono);
        font-size: 10px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--text-faint);
        white-space: nowrap;
    }
    .field input {
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 3px 6px;
        width: 64px;
    }
    .field input:focus { outline: 0; border-color: var(--accent-tint); }
    .settings-hint {
        font-size: 10.5px;
        color: var(--text-faint);
        line-height: 1.4;
        max-width: 36ch;
    }
    .action-bar {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-4);
        background: var(--panel-2);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        box-shadow: 0 -4px 16px oklch(0.13 0.034 285 / 0.4);
    }
    /* When settings panel is open, square off the top corners of the bar */
    .pub-settings + .action-bar {
        border-top: 1px solid var(--border-quiet);
        border-radius: 0 0 var(--r-2) var(--r-2);
    }
    .count {
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .count strong {
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
    }
    .link {
        background: transparent;
        border: 0;
        color: var(--accent);
        font: inherit;
        font-size: var(--fs-meta);
        cursor: pointer;
        padding: 0;
    }
    .link:hover { color: var(--accent-strong); text-decoration: underline; }
    .bar-err {
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
        margin-right: auto;
    }
    .settings-toggle {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
        padding: 0;
    }
    .settings-toggle:hover { color: var(--text-primary); }
    .settings-toggle.active { color: var(--accent); }
    .publish {
        margin-left: auto;
        background: var(--accent);
        color: var(--accent-fg);
        border: 0;
        padding: 7px 16px;
        border-radius: var(--r-2);
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
        transition: background var(--t-fast) var(--ease-out-quart);
    }
    .publish:hover:not(:disabled) { background: var(--accent-strong); }
    .publish:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
