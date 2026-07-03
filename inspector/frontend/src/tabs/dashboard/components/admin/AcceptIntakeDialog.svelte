<script lang="ts">
    /**
     * Accept-confirm dialog for an intake request (owner-only).
     *
     * Accepting does NOT create the catalog delivery — source / channel / bitrate
     * (and therefore the slug's channel suffix) are probed from the actual audio
     * and only become valid during offline ingest. The one human decision made
     * here is the canonical reciter_id for a *new* reciter; everything else the
     * pipeline determines. For a new combination there's nothing to fill — it's a
     * plain confirm.
     */
    import { acceptRequest } from '../../../../lib/api/admin-requests';
    import { vocabLabel } from '../../../../lib/i18n/vocab';
    import type { AdminRequestRow } from '../../../../lib/types/generated/schemas';

    interface Props {
        row: AdminRequestRow;
        onClose: () => void;
        onAccepted: () => void;
    }
    let { row, onClose, onAccepted }: Props = $props();

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
    const SLUG_RE = /^[a-z][a-z0-9_]{1,79}$/;

    let reciterId = $state('');
    let touched = false;
    let busy = $state(false);
    let error = $state<string | null>(null);

    const suggestedReciterId = $derived(toSlug((edits.name_en as string) ?? ''));
    $effect(() => {
        if (!touched) reciterId = suggestedReciterId;
    });

    const reciterIdValid = $derived(!isNewReciter || SLUG_RE.test(reciterId.trim()));
    const canAccept = $derived(reciterIdValid && !busy);

    const comboLabel = $derived(
        [vocabLabel('riwayah', row.riwayah), vocabLabel('style', row.style)].filter(Boolean).join(' · '),
    );

    async function confirm(): Promise<void> {
        if (!canAccept) return;
        busy = true;
        error = null;
        try {
            await acceptRequest(row.id, isNewReciter ? { reciter_id: reciterId.trim() } : {});
            onAccepted();
        } catch (e) {
            error = e instanceof Error ? e.message : 'Accept failed.';
        } finally {
            busy = false;
        }
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key === 'Escape') onClose();
    }
</script>

<svelte:window onkeydown={onKey} />

<div class="backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && onClose()}>
    <div class="dialog" role="dialog" aria-modal="true" aria-label="Accept request">
        <header>
            <h3>Accept &amp; queue for ingest</h3>
            <button class="close" aria-label="Close" onclick={onClose}>×</button>
        </header>

        <p class="lede">
            Approving queues this contribution for ingest. The pipeline fetches the audio,
            classifies its source &amp; channel, mints the delivery slug, and aligns it — none
            of that is decided here.
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

        {#if isNewReciter}
            <label>
                <span>Reciter ID <span class="req">required</span></span>
                <input
                    type="text"
                    bind:value={reciterId}
                    spellcheck="false"
                    placeholder="canonical_reciter_id"
                    oninput={() => (touched = true)}
                    class:invalid={reciterId.trim() !== '' && !reciterIdValid}
                />
                <span class="hint">
                    The catalog’s canonical id for this reciter (lowercase, underscores). The
                    delivery slug is built from it at ingest:
                    <code>reciter[_riwayah][_style][_year]_channel</code>.
                </span>
            </label>
        {:else}
            <p class="combo-note">
                The reciter already exists — ingest adds this new combination as a delivery.
            </p>
        {/if}

        {#if error}
            <p class="err" role="alert">{error}</p>
        {/if}

        <footer>
            <button class="ghost" onclick={onClose} disabled={busy}>Cancel</button>
            <button class="primary" onclick={confirm} disabled={!canAccept}>
                {busy ? 'Queuing…' : 'Accept'}
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
        width: min(460px, 94vw);
        background: var(--canvas);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        padding: var(--s-5);
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
        box-shadow: 0 32px 80px oklch(0 0 0 / 0.45);
    }
    header { display: flex; align-items: center; justify-content: space-between; }
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

    label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-meta); color: var(--text-muted); }
    .req { color: var(--text-faint); font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; margin-left: 4px; }
    input {
        background: var(--panel); border: 1px solid var(--border-default); color: var(--text-primary);
        border-radius: var(--r-2); padding: 8px 10px; font: inherit; font-family: var(--font-mono);
    }
    input:focus { outline: none; border-color: var(--accent); }
    input.invalid { border-color: var(--state-error-fg); color: var(--state-error-fg); }
    .hint { font-size: 10.5px; color: var(--text-faint); line-height: 1.5; }
    .hint code { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
    .combo-note { margin: 0; font-size: var(--fs-meta); color: var(--text-secondary); }

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
