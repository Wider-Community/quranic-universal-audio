<script lang="ts">
    /**
     * Wizard step 3 — combination metadata + comments.
     *
     * Mirrors the per-delivery RequestForm vocab (riwayah / style /
     * recording_context dropdowns + recording_year + comments + auto-claim
     * checkbox) so the contributor surface stays consistent. Vocab is
     * fetched lazily; falling back to whatever raw slug the user typed
     * keeps a bad fetch from blocking the wizard.
     */
    import { fade } from 'svelte/transition';
    import { onMount } from 'svelte';

    import { submitWizard } from '../../stores/submit-wizard';

    const MIN_YEAR = 1885;
    const MAX_YEAR = new Date().getFullYear();

    interface VocabRow { slug: string; name: string; }

    let riwayatOptions: VocabRow[] = [];
    let styleOptions: VocabRow[] = [];
    let contextOptions: VocabRow[] = [];

    $: state = $submitWizard;

    onMount(async () => {
        try {
            const resp = await fetch('/api/static/catalog.json');
            if (!resp.ok) return;
            const cat = await resp.json();
            riwayatOptions = (cat?.vocab?.riwayat ?? []).map((r: VocabRow) => ({ slug: r.slug, name: r.name }));
            styleOptions = (cat?.vocab?.styles ?? []).map((s: VocabRow) => ({ slug: s.slug, name: s.name }));
            contextOptions = (cat?.vocab?.recording_contexts ?? []).map((c: VocabRow) => ({ slug: c.slug, name: c.name }));
        } catch {
            // Best-effort; raw slugs render fine.
        }
    });

    function update<K extends keyof typeof state.combination>(key: K, value: typeof state.combination[K]): void {
        submitWizard.update((s) => ({ ...s, combination: { ...s.combination, [key]: value } }));
    }

    function onYear(e: Event): void {
        const raw = (e.currentTarget as HTMLInputElement).value;
        update('recording_year', raw === '' ? '' : Number(raw));
    }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <p class="lede">A little metadata so we know what we're aligning.</p>

    <div class="grid">
        <label>
            <span>Riwayah</span>
            <select
                value={state.combination.riwayah}
                on:change={(e) => update('riwayah', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="" disabled>Pick one…</option>
                {#each riwayatOptions as r (r.slug)}
                    <option value={r.slug}>{r.name}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>Style</span>
            <select
                value={state.combination.style}
                on:change={(e) => update('style', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="" disabled>Pick one…</option>
                {#each styleOptions as s (s.slug)}
                    <option value={s.slug}>{s.name}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>Recording context <span class="hint">optional</span></span>
            <select
                value={state.combination.recording_context}
                on:change={(e) => update('recording_context', (e.currentTarget as HTMLSelectElement).value)}
            >
                <option value="">—</option>
                {#each contextOptions as c (c.slug)}
                    <option value={c.slug}>{c.name}</option>
                {/each}
            </select>
        </label>

        <label>
            <span>Recording year <span class="hint">optional</span></span>
            <input
                type="number"
                min={MIN_YEAR}
                max={MAX_YEAR}
                placeholder="—"
                value={state.combination.recording_year === '' ? '' : String(state.combination.recording_year)}
                on:input={onYear}
            />
        </label>
    </div>

    <label class="comments">
        <span>Comments <span class="hint">optional</span></span>
        <textarea
            rows="3"
            maxlength="1000"
            placeholder="Anything the reviewer should know…"
            value={state.comments}
            on:input={(e) => submitWizard.update((s) => ({ ...s, comments: (e.currentTarget as HTMLTextAreaElement).value }))}
        ></textarea>
    </label>

    <label class="auto-claim">
        <input
            type="checkbox"
            checked={state.autoClaim}
            on:change={(e) => submitWizard.update((s) => ({ ...s, autoClaim: (e.currentTarget as HTMLInputElement).checked }))}
        />
        <span class="ac-text">
            <span class="ac-label">Auto-claim me as reviewer once alignment finishes</span>
            <span class="ac-hint">You hold one claim at a time. Skipped if you're already holding one.</span>
        </span>
    </label>
</div>

<style>
    .step {
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
    }
    .lede {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-muted);
        max-width: 60ch;
    }
    .grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-3);
    }
    label {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .hint {
        color: var(--text-faint);
        margin-left: 6px;
        text-transform: lowercase;
        font-size: 10.5px;
    }
    select, input, textarea {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: inherit;
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    select:focus, input:focus, textarea:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--panel-2);
    }
    .comments textarea {
        resize: vertical;
        min-height: 72px;
    }
    .auto-claim {
        display: flex;
        flex-direction: row;
        align-items: flex-start;
        gap: var(--s-2);
        padding: var(--s-3);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        cursor: pointer;
    }
    .auto-claim input[type='checkbox'] {
        margin-top: 3px;
        flex-shrink: 0;
        width: auto;
    }
    .ac-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .ac-label {
        color: var(--text-primary);
        font-size: var(--fs-meta);
    }
    .ac-hint {
        color: var(--text-muted);
        font-size: 10.5px;
        line-height: 1.4;
    }
</style>
