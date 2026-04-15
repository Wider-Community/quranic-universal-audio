/**
 * Save flow: preview, confirm, execute save to server.
 */

import { get as storeGet } from 'svelte/store';

import { fetchJson, fetchJsonOrNull } from '../lib/api';
import {
    buildSplitChains,
    buildSplitLineage,
    countVersesFromBatches,
    historyData,
    restoreSplitChains,
    setSplitChains,
    snapshotSplitChains,
} from '../lib/stores/segments/history';
import {
    clearSavePreviewData,
    hidePreview,
    type SavePreviewBatch,
    type SavePreviewData,
    setSavePreviewData,
    showPreview,
} from '../lib/stores/segments/save';
import type { SegEditHistoryResponse, SegSaveResponse } from '../types/api';
import type { EditOp, HistoryBatch, Segment } from '../types/domain';
import { _SEG_NORMAL_IDS } from './constants';
import { getChapterSegments, onSegReciterChange } from './data';
import { renderEditHistoryPanel } from './history/index';
import { dom, isDirty, state } from './state';
import { stopErrorCardAudio } from './validation/error-card-audio';
import { refreshValidation } from './validation/index';


// ---------------------------------------------------------------------------
// onSegSaveClick -- entry point from Save button
// ---------------------------------------------------------------------------

export async function onSegSaveClick(): Promise<void> {
    if (!isDirty()) return;
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    showSavePreview();
}

// ---------------------------------------------------------------------------
// buildSavePreviewData
// ---------------------------------------------------------------------------

export function buildSavePreviewData(): SavePreviewData {
    const batches: SavePreviewBatch[] = [];
    const warningChapters: number[] = [];
    const opCounts: Record<string, number> = {};
    const fixKindCounts: Record<string, number> = {};
    let totalOps = 0;

    for (const [ch, dirtyEntry] of state.segDirtyMap) {
        const chOps = state.segOpLog.get(ch) || [];
        if (chOps.length === 0) { warningChapters.push(ch); continue; }
        for (const op of chOps) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            const kind = op.fix_kind || 'manual';
            fixKindCounts[kind] = (fixKindCounts[kind] || 0) + 1;
            totalOps++;
        }
        batches.push({
            batch_id: null,
            saved_at_utc: null,
            chapter: typeof ch === 'string' ? parseInt(ch) : ch,
            save_mode: dirtyEntry.structural ? 'full_replace' : 'patch',
            operations: chOps,
        });
    }

    const summary = {
        total_operations: totalOps,
        total_batches: batches.length + warningChapters.length,
        chapters_edited: batches.length + warningChapters.length,
        verses_edited: countVersesFromBatches(batches as HistoryBatch[]),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
    return { batches, summary, warningChapters };
}

// ---------------------------------------------------------------------------
// showSavePreview
// ---------------------------------------------------------------------------

export function showSavePreview(): void {
    if (!dom.segSavePreview.hidden) return;
    state._segSavedPreviewState = { scrollTop: dom.segListEl.scrollTop };
    const data = buildSavePreviewData();

    // Snapshot current split-chain state so hideSavePreview can restore it.
    // snapshotSplitChains() returns { chains, chainedOpIds }; map to the
    // legacy SavedChainsSnapshot shape { splitChains, chainedOpIds }.
    const snap = snapshotSplitChains();
    state._segSavedChains = { splitChains: snap.chains, chainedOpIds: snap.chainedOpIds };

    // Rebuild split chains to include pending batches, push to store so
    // SavePreview.svelte (and HistoryPanel) see the augmented chain map.
    const allBatches = [...(storeGet(historyData)?.batches || []), ...(data.batches as HistoryBatch[])];
    const splitLineage = buildSplitLineage(allBatches);
    const built = buildSplitChains(allBatches, splitLineage);
    // Keep legacy state fields in sync (consumed by imperative history/rendering.ts
    // code that remains until P3 orphan deletion).
    state._splitChains = built.chains;
    state._chainedOpIds = built.chainedOpIds;
    setSplitChains(built.chains, built.chainedOpIds);

    // Publish preview data to store — SavePreview.svelte renders reactively.
    setSavePreviewData(data);

    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByPreview = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { controls.dataset.hiddenByPreview = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByPreview = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    dom.segHistoryView.hidden = true;

    dom.segSavePreview.hidden = false;
    showPreview(); // notify $savePreviewVisible store (SavePreview.svelte hidden binding)
}

// ---------------------------------------------------------------------------
// hideSavePreview
// ---------------------------------------------------------------------------

export function hideSavePreview(restoreScroll = true): void {
    stopErrorCardAudio();
    dom.segSavePreview.hidden = true;
    hidePreview(); // notify $savePreviewVisible store (SavePreview.svelte hidden binding)
    clearSavePreviewData(); // clear store — SavePreview.svelte empties reactively

    if (state._segSavedChains) {
        // Restore split chains to their pre-preview state via the store.
        // Map legacy { splitChains, chainedOpIds } to store's { chains, chainedOpIds }.
        restoreSplitChains({ chains: state._segSavedChains.splitChains, chainedOpIds: state._segSavedChains.chainedOpIds });
        // Keep legacy state fields in sync.
        state._splitChains = state._segSavedChains.splitChains;
        state._chainedOpIds = state._segSavedChains.chainedOpIds;
        state._segSavedChains = null;
    }

    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByPreview !== '1') el.hidden = false; delete el.dataset.hiddenByPreview; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByPreview !== '1') controls.hidden = false; delete controls.dataset.hiddenByPreview; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByPreview !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByPreview; }

    if (state._segDataStale) {
        state._segDataStale = false;
        state._segSavedPreviewState = null;
        onSegReciterChange();
    } else if (restoreScroll && state._segSavedPreviewState) {
        const saved = state._segSavedPreviewState;
        state._segSavedPreviewState = null;
        requestAnimationFrame(() => { dom.segListEl.scrollTop = saved.scrollTop; });
    }
}

