<script lang="ts">
    /**
     * Accept-confirm dialog for an intake request (owner-only).
     *
     * Accepting mints a real catalog reciter/delivery, so the owner confirms the
     * fields the audio URL can't supply: the permanent **slug** (sticky once
     * created — the state row + wip/<slug>/ + manifest bind to it), the
     * **reciter_id** (new reciters only), and the **source** + **channel** vocab
     * FKs. Identity/combination are carried from the request, shown read-only.
     */
    import { onMount } from 'svelte';

    import { acceptRequest } from '../../../../lib/api/admin-requests';
    import type { AdminRequestRow } from '../../../../lib/types/generated/schemas';
    import { titleCaseSlug } from '../../../../lib/utils/delivery-label';

    interface Props {
        row: AdminRequestRow;
        onClose: () => void;
        onAccepted: (slug: string) => void;
    }
    let { row, onClose, onAccepted }: Props = $props();

    interface VocabRow {
        slug: string;
        short?: string;
        name: string;
    }
    let sources = $state<VocabRow[]>([]);
    let channels = $state<VocabRow[]>([]);
    let riwayat = $state<VocabRow[]>([]);
    let styles = $state<VocabRow[]>([]);

    const isNewReciter = $derived(row.kind === 'new_reciter');
    const edits = $derived((row.proposed_edits ?? {}) as Record<string, unknown>);

    function toSlug(s: string): string {
        return (s || '')
            .toLowerCase()
            .normalize('NFKD')
            .replace(/[^a-z0-9]+/g, '_')
            .replace(/^_+|_+$/g, '')
            .replace(/_+/g, '_');
    }
    function shortOf(list: VocabRow[], slug: string): string {
        return list.find((v) => v.slug === slug)?.short || slug;
    }

    const suggestedReciterId = $derived(
        isNewReciter ? toSlug((edits.name_en as string) ?? '') : (row.reciter_id ?? ''),
    );

    let reciterId = $state('');
    let slug = $state('');
    let source = $state('');
    let channel = $state('');
    let busy = $state(false);
    let error = $state<string | null>(null);
    let reciterTouched = false;
    let slugTouched = false;

    // Build the slug per the catalog convention (catalog.md §3):
    //   <reciter_id>[_riwayah_short≠hafs][_style_short≠murattal][_year]_<channel_short>
    // Owner can override; it becomes the permanent, sticky slug.
    const suggestedSlug = $derived.by(() => {
        const parts = [reciterId];
        const r = row.riwayah ?? '';
        const st = row.style ?? '';
        // Omit the default riwayah/style by SHORT (catalog.md §3): hafs_an_asim
        // → short 'hafs' (omitted), murattal → 'murattal' (omitted).
        const rShort = r ? shortOf(riwayat, r) : '';
        const stShort = st ? shortOf(styles, st) : '';
        if (rShort && rShort !== 'hafs') parts.push(rShort);
        if (stShort && stShort !== 'murattal') parts.push(stShort);
        const year = edits.recording_year;
        if (year) parts.push(String(year));
        if (channel) parts.push(shortOf(channels, channel));
        return parts.filter(Boolean).map(toSlug).join('_');
    });

    // Seed the editable fields from the suggestions until the owner edits them.
    $effect(() => {
        if (!reciterTouched) reciterId = suggestedReciterId;
    });
    $effect(() => {
        if (!slugTouched) slug = suggestedSlug;
    });

    onMount(async () => {
        try {
            const res = await fetch('/api/static/catalog.json');
            if (!res.ok) return;
            const cat = await res.json();
            const pick = (xs: VocabRow[]) =>
                (xs ?? []).map((v) => ({ slug: v.slug, short: v.short, name: v.name }));
            sources = pick(cat?.vocab?.sources);
            channels = pick(cat?.vocab?.channels);
            riwayat = pick(cat?.vocab?.riwayat);
            styles = pick(cat?.vocab?.styles);
        } catch {
            // Best-effort — owner can still type valid slugs if the fetch fails.
        }
    });

    const canAccept = $derived(
        !!slug.trim() && !!reciterId.trim() && !!source && !!channel && !busy,
    );

    async function confirm(): Promise<void> {
        if (!canAccept) return;
        busy = true;
        error = null;
        try {
            const minted = await acceptRequest(row.id, {
                slug: slug.trim(),
                reciter_id: reciterId.trim(),
                source,
                channel,
            });
            onAccepted(minted);
        } catch (e) {
            error = e instanceof Error ? e.message : 'Accept failed.';
        } finally {
            busy = false;
        }
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') onClose();
    }

    const comboLabel = $derived(
        [row.riwayah, row.style]
            .filter(Boolean)
            .map((s) => titleCaseSlug(s as string))
            .join(' · '),
    );
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
    <div class="dialog" role="dialog" aria-modal="true" aria-label="Accept request">
        <header>
            <h3>Accept &amp; create catalog entry</h3>
            <button class="close" aria-label="Close" onclick={onClose}>×</button>
        </header>

        <p class="lede">
            This mints a real reciter/delivery and queues it for alignment. The slug is
            permanent — choose it deliberately.
        </p>

        <div class="ctx">
            <span class="ctx-name">
                {(edits.name_en as string) ?? row.name_en ?? '—'}
                {#if (edits.name_ar as string) || row.name_ar}
                    <span dir="rtl" class="ctx-ar">{(edits.name_ar as string) ?? row.name_ar}</span>
                {/if}
            </span>
            <span class="ctx-combo">{comboLabel || '—'}</span>
        </div>

        <div class="fields">
            {#if isNewReciter}
                <label>
                    <span>Reciter ID</span>
                    <input
                        type="text"
                        bind:value={reciterId}
                        spellcheck="false"
                        placeholder="reciter_id_slug"
                        oninput={() => (reciterTouched = true)}
                    />
                </label>
            {/if}
            <div class="two">
                <label>
                    <span>Source</span>
                    <select bind:value={source}>
                        <option value="" disabled>Pick one…</option>
                        {#each sources as s (s.slug)}
                            <option value={s.slug}>{s.name}</option>
                        {/each}
                    </select>
                </label>
                <label>
                    <span>Channel</span>
                    <select bind:value={channel}>
                        <option value="" disabled>Pick one…</option>
                        {#each channels as c (c.slug)}
                            <option value={c.slug}>{c.name}</option>
                        {/each}
                    </select>
                </label>
            </div>
            <label>
                <span>Delivery slug</span>
                <input
                    type="text"
                    bind:value={slug}
                    spellcheck="false"
                    placeholder="pick a channel to complete the slug"
                    oninput={() => (slugTouched = true)}
                />
                <span class="slug-hint">
                    Built per the catalog convention
                    <code>reciter[_riwayah][_style][_year]_channel</code> (hafs / murattal
                    omitted). Edit if needed — it’s permanent.
                </span>
            </label>
        </div>

        {#if error}
            <p class="err" role="alert">{error}</p>
        {/if}

        <footer>
            <button class="ghost" onclick={onClose} disabled={busy}>Cancel</button>
            <button class="primary" onclick={confirm} disabled={!canAccept}>
                {busy ? 'Creating…' : 'Accept & create'}
            </button>
        </footer>
    </div>
</div>

<style>
    .backdrop {
        position: fixed;
        inset: 0;
        z-index: 140;
        background: oklch(0.06 0.005 268 / 0.72);
        backdrop-filter: blur(3px);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: var(--s-6);
    }
    .dialog {
        width: min(480px, 94vw);
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        padding: var(--s-5);
        /* Cap to the viewport (backdrop adds --s-6 padding each side) and
           scroll internally so content never clips off screen on short or
           zoomed viewports. Mirrors SubmitWizard / RequestForm sizing. */
        max-height: min(88vh, 880px);
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
        overflow-y: auto;
        box-shadow: 0 32px 80px oklch(0 0 0 / 0.45);
    }
    header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        /* Keep the close button reachable while the body scrolls. */
        position: sticky;
        top: 0;
        margin: calc(-1 * var(--s-5)) calc(-1 * var(--s-5)) 0;
        padding: var(--s-5) var(--s-5) 0;
        background: var(--canvas);
        z-index: 1;
    }
    h3 { margin: 0; font-size: var(--fs-h3); font-weight: 500; color: var(--text-primary); }
    .close {
        width: 28px; height: 28px; display: inline-flex; align-items: center; justify-content: center;
        color: var(--text-muted); border-radius: var(--r-2); font-size: 18px; line-height: 1;
        background: transparent; border: 0; cursor: pointer;
    }
    .close:hover { color: var(--text-primary); background: var(--panel); }
    .lede { margin: 0; font-size: var(--fs-meta); color: var(--text-muted); line-height: var(--lh-normal); }

    .ctx {
        display: flex; flex-direction: column; gap: 2px;
        padding: var(--s-3); background: var(--canvas-inset);
        border: 1px solid var(--border-quiet); border-radius: var(--r-2);
    }
    .ctx-name { font-size: var(--fs-row); color: var(--text-primary); display: flex; align-items: baseline; gap: var(--s-2); }
    .ctx-ar { font-size: var(--fs-meta); color: var(--text-secondary); }
    .ctx-combo { font-size: var(--fs-meta); color: var(--text-muted); font-family: var(--font-mono); }

    .fields { display: flex; flex-direction: column; gap: var(--s-3); }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-3); }
    label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-meta); color: var(--text-muted); }
    .slug-hint { font-size: 10.5px; color: var(--text-faint); line-height: 1.5; }
    .slug-hint code { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
    input, select {
        background: var(--panel); border: 1px solid var(--border-default); color: var(--text-primary);
        border-radius: var(--r-2); padding: 8px 10px; font: inherit;
    }
    input { font-family: var(--font-mono); }
    input:focus, select:focus { outline: none; border-color: var(--accent); }

    .err { margin: 0; font-size: var(--fs-meta); color: var(--state-error-fg); }

    footer { display: flex; justify-content: flex-end; gap: var(--s-2); }
    .ghost, .primary {
        padding: 7px 14px; border-radius: var(--r-2); font: 500 var(--fs-meta)/1 var(--font-sans);
        border: 1px solid var(--border-default); cursor: pointer;
        transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast);
    }
    .ghost { background: transparent; color: var(--text-muted); }
    .ghost:hover { color: var(--text-primary); border-color: var(--border-strong); }
    .primary { background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }
    .primary:hover:not(:disabled) { background: var(--accent-strong); border-color: var(--accent-strong); }
    .primary:disabled, .ghost:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
