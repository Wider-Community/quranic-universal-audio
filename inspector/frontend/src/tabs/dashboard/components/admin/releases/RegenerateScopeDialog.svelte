<script lang="ts">
    /**
     * RegenerateScopeDialog — choose Full vs Affected-only before re-running
     * MFA alignment for a reciter whose timestamps are behind its segments.
     *
     * Shown only when the row has affected chapters (segments edited since the
     * last generation). Defaults to **Affected-only** (cheaper — the job
     * downloads + aligns just those chapters, untouched shards are preserved);
     * Full re-aligns the whole reciter. ``onlaunch`` receives the chapter list
     * for affected mode, or ``undefined`` for full.
     */
    import Modal from '../../../../../lib/components/Modal.svelte';
    import { surahOptionText } from '../../../../../lib/utils/surah-info';

    interface Props {
        name: string;
        affectedChapters: number[];
        busy?: boolean;
        onclose: () => void;
        onlaunch: (_chapters?: number[]) => void;
    }
    let { name, affectedChapters, busy = false, onclose, onlaunch }: Props = $props();

    let scope = $state<'affected' | 'full'>('affected');

    function launch(): void {
        if (busy) return;
        onlaunch(scope === 'affected' ? affectedChapters : undefined);
    }
</script>

<Modal open={true} size="narrow" title="Regenerate timestamps" on:close={onclose}>
    <div class="scope">
        <p class="lead">
            <strong>{name}</strong>'s timestamps are behind its segments.
            {affectedChapters.length} chapter{affectedChapters.length === 1 ? '' : 's'}
            edited since the last generation.
        </p>

        <label class="opt" class:active={scope === 'affected'}>
            <input type="radio" value="affected" bind:group={scope} />
            <span class="opt-body">
                <span class="opt-title">Affected chapters only</span>
                <span class="opt-sub">Re-align just the edited chapters — faster; untouched chapters keep their timestamps.</span>
            </span>
        </label>

        <ul class="chips" class:dim={scope !== 'affected'}>
            {#each affectedChapters as ch}
                <li class="chip">{surahOptionText(ch)}</li>
            {/each}
        </ul>

        <label class="opt" class:active={scope === 'full'}>
            <input type="radio" value="full" bind:group={scope} />
            <span class="opt-body">
                <span class="opt-title">Full reciter</span>
                <span class="opt-sub">Re-align all 114 chapters. Slower; use when edits aren't localized.</span>
            </span>
        </label>

        <p class="note">Either way the reciter stays released and its HF/GH releases are flagged stale — re-publish afterwards.</p>
    </div>

    <svelte:fragment slot="footer">
        <button type="button" class="btn" onclick={onclose} disabled={busy}>Cancel</button>
        <button type="button" class="btn btn-primary" onclick={launch} disabled={busy}>
            {busy ? 'Launching…' : scope === 'affected' ? `Regenerate ${affectedChapters.length} chapter${affectedChapters.length === 1 ? '' : 's'}` : 'Regenerate full'}
        </button>
    </svelte:fragment>
</Modal>

<style>
    .scope { padding: var(--s-5) var(--s-6); display: flex; flex-direction: column; gap: var(--s-3); }
    .lead { margin: 0 0 var(--s-1); font-size: var(--fs-body); color: var(--text-secondary); }
    .opt {
        display: flex;
        gap: var(--s-3);
        padding: var(--s-3);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .opt.active { border-color: var(--accent); background: var(--accent-tint-soft); }
    .opt input { margin-top: 3px; accent-color: var(--accent); }
    .opt-body { display: flex; flex-direction: column; gap: 2px; }
    .opt-title { font-size: var(--fs-body); color: var(--text-primary); }
    .opt-sub { font-size: var(--fs-meta); color: var(--text-muted); }
    .chips { list-style: none; margin: 0; padding: 0 0 0 var(--s-2); display: flex; flex-wrap: wrap; gap: var(--s-2); }
    .chips.dim { opacity: 0.4; }
    .chip {
        font-size: var(--fs-meta);
        font-family: var(--font-mono);
        padding: 2px 8px;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        color: var(--text-secondary);
    }
    .note { margin: var(--s-1) 0 0; font-size: var(--fs-meta); color: var(--text-faint); }
    .btn {
        background: transparent;
        border: 1px solid var(--border-quiet);
        color: var(--text-secondary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 6px 14px;
        border-radius: var(--r-1);
        cursor: pointer;
    }
    .btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent-strong); }
    .btn-primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent, #fff); }
    .btn-primary:hover:not(:disabled) { background: var(--accent-strong); border-color: var(--accent-strong); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
