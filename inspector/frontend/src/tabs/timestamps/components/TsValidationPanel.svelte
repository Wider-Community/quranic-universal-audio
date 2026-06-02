<script lang="ts">
    /**
     * TsValidationPanel — verse-level ts-validation accordion (owner preview).
     *
     * The verse-level analogue of the Segments tab's "Low Confidence v2"
     * accordion. Lists verses the multi-beam generate-timestamps job flagged
     * (aligned under the canonical beam but failed under a tighter probe beam).
     * Clicking a verse jumps the cascade to it so the owner can inspect the
     * alignment on the waveform. Hidden entirely when there are no flags.
     *
     * Decoupled from the Segments ValidationPanel (which is segments-store /
     * IssueRegistry coupled) — this only needs the sidecar doc + a select cb.
     */
    import type { TsValidationDoc, TsValidationVerse } from '../../../lib/types/generated/schemas';

    let {
        doc,
        activeVerse = '',
        onselect,
    }: {
        doc: TsValidationDoc | null;
        activeVerse?: string;
        onselect: (verseKey: string) => void;
    } = $props();

    let open = $state(true);

    /** Numeric surah:ayah[:word…] compare so 2:7 sorts before 2:10. */
    function cmpRef(a: string, b: string): number {
        const pa = a.split(/[:-]/).map((n) => parseInt(n, 10) || 0);
        const pb = b.split(/[:-]/).map((n) => parseInt(n, 10) || 0);
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
            const d = (pa[i] ?? 0) - (pb[i] ?? 0);
            if (d) return d;
        }
        return 0;
    }

    const entries = $derived.by(() => {
        const verses = doc?.verses ?? {};
        return Object.entries(verses)
            .map(([ref, flag]) => ({ ref, flag: flag as TsValidationVerse }))
            .sort((a, b) => cmpRef(a.ref, b.ref));
    });

    function summary(flag: TsValidationVerse): string {
        const failed = flag?.failed_beams ?? [];
        const minPass = flag?.min_passing_beam ?? null;
        const failTxt = failed.length ? `fails @ beam ${failed.join(', ')}` : '';
        const okTxt = minPass != null ? `ok from ${minPass}` : 'never aligned';
        return [failTxt, okTxt].filter(Boolean).join(' · ');
    }
</script>

{#if entries.length}
    <details class="tsval" bind:open>
        <summary>
            Low-confidence verses
            <span class="count">{entries.length}</span>
        </summary>
        <ul>
            {#each entries as e (e.ref)}
                <li>
                    <button
                        type="button"
                        class="row"
                        class:active={e.ref === activeVerse}
                        onclick={() => onselect(e.ref)}
                    >
                        <span class="ref">{e.ref}</span>
                        <span class="sum">{summary(e.flag)}</span>
                    </button>
                </li>
            {/each}
        </ul>
    </details>
{/if}

<style>
    .tsval {
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        background: var(--panel-2);
        font-size: var(--fs-meta);
    }
    .tsval > summary {
        cursor: pointer;
        padding: 6px 10px;
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
    ul { list-style: none; margin: 0; padding: 4px; display: flex; flex-direction: column; gap: 2px; max-height: 260px; overflow: auto; }
    .row {
        display: flex;
        align-items: baseline;
        gap: var(--s-3);
        width: 100%;
        text-align: left;
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-1);
        padding: 4px 8px;
        cursor: pointer;
        font: inherit;
        color: var(--text-secondary);
    }
    .row:hover { background: var(--panel); border-color: var(--border-quiet); }
    .row.active { border-color: var(--accent); }
    .ref { font-family: var(--font-mono); font-size: 11px; color: var(--text-primary); white-space: nowrap; }
    .sum { font-size: 10.5px; color: var(--text-muted); }
</style>
