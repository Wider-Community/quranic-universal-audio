<script lang="ts">
    /**
     * TsValidationPanel — verse-level ts-validation accordion (owner preview).
     *
     * The verse-level analogue of the Segments tab's "Low Confidence v2"
     * accordion. Shows compact verse chips grouped by highest failed beam.
     * Clicking a verse jumps the cascade to it so the owner can inspect the
     * alignment on the waveform. Hidden entirely when there are no flags.
     *
     * Decoupled from the Segments ValidationPanel (which is segments-store /
     * IssueRegistry coupled) — this only needs the sidecar doc + a select cb.
     */
    import type { TsValidationDoc } from '../../../lib/types/generated/schemas';
    import { groupTsValidationVerses } from '../utils/validation-groups';

    let {
        doc,
        activeVerse = '',
        onselect,
    }: {
        doc: TsValidationDoc | null;
        activeVerse?: string;
        onselect: (_verseKey: string) => void;
    } = $props();

    let open = $state(false);

    const groups = $derived(groupTsValidationVerses(doc));
    const total = $derived(groups.reduce((sum, group) => sum + group.refs.length, 0));
    const groupKey = $derived(groups.map((group) => `${group.beam}:${group.refs.join(',')}`).join('|'));

    $effect(() => {
        groupKey;
        open = false;
    });

    function severityColor(index: number, count: number): string {
        if (count <= 1) return 'hsl(2 76% 53%)';
        const t = index / (count - 1);
        const hue = 2 + (44 - 2) * t;
        const saturation = 76 + (88 - 76) * t;
        const lightness = 53 - (53 - 50) * t;
        return `hsl(${hue} ${saturation}% ${lightness}%)`;
    }
</script>

{#if groups.length}
    <details class="tsval" bind:open>
        <summary>
            Low-confidence verses
            <span class="count">{total}</span>
        </summary>
        <div class="rows">
            {#each groups as group, i (group.beam)}
                <div class="beam-row" style:--severity-color={severityColor(i, groups.length)}>
                    {#each group.refs as ref (ref)}
                    <button
                        type="button"
                        class="chip"
                        class:active={ref === activeVerse}
                        aria-label={`Jump to low-confidence verse ${ref}`}
                        onclick={() => onselect(ref)}
                    >
                        {ref}
                    </button>
                    {/each}
                </div>
            {/each}
        </div>
    </details>
{/if}

<style>
    .tsval {
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        background: var(--panel-2);
        font-size: var(--fs-meta);
        width: 100%;
    }
    .tsval > summary {
        cursor: pointer;
        padding: 7px 10px;
        font-family: var(--font-mono);
        font-size: 10.5px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--text-faint);
        display: flex;
        align-items: center;
        gap: var(--s-2);
        user-select: none;
    }
    .count {
        font-family: var(--font-mono);
        font-size: 9.5px;
        border-radius: 999px;
        padding: 1px 7px;
        background: var(--state-error-bg, var(--panel));
        color: var(--state-error-fg, var(--text-secondary));
    }
    .rows {
        display: flex;
        flex-direction: column;
        gap: 5px;
        max-height: 180px;
        overflow: auto;
        padding: 4px 8px 8px;
    }
    .beam-row {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        padding: 2px 0 2px 8px;
        border-left: 3px solid var(--severity-color);
    }
    .chip {
        display: flex;
        align-items: center;
        justify-content: center;
        min-width: 46px;
        min-height: 24px;
        background: color-mix(in srgb, var(--severity-color) 14%, var(--panel));
        border: 1px solid color-mix(in srgb, var(--severity-color) 54%, var(--border-quiet));
        border-radius: var(--r-1);
        padding: 3px 8px;
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: 11px;
        color: var(--text-primary);
        line-height: 1;
    }
    .chip:hover {
        background: color-mix(in srgb, var(--severity-color) 24%, var(--panel));
        border-color: var(--severity-color);
    }
    .chip.active {
        background: color-mix(in srgb, var(--severity-color) 28%, var(--panel));
        border-color: var(--accent);
        box-shadow: inset 0 0 0 1px var(--accent);
    }
</style>
