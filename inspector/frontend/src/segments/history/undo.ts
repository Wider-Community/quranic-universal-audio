// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Undo operations: batch undo, op undo, chain undo, pending discard.
 */

import { state, dom, isDirty, _SEG_NORMAL_IDS } from '../state';
import { surahOptionText } from '../../shared/surah-info';
import { _ensureWaveformObserver } from '../waveform/index';
import { renderEditHistoryPanel, _buildSplitLineage, _buildSplitChains } from './index';
import { renderHistorySummaryStats, renderHistoryBatches, drawHistoryArrows, _countVersesFromBatches } from './rendering';
import { stopErrorCardAudio } from '../validation/error-card-audio';
import { hideSavePreview, buildSavePreviewData } from '../save';

// ---------------------------------------------------------------------------
// _afterUndoSuccess -- shared post-undo refresh
// ---------------------------------------------------------------------------

export async function _afterUndoSuccess(reciter, opsReversed) {
    try {
        const histResp = await fetch(`/api/seg/edit-history/${reciter}`);
        if (histResp.ok) {
            state.segHistoryData = await histResp.json();
            renderEditHistoryPanel(state.segHistoryData);
            const observer = _ensureWaveformObserver();
            dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
            requestAnimationFrame(() => {
                dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(d => drawHistoryArrows(d));
            });
        }
    } catch (_) { /* non-critical */ }
    state._segDataStale = true;
    fetch(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' }).catch(() => {});
    dom.segPlayStatus.textContent = `Undo successful \u2014 ${opsReversed} op${opsReversed !== 1 ? 's' : ''} reversed`;
}

// ---------------------------------------------------------------------------
// onBatchUndoClick
// ---------------------------------------------------------------------------

export async function onBatchUndoClick(batchId, chapter, btn) {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this save${chLabel}? The operations will be reversed.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const resp = await fetch(`/api/seg/undo-batch/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: batchId }),
        });
        const result = await resp.json();
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo batch failed:', e);
        alert('Undo failed \u2014 see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// onOpUndoClick
// ---------------------------------------------------------------------------

export async function onOpUndoClick(batchId, opIds, btn) {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    if (!confirm('Undo this operation?')) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const resp = await fetch(`/api/seg/undo-ops/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: batchId, op_ids: opIds }),
        });
        const result = await resp.json();
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo op failed:', e);
        alert('Undo failed \u2014 see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// _getChainBatchIds
// ---------------------------------------------------------------------------

export function _getChainBatchIds(chain) {
    const seen = new Set();
    const ids = [];
    for (let i = chain.ops.length - 1; i >= 0; i--) {
        const batchId = chain.ops[i].batch?.batch_id;
        if (batchId && !seen.has(batchId)) {
            seen.add(batchId);
            ids.push(batchId);
        }
    }
    return ids;
}

// ---------------------------------------------------------------------------
// onChainUndoClick
// ---------------------------------------------------------------------------

export async function onChainUndoClick(batchIds, chapter, btn) {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this entire split chain${chLabel}? ${batchIds.length} save(s) will be reversed in order.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    let totalReversed = 0;
    let failed = false;
    for (const batchId of batchIds) {
        try {
            const resp = await fetch(`/api/seg/undo-batch/${reciter}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_id: batchId }),
            });
            const result = await resp.json();
            if (result.ok) {
                totalReversed += result.operations_reversed || 0;
            } else {
                alert(`Undo failed on batch ${batchIds.indexOf(batchId) + 1}/${batchIds.length}: ${result.error}`);
                failed = true;
                break;
            }
        } catch (e) {
            console.error('Chain undo failed:', e);
            alert('Undo failed \u2014 see console for details');
            failed = true;
            break;
        }
    }

    await _afterUndoSuccess(reciter, totalReversed);
    if (!failed) {
        dom.segPlayStatus.textContent = `Undo successful \u2014 ${totalReversed} op${totalReversed !== 1 ? 's' : ''} reversed across ${batchIds.length} save(s)`;
    } else {
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

// ---------------------------------------------------------------------------
// onPendingBatchDiscard -- discard unsaved edits for a chapter
// ---------------------------------------------------------------------------

export function onPendingBatchDiscard(chapter, btn) {
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Discard pending edits${chLabel}?`)) return;

    state.segDirtyMap.delete(chapter);
    state.segDirtyMap.delete(String(chapter));
    state.segOpLog.delete(chapter);
    state.segOpLog.delete(String(chapter));

    state._segDataStale = true;
    dom.segSaveBtn.disabled = !isDirty();

    if (!isDirty()) {
        hideSavePreview();
        return;
    }
    const data = buildSavePreviewData();
    const allBatches = [...(state.segHistoryData?.batches || []), ...data.batches];
    const splitLineage = _buildSplitLineage(allBatches);
    const built = _buildSplitChains(allBatches, splitLineage);
    state._splitChains = built.chains;
    state._chainedOpIds = built.chainedOpIds;
    renderHistorySummaryStats(data.summary, dom.segSavePreviewStats);
    if (data.warningChapters.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'seg-save-preview-warning';
        warn.textContent = `${data.warningChapters.length} chapter(s) marked as changed `
            + `but have no detailed operations recorded: `
            + data.warningChapters.map(c => surahOptionText(c)).join(', ');
        dom.segSavePreviewStats.prepend(warn);
    }
    renderHistoryBatches(data.batches, dom.segSavePreviewBatches);
    dom.segSavePreviewBatches.querySelectorAll('.seg-history-batch-time').forEach(el => {
        if (el.textContent === 'Pending') el.style.color = '#f0a500';
    });
    const observer = _ensureWaveformObserver();
    dom.segSavePreview.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        dom.segSavePreview.querySelectorAll('.seg-history-diff').forEach(d => drawHistoryArrows(d));
    });
}
