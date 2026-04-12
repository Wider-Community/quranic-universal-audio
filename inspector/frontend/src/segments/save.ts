/**
 * Save flow: preview, confirm, execute save to server.
 */

import { state, dom, isDirty, _SEG_NORMAL_IDS } from './state';
import { surahOptionText } from '../shared/surah-info';
import { getChapterSegments, onSegReciterChange } from './data';
import { _ensureWaveformObserver } from './waveform/index';
import { refreshValidation } from './validation/index';
import { renderEditHistoryPanel } from './history/index';
import { _buildSplitLineage, _buildSplitChains } from './history/index';
import { renderHistorySummaryStats, renderHistoryBatches, drawHistoryArrows, _countVersesFromBatches } from './history/rendering';
import { stopErrorCardAudio } from './validation/error-card-audio';
import { fetchJson, fetchJsonOrNull } from '../shared/api';
import type { SegEditHistoryResponse, SegSaveResponse } from '../types/api';
import type { HistoryBatch, EditOp, Segment } from '../types/domain';

interface SavePreviewBatch {
    batch_id: null;
    saved_at_utc: null;
    chapter: number;
    save_mode: 'full_replace' | 'patch';
    operations: EditOp[];
}

interface SavePreviewData {
    batches: SavePreviewBatch[];
    summary: {
        total_operations: number;
        total_batches: number;
        chapters_edited: number;
        verses_edited: number;
        op_counts: Record<string, number>;
        fix_kind_counts: Record<string, number>;
    };
    warningChapters: number[];
}

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
        verses_edited: _countVersesFromBatches(batches as unknown as HistoryBatch[]) ?? 0,
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

    state._segSavedChains = { splitChains: state._splitChains, chainedOpIds: state._chainedOpIds };
    const allBatches = [...(state.segHistoryData?.batches || []), ...(data.batches as unknown as HistoryBatch[])];
    const splitLineage = _buildSplitLineage(allBatches);
    const built = _buildSplitChains(allBatches, splitLineage);
    state._splitChains = built.chains as Map<string, unknown> | null;
    state._chainedOpIds = built.chainedOpIds as Set<string> | null;

    renderHistorySummaryStats(data.summary, dom.segSavePreviewStats);

    if (data.warningChapters.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'seg-save-preview-warning';
        warn.textContent = `${data.warningChapters.length} chapter(s) marked as changed `
            + `but have no detailed operations recorded: `
            + data.warningChapters.map(c => surahOptionText(c)).join(', ');
        dom.segSavePreviewStats.prepend(warn);
    }

    renderHistoryBatches(data.batches as unknown as HistoryBatch[], dom.segSavePreviewBatches);

    dom.segSavePreviewBatches.querySelectorAll<HTMLElement>('.seg-history-batch-time').forEach(el => {
        if (el.textContent === 'Pending') el.style.color = '#f0a500';
    });

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

    const observer = _ensureWaveformObserver();
    dom.segSavePreview.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        dom.segSavePreview.querySelectorAll<HTMLElement>('.seg-history-diff').forEach(d => drawHistoryArrows(d));
    });
}

// ---------------------------------------------------------------------------
// hideSavePreview
// ---------------------------------------------------------------------------

export function hideSavePreview(restoreScroll = true): void {
    stopErrorCardAudio();
    dom.segSavePreview.hidden = true;
    dom.segSavePreviewStats.innerHTML = '';
    dom.segSavePreviewBatches.innerHTML = '';

    if (state._segSavedChains) {
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
