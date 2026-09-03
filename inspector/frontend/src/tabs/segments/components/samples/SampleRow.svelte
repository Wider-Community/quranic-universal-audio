<script lang="ts">
    /** One row of the samples list: identity, status, export badge, actions. */
    import * as m from '$lib/paraglide/messages';
    import {
        deleteSample,
        downloadSampleAudio,
        downloadSampleExport,
        renameSample,
        reviewSample,
        SampleApiError,
    } from '../../../../lib/api/samples';
    import { pushToast } from '../../../../lib/stores/toast';
    import type { SampleRow as SampleRowT } from '../../../../lib/types/generated/schemas';

    interface Props {
        sample: SampleRowT;
        onOpen: (_slug: string) => void;
        onChanged: () => Promise<void>;
    }
    const { sample, onOpen, onChanged }: Props = $props();

    let busy = $state(false);

    // The ingest chip is only worth a row slot while the upload is still
    // being processed or has failed; a ready ingest is the unremarkable case.
    const ingestLabel = $derived(
        sample.status === 'failed'
            ? m.segments_samples_status_failed()
            : m.segments_samples_status_processing(),
    );
    const reviewed = $derived(!!sample.reviewed_at);
    const reviewedTitle = $derived(
        sample.reviewed_by_login ? `${m.segments_samples_ready_tag()} — ${sample.reviewed_by_login}` : '',
    );
    const created = $derived(new Date(sample.created_at).toLocaleString());

    function fail(e: unknown): void {
        pushToast({ kind: 'error', text: e instanceof SampleApiError ? e.message : String(e) });
    }

    async function rename(): Promise<void> {
        const next = window.prompt(m.segments_samples_rename_prompt(), sample.name)?.trim();
        if (!next || next === sample.name) return;
        busy = true;
        try {
            await renameSample(sample.id, next);
            await onChanged();
        } catch (e) {
            fail(e);
        } finally {
            busy = false;
        }
    }

    async function remove(): Promise<void> {
        if (!window.confirm(m.segments_samples_delete_confirm({ name: sample.name }))) return;
        busy = true;
        try {
            await deleteSample(sample.id);
            pushToast({ kind: 'success', text: m.segments_samples_deleted_toast() });
            await onChanged();
        } catch (e) {
            fail(e);
        } finally {
            busy = false;
        }
    }

    async function toggleReviewed(): Promise<void> {
        busy = true;
        try {
            await reviewSample(sample.id, !reviewed);
            await onChanged();
        } catch (e) {
            fail(e);
        } finally {
            busy = false;
        }
    }

    async function exportJson(): Promise<void> {
        downloadSampleExport(sample);
        // The export stamps last_export_at server-side; refetch so the badge clears.
        setTimeout(() => void onChanged(), 1500);
    }
</script>

<div class="row" role="row" class:failed={sample.status === 'failed'}>
    <div class="cell name">
        <span class="name-text" title={sample.audio_filename}>{sample.name}</span>
        {#if sample.status !== 'ready'}
            <span class="chip" class:chip-warn={sample.status === 'failed'} class:chip-pending={sample.status === 'processing'} title={sample.error ?? ''}>
                {ingestLabel}
            </span>
        {/if}
        {#if sample.wbw_complete}
            <span class="chip chip-ok">{m.segments_samples_wbw_tag()}</span>
        {/if}
        {#if reviewed}
            <span class="chip chip-ok" title={reviewedTitle}>{m.segments_samples_ready_tag()}</span>
        {/if}
        {#if sample.changed_since_export}
            <span class="chip chip-warn">{m.segments_samples_changed_badge()}</span>
        {/if}
    </div>
    <div class="cell">{sample.owner_login ?? sample.owner_hf_user_id}</div>
    <div class="cell">{created}</div>
    <div class="cell actions">
        <button type="button" class="btn primary" disabled={busy || sample.status !== 'ready'} onclick={() => onOpen(sample.slug)}>
            {m.segments_samples_open()}
        </button>
        <button type="button" class="btn" disabled={busy || sample.status !== 'ready'} onclick={exportJson}>
            {m.segments_samples_export()}
        </button>
        <button type="button" class="btn" disabled={busy} onclick={() => downloadSampleAudio(sample)}>
            {m.segments_samples_download_audio()}
        </button>
        <button type="button" class="btn" disabled={busy || sample.status !== 'ready'} onclick={toggleReviewed}>
            {reviewed ? m.segments_samples_unreview() : m.segments_samples_review()}
        </button>
        {#if sample.can_manage}
            <button type="button" class="btn" disabled={busy} onclick={rename}>{m.segments_samples_rename()}</button>
            <button type="button" class="btn danger" disabled={busy} onclick={remove}>{m.segments_samples_delete()}</button>
        {/if}
    </div>
</div>

<style>
    .row {
        display: grid; grid-template-columns: minmax(180px, 2fr) 1fr 1fr auto; gap: var(--s-2);
        align-items: center; padding: 8px var(--s-3); border-top: 1px solid var(--border-quiet);
        font-size: var(--fs-body); color: var(--text-secondary);
    }
    .row.failed { background: color-mix(in oklch, var(--state-error-bg) 40%, transparent); }
    .cell { min-width: 0; }
    .name { display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap; }
    .name-text { color: var(--text-primary); font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .chip {
        display: inline-flex; align-items: center; gap: 4px; height: 22px; padding: 0 7px;
        background: var(--panel-2); border: 1px solid var(--border-quiet); border-radius: 999px;
        font-size: 11px; font-family: var(--font-mono); color: var(--text-secondary); white-space: nowrap;
    }
    .chip-pending { background: var(--state-available-bg); border-color: oklch(0.84 0.110 300 / 0.4); color: var(--state-available-fg); }
    .chip-ok { background: var(--state-published-bg); border-color: var(--state-published-border); color: var(--state-published-fg); }
    .chip-warn { background: var(--state-error-bg); border-color: oklch(0.86 0.130 75 / 0.4); color: var(--state-error-fg); }

    .actions { display: inline-flex; align-items: center; gap: var(--s-1); flex-wrap: wrap; justify-content: flex-end; }
    .btn {
        background: transparent; border: 1px solid var(--border-quiet); color: var(--text-secondary);
        font: inherit; font-size: var(--fs-meta); padding: 3px 10px; border-radius: var(--r-1);
        cursor: pointer; white-space: nowrap;
    }
    .btn:hover:not(:disabled) { border-color: var(--border-default); color: var(--text-primary); }
    .btn:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn.primary { border-color: var(--accent); color: var(--accent); }
    .btn.danger:hover:not(:disabled) { border-color: var(--state-error-fg); color: var(--state-error-fg); }
</style>