// ---------------------------------------------------------------------------
// confirmSaveFromPreview / executeSave
// ---------------------------------------------------------------------------

export async function confirmSaveFromPreview(): Promise<void> {
    hideSavePreview(false);
    await executeSave();
}

interface SaveSegmentPayloadFull {
    segment_uid: string;
    time_start: number;
    time_end: number;
    matched_ref: string;
    matched_text: string;
    confidence: number;
    phonemes_asr: string;
    audio_url: string;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    ignored_categories?: string[];
}

interface SaveSegmentPayloadPatch {
    index: number;
    segment_uid: string;
    matched_ref: string;
    matched_text: string;
    confidence: number;
    ignored_categories?: string[];
}

interface SavePayloadFull {
    full_replace: true;
    segments: SaveSegmentPayloadFull[];
    operations: EditOp[];
}

interface SavePayloadPatch {
    segments: SaveSegmentPayloadPatch[];
    operations: EditOp[];
}

export async function executeSave(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;

    dom.segSaveBtn.disabled = true;
    dom.segSaveBtn.textContent = 'Saving...';

    let savedChanges = 0;
    let savedChapters = 0;
    let allOk = true;

    try {
        for (const [ch, entry] of state.segDirtyMap) {
            const chSegs: Segment[] = getChapterSegments(ch);
            let payload: SavePayloadFull | SavePayloadPatch;
            const chOps = state.segOpLog.get(ch) || [];

            if (entry.structural) {
                payload = {
                    full_replace: true,
                    segments: chSegs.map(s => {
                        const o: SaveSegmentPayloadFull = {
                            segment_uid: s.segment_uid || '',
                            time_start: s.time_start,
                            time_end: s.time_end,
                            matched_ref: s.matched_ref,
                            matched_text: s.matched_text,
                            confidence: s.confidence,
                            phonemes_asr: s.phonemes_asr || '',
                            audio_url: s.audio_url || '',
                        };
                        if (s.wrap_word_ranges) o.wrap_word_ranges = s.wrap_word_ranges;
                        if (s.has_repeated_words) o.has_repeated_words = true;
                        if (s.ignored_categories?.length) o.ignored_categories = s.ignored_categories;
                        return o;
                    }),
                    operations: chOps,
                };
                savedChanges += chOps.length;
            } else {
                const updates: SaveSegmentPayloadPatch[] = [];
                for (const idx of entry.indices) {
                    const seg = chSegs.find(s => s.index === idx);
                    if (seg) {
                        const upd: SaveSegmentPayloadPatch = {
                            index: seg.index,
                            segment_uid: seg.segment_uid || '',
                            matched_ref: seg.matched_ref,
                            matched_text: seg.matched_text,
                            confidence: seg.confidence,
                        };
                        if (seg.ignored_categories?.length) upd.ignored_categories = seg.ignored_categories;
                        updates.push(upd);
                    }
                }
                if (updates.length === 0) continue;
                payload = { segments: updates, operations: chOps };
                savedChanges += chOps.length;
            }

            const result = await fetchJson<SegSaveResponse & { error?: string }>(
                `/api/seg/save/${reciter}/${ch}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );
            if (!result.ok) {
                dom.segPlayStatus.textContent = `Save error (ch ${ch}): ${result.error}`;
                allOk = false;
                break;
            }
            state.segDirtyMap.delete(ch);
            state.segOpLog.delete(ch);
            savedChapters++;
        }

        if (allOk) {
            state.segDirtyMap.clear();
            state.segOpLog.clear();
            const msg = savedChapters > 1
                ? `Saved ${savedChanges} changes across ${savedChapters} chapters`
                : `Saved ${savedChanges} change${savedChanges !== 1 ? 's' : ''}`;
            dom.segSaveBtn.textContent = msg;
            document.querySelectorAll('.seg-row.dirty').forEach(r => r.classList.remove('dirty'));
            setTimeout(() => { dom.segSaveBtn.textContent = 'Save'; }, 2500);
            fetchJson(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' })
                .then(() => refreshValidation())
                .catch(() => refreshValidation());
            try {
                const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
                    `/api/seg/edit-history/${reciter}`,
                );
                if (hist) {
                    state.segHistoryData = hist;
                    renderEditHistoryPanel(state.segHistoryData);
                }
            } catch (_) { /* non-critical */ }
        } else {
            dom.segSaveBtn.disabled = !isDirty();
            dom.segSaveBtn.textContent = 'Save';
        }
    } catch (e) {
        console.error('Save failed:', e);
        dom.segPlayStatus.textContent = 'Save failed';
        dom.segSaveBtn.disabled = !isDirty();
        dom.segSaveBtn.textContent = 'Save';
    }
}
