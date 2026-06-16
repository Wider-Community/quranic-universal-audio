<script lang="ts">
    /**
     * TsFlaggedAccordion — permanent "Flagged issues" accordion on the
     * Timestamps tab. Sibling of `TsValidationPanel` (low-confidence verses);
     * lists the verses users have reported via the footer Report button as
     * compact pills with a comment-count badge. Clicking a pill jumps the
     * cascade to that verse (same `onselect` contract as the validation panel);
     * the comments themselves are read/added via the footer Report button.
     *
     * Public data — shown to everyone. Hidden entirely when nothing is flagged.
     */
    import type { TsFlagVerseCount } from '../../../lib/types/generated/schemas';

    let {
        flags,
        activeVerse = '',
        onselect,
    }: {
        flags: TsFlagVerseCount[];
        activeVerse?: string;
        onselect: (_verseKey: string) => void;
    } = $props();

    let open = $state(false);
    const total = $derived(flags.reduce((sum, f) => sum + f.count, 0));
</script>

{#if flags.length}
    <details class="tsval flagged" bind:open>
        <summary>
            Flagged issues
            <span class="count">{total}</span>
        </summary>
        <div class="rows">
            <div class="beam-row">
                {#each flags as f (f.verse_key)}
                    <button
                        type="button"
                        class="chip"
                        class:active={f.verse_key === activeVerse}
                        aria-label={`Jump to flagged verse ${f.verse_key} (${f.count} ${f.count === 1 ? 'report' : 'reports'})`}
                        onclick={() => onselect(f.verse_key)}
                    >
                        {f.verse_key}
                        {#if f.count > 1}<span class="chip-count">{f.count}</span>{/if}
                    </button>
                {/each}
            </div>
        </div>
    </details>
{/if}

<style>
    .tsval {
        --severity-color: hsl(38 92% 52%);
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
        background: color-mix(in srgb, var(--severity-color) 22%, var(--panel));
        color: var(--text-secondary);
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
        display: inline-flex;
        align-items: center;
        gap: 4px;
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
    .chip-count {
        font-size: 9px;
        padding: 0 5px;
        border-radius: 999px;
        background: color-mix(in srgb, var(--severity-color) 40%, var(--panel));
        color: var(--text-secondary);
    }
</style>
