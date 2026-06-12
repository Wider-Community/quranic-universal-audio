<script lang="ts">
    /**
     * Unified timestamps generate / regenerate settings — the in-row expand.
     *
     * One compact control for BOTH first generation (Ready-to-generate rows,
     * ``row.ts === null``) and regeneration (any row with existing timestamps).
     * Inputs default to main beam 50 + probe 2; Advanced (workers / flavor /
     * timeout) folds open on demand. When the row's timestamps are behind
     * specific chapters (``ts.affected_chapters``) the Full-vs-Affected scope
     * chooser folds in inline — no separate modal.
     *
     * Launches via the shared ``generateTimestamps`` route (same endpoint for
     * gen + regen); the parent switches the row's expansion to "Past jobs" on
     * success so the live log is immediately visible.
     */
    import {
        generateTimestamps,
        fetchAlignerModels,
        type TimestampsJobSettings,
        type AlignerModel,
    } from '../../../../../lib/api/admin-reviews';
    import type { ReleaseStatusRow } from '../../../../../lib/api/admin-releases';
    import { surahOptionText } from '../../../../../lib/utils/surah-info';

    interface Props {
        row: ReleaseStatusRow;
        /** Fired with the launched job id after a successful launch. */
        onlaunched: (_jobId: string) => void;
    }
    let { row, onlaunched }: Props = $props();

    const isRegen = $derived(row.ts !== null);
    const affected = $derived(row.ts?.affected_chapters ?? []);
    const hasAffected = $derived(affected.length > 0);

    // form state — defaults: beam 50, probe 2.
    let beam = $state(50);
    let probe = $state(2);
    // acoustic model — null until the catalog loads, then the store default.
    let models = $state<AlignerModel[]>([]);
    let modelId = $state<string | null>(null);
    $effect(() => {
        fetchAlignerModels()
            .then((ms) => {
                models = ms;
                modelId = ms.find((m) => m.default)?.id ?? ms[0]?.id ?? null;
            })
            .catch(() => {});
    });
    let scope = $state<'affected' | 'full'>('affected');
    let advancedOpen = $state(false);
    let workers = $state<number | null>(null);
    let flavor = $state('');
    let timeout = $state('');

    let launching = $state(false);
    let formError = $state<string | null>(null);

    const buttonLabel = $derived.by(() => {
        if (launching) return 'Launching…';
        if (!isRegen) return 'Generate timestamps';
        if (hasAffected && scope === 'affected') {
            return `Regenerate ${affected.length} chapter${affected.length === 1 ? '' : 's'}`;
        }
        return 'Regenerate full';
    });

    function affectedText(): string {
        return affected.map((c) => surahOptionText(c)).join(', ');
    }

    async function launch(): Promise<void> {
        if (launching) return;
        formError = null;
        if (!Number.isInteger(beam) || beam <= 0) {
            formError = 'beam must be a positive integer';
            return;
        }
        const probeBeams = Number.isInteger(probe) && probe > 0 ? [probe] : [];
        const chapters =
            isRegen && hasAffected && scope === 'affected' ? affected : undefined;
        const settings: TimestampsJobSettings = {
            beam,
            probe_beams: probeBeams,
            aligner_model: modelId,
            chapters: chapters ?? null,
            workers: advancedOpen ? workers : null,
            flavor: advancedOpen && flavor.trim() ? flavor.trim() : null,
            timeout: advancedOpen && timeout.trim() ? timeout.trim() : null,
        };
        launching = true;
        try {
            const { job_id } = await generateTimestamps(row.slug, settings);
            onlaunched(job_id);
        } catch (e) {
            formError = (e as Error).message ?? 'Launch failed';
        } finally {
            launching = false;
        }
    }
</script>

<div class="ts-settings">
    <div class="beam-row">
        {#if models.length > 1}
            <label class="field wide">
                <span class="lbl">model</span>
                <select bind:value={modelId}>
                    {#each models as m (m.id)}
                        <option value={m.id}>{m.label}{m.default ? ' (default)' : ''}</option>
                    {/each}
                </select>
            </label>
        {/if}
        <label class="field">
            <span class="lbl">beam</span>
            <input type="number" min="1" bind:value={beam} />
        </label>
        <label class="field">
            <span class="lbl">probe</span>
            <input type="number" min="0" bind:value={probe} />
        </label>
        <button class="adv-toggle" type="button" onclick={() => (advancedOpen = !advancedOpen)}>
            {advancedOpen ? '− Advanced' : '+ Advanced'}
        </button>
        <span class="spacer"></span>
        <button class="launch" type="button" onclick={launch} disabled={launching}>
            {buttonLabel}
        </button>
    </div>

    {#if isRegen && hasAffected}
        <div class="scope-row">
            <label class="radio" class:active={scope === 'affected'}>
                <input type="radio" value="affected" bind:group={scope} />
                <span>Affected only</span>
            </label>
            <label class="radio" class:active={scope === 'full'}>
                <input type="radio" value="full" bind:group={scope} />
                <span>Full reciter</span>
            </label>
            <span class="affected-chips" class:dim={scope !== 'affected'}>{affectedText()}</span>
        </div>
    {/if}

    {#if advancedOpen}
        <div class="adv-row">
            <label class="field">
                <span class="lbl">workers</span>
                <input type="number" min="1" max="64" bind:value={workers} placeholder="auto" />
            </label>
            <label class="field wide">
                <span class="lbl">flavor</span>
                <input type="text" bind:value={flavor} placeholder="cpu-upgrade" />
            </label>
            <label class="field">
                <span class="lbl">timeout</span>
                <input type="text" bind:value={timeout} placeholder="2h" />
            </label>
        </div>
    {/if}

    {#if formError}
        <div class="form-err" role="alert">{formError}</div>
    {/if}
</div>

<style>
    .ts-settings {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        padding: var(--s-2) var(--s-1);
    }
    .beam-row,
    .scope-row,
    .adv-row {
        display: flex;
        align-items: center;
        gap: var(--s-3);
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
    }
    .field input {
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 3px 6px;
        width: 56px;
    }
    .field.wide input { width: 110px; }
    .field input:focus { outline: 0; border-color: var(--accent-tint); }
    .field select {
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
        padding: 3px 6px;
        max-width: 200px;
    }
    .field select:focus { outline: 0; border-color: var(--accent-tint); }

    .adv-toggle {
        background: transparent;
        border: 0;
        color: var(--text-muted);
        font: inherit;
        font-size: 11px;
        cursor: pointer;
        padding: 0;
    }
    .adv-toggle:hover { color: var(--text-primary); }
    .spacer { flex: 1; }

    .launch {
        background: var(--accent-tint-soft);
        border: 1px solid var(--accent);
        color: var(--accent-strong);
        font: inherit;
        font-size: var(--fs-meta);
        font-weight: 500;
        padding: 4px 14px;
        border-radius: var(--r-1);
        cursor: pointer;
        white-space: nowrap;
        transition: background-color var(--t-fast);
    }
    .launch:hover:not(:disabled) { background: var(--accent-tint); }
    .launch:disabled { opacity: 0.5; cursor: not-allowed; }

    .radio {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        cursor: pointer;
    }
    .radio.active { color: var(--text-primary); }
    .radio input { accent-color: var(--accent); margin: 0; }
    .affected-chips {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-muted);
    }
    .affected-chips.dim { opacity: 0.4; }

    .form-err {
        font-size: var(--fs-meta);
        color: var(--state-error-fg);
    }
</style>
