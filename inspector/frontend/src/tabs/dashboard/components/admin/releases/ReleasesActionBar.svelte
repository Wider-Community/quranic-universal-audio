<script lang="ts">
    /**
     * Sticky selection action bar for the Releases tab.
     *
     * Appears at the bottom of the compartment when one or more publishable
     * rows are selected. Publishing always goes through here (a single
     * selection is just a batch of one) — there are no per-row publish buttons.
     * Gated by ``release.publish_hf``.
     */
    import { can } from '../../../../../lib/stores/capabilities';

    interface Props {
        count: number;
        /** Total publishable rows currently visible, for "Select all". */
        selectableCount: number;
        busy?: boolean;
        error?: string | null;
        onPublish: () => void;
        onSelectAll: () => void;
        onClear: () => void;
    }
    let { count, selectableCount, busy = false, error = null,
          onPublish, onSelectAll, onClear }: Props = $props();

    const canPublish = can('release.publish_hf');
    const allSelected = $derived(count >= selectableCount && selectableCount > 0);
</script>

{#if count > 0 && $canPublish}
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
        <button class="publish" type="button" onclick={onPublish} disabled={busy}>
            {busy ? 'Launching…' : `Publish ${count} to HF`}
        </button>
    </div>
{/if}

<style>
    .action-bar {
        position: sticky;
        bottom: 0;
        z-index: 2;
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3) var(--s-4);
        margin-top: var(--s-2);
        background: var(--panel-2);
        border: 1px solid var(--accent-tint);
        border-radius: var(--r-2);
        box-shadow: 0 -4px 16px oklch(0.13 0.034 285 / 0.4);
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
