/**
 * Segments Tab — Phase 7/8 code remaining after Phase 6 extraction.
 * Contains: edit operations (trim, split, merge, delete, ref edit),
 * save/undo, validation panel, error cards, stats, edit history.
 *
 * All foundation code has been extracted to segments/*.js modules.
 */

import { surahOptionText } from './shared/surah-info.js';

// Import everything from the extracted modules
import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty, unmarkDirty, isDirty, isIndexDirty,
         EDIT_OP_LABELS, ERROR_CAT_LABELS, _SEG_NORMAL_IDS } from './segments/state.js';
import { _classifySegCategories, _classifySnapIssues, _deriveOpIssueDelta, _isIgnoredFor, _stripQuranDeco } from './segments/categories.js';
import { isCrossVerse, parseSegRef, countSegWords, _normalizeRef, _addVerseMarkers, formatRef, formatTimeMs, formatDurationMs } from './segments/references.js';
import { onSegReciterChange, onSegChapterChange, clearSegDisplay, getChapterSegments, getSegByChapterIndex, getAdjacentSegments, syncChapterSegsToAll, _getChapterSegs } from './segments/data.js';
import { renderSegCard, renderSegList, getConfClass, updateSegCard, syncAllCardsForSegment, resolveSegFromRow, _getEditCanvas } from './segments/rendering.js';
import { drawSegmentWaveformFromPeaks, drawWaveformFromPeaksForSeg, drawSegPlayhead, _slicePeaks, _drawTrimHighlight, _drawSplitHighlight, _drawMergeHighlight } from './segments/waveform-draw.js';
import { _ensureWaveformObserver, drawAllSegWaveforms, _fetchPeaks, _fetchChapterPeaksIfNeeded, _redrawPeaksWaveforms } from './segments/waveform.js';
import { playFromSegment, onSegPlayClick, onSegTimeUpdate, startSegAnimation, stopSegAnimation, onSegAudioEnded, animateSeg, updateSegHighlight, drawActivePlayhead, updateSegPlayStatus } from './segments/playback.js';
import { applyFiltersAndRender, applyVerseFilterAndRender, computeSilenceAfter, segDerivedProps, renderFilterBar, updateFilterBarControls, addSegFilterCondition, clearAllSegFilters } from './segments/filters.js';
import { jumpToSegment, jumpToVerse, jumpToMissingVerseContext, findMissingVerseBoundarySegments, _showBackToResultsBanner, _restoreFilterView } from './segments/navigation.js';
import { _isCurrentReciterBySurah, _audioSrcMatch, _formatBytes, _updateCacheStatusUI, _fetchCacheStatus, _prepareAudio, _deleteAudioCache, _rewriteAudioUrls } from './segments/audio-cache.js';
import { handleSegRowClick, _handleSegCanvasMousedown } from './segments/event-delegation.js';
import { handleSegKeydown } from './segments/keyboard.js';
import { registerSegHandlers } from './segments/index.js';


// =====================================================================
// Register all Phase 7/8 handlers with the foundation modules
// =====================================================================

// Deferred registration: wait for DOMContentLoaded since index.js wires dom refs
document.addEventListener('DOMContentLoaded', () => {
    registerSegHandlers({
        // Edit operations (Phase 7)
        startRefEdit,
        enterEditWithBuffer,
        mergeAdjacent,
        deleteSegment,
        exitEditMode,
        confirmTrim,
        confirmSplit,

        // Save/undo
        onSegSaveClick,
        hideSavePreview,
        confirmSaveFromPreview,

        // Validation panel (Phase 8)
        renderValidationPanel,
        captureValPanelState,
        restoreValPanelState,
        renderStatsPanel,
        renderEditHistoryPanel,

        // Error card audio
        playErrorCardAudio,
        stopErrorCardAudio,
        ensureContextShown,
        _isWrapperContextShown,

        // Edit-mode waveform draws
        drawSplitWaveform,
        drawTrimWaveform,

        // History
        showHistoryView,
        hideHistoryView,
        clearHistoryFilters,
        setHistorySort,
    });
});


// =====================================================================
// PHASE 7/8 CODE BELOW — not yet extracted
// Everything below this line will be extracted in future phases.
// =====================================================================


// ---------------------------------------------------------------------------
// Inline ref editing
// ---------------------------------------------------------------------------

function startRefEdit(refSpan, seg, row, contextCategory = null) {
    if (refSpan.querySelector('input')) return;

    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    state._segContinuousPlay = false;

    state._pendingOp = createOp('edit_reference', contextCategory ? { contextCategory } : undefined);
    state._pendingOp.targets_before = [snapshotSeg(seg)];

    const originalRef = seg.matched_ref || '';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'seg-text-ref-input';
    input.value = originalRef;

    refSpan.textContent = '';
    refSpan.appendChild(input);
    input.focus();
    input.select();

    let committed = false;

    function commit() {
        if (committed) return;
        committed = true;
        const newRef = input.value.trim();
        commitRefEdit(seg, newRef, row);
    }

    input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            committed = true;
            state._pendingOp = null;
            state._splitChainUid = null; state._splitChainWrapper = null; state._splitChainCategory = null;
            refSpan.textContent = formatRef(originalRef);
        }
    });

    input.addEventListener('blur', commit);
    input.addEventListener('click', (e) => e.stopPropagation());
}

function _chainSplitRefEdit(chapter) {
    if (!state._splitChainUid) return;
    const chainUid = state._splitChainUid;
    const chainWrapper = state._splitChainWrapper;
    const chainCat = state._splitChainCategory;
    state._splitChainUid = null;
    state._splitChainWrapper = null;
    state._splitChainCategory = null;
    const allSegs = state.segAllData?.segments || state.segData?.segments || [];
    const secondSeg = allSegs.find(s => s.segment_uid === chainUid);
    if (!secondSeg) return;
    const selector = `.seg-row[data-seg-chapter="${secondSeg.chapter}"][data-seg-index="${secondSeg.index}"]`;
    const secondRow = (chainWrapper && chainWrapper.querySelector(selector))
        || dom.segListEl.querySelector(selector)
        || document.querySelector(selector);
    if (!secondRow) return;
    secondRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const refSpan = secondRow.querySelector('.seg-text-ref');
    if (refSpan) {
        dom.segPlayStatus.textContent = 'Now edit second half reference';
        setTimeout(() => startRefEdit(refSpan, secondSeg, secondRow, chainCat), 100);
    }
}

async function commitRefEdit(seg, newRef, row) {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    newRef = _normalizeRef(newRef);
    if (newRef === oldRef) {
        if (seg.confidence < 1.0) {
            if (state._pendingOp) {
                state._pendingOp.op_type = 'confirm_reference';
                state._pendingOp.fix_kind = 'audit';
            }
            seg.confidence = 1.0;
            if (state._pendingOp?.op_context_category) {
                if (!seg.ignored_categories) seg.ignored_categories = [];
                if (!seg.ignored_categories.includes(state._pendingOp.op_context_category))
                    seg.ignored_categories.push(state._pendingOp.op_context_category);
            }
            delete seg._derived;
            markDirty(chapter, seg.index);
            syncAllCardsForSegment(seg);
            if (state._pendingOp) {
                state._pendingOp.applied_at_utc = new Date().toISOString();
                state._pendingOp.targets_after = [snapshotSeg(seg)];
                finalizeOp(chapter, state._pendingOp);
            }
        } else {
            state._pendingOp = null;
            const refSpan = row.querySelector('.seg-text-ref');
            if (refSpan) refSpan.textContent = formatRef(oldRef);
        }
        _chainSplitRefEdit(chapter);
        return;
    }

    seg.matched_ref = newRef;
    seg.confidence = 1.0;
    if (state._pendingOp?.op_context_category) {
        if (!seg.ignored_categories) seg.ignored_categories = [];
        if (!seg.ignored_categories.includes(state._pendingOp.op_context_category))
            seg.ignored_categories.push(state._pendingOp.op_context_category);
    }

    if (newRef) {
        try {
            const resp = await fetch(`/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`);
            const data = await resp.json();
            if (data.text) {
                seg.matched_text = data.text;
                seg.display_text = data.display_text || data.text;
            } else if (data.error) {
                console.warn('resolve_ref error:', data.error);
                seg.matched_text = '(invalid ref)';
                seg.display_text = '';
            }
        } catch (e) {
            console.error('Failed to resolve ref:', e);
            seg.matched_text = '(resolve failed)';
            seg.display_text = '';
        }
    } else {
        seg.matched_text = '';
        seg.display_text = '';
    }

    delete seg._derived;
    markDirty(chapter, seg.index);
    syncAllCardsForSegment(seg);

    if (state._pendingOp) {
        state._pendingOp.applied_at_utc = new Date().toISOString();
        state._pendingOp.targets_after = [snapshotSeg(seg)];
        finalizeOp(chapter, state._pendingOp);
    }

    _chainSplitRefEdit(chapter);
}


// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

async function onSegSaveClick() {
    if (!isDirty()) return;
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    showSavePreview();
}

// ---------------------------------------------------------------------------
// Save Confirmation Preview
// ---------------------------------------------------------------------------

function buildSavePreviewData() {
    const batches = [];
    const warningChapters = [];
    const opCounts = {};
    const fixKindCounts = {};
    let totalOps = 0;

    for (const [ch, dirtyEntry] of state.segDirtyMap) {
        const chOps = state.segOpLog.get(ch) || [];
        if (chOps.length === 0) { warningChapters.push(ch); continue; }
        for (const op of chOps) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            fixKindCounts[op.fix_kind || 'manual'] = (fixKindCounts[op.fix_kind || 'manual'] || 0) + 1;
            totalOps++;
        }
        batches.push({
            batch_id: null,
            saved_at_utc: null,
            chapter: parseInt(ch),
            save_mode: dirtyEntry.structural ? 'full_replace' : 'patch',
            operations: chOps,
        });
    }

    const summary = {
        total_operations: totalOps,
        total_batches: batches.length + warningChapters.length,
        chapters_edited: batches.length + warningChapters.length,
        verses_edited: _countVersesFromBatches(batches),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
    return { batches, summary, warningChapters };
}

function showSavePreview() {
    if (!dom.segSavePreview.hidden) return;
    state._segSavedPreviewState = { scrollTop: dom.segListEl.scrollTop };
    const data = buildSavePreviewData();

    state._segSavedChains = { splitChains: state._splitChains, chainedOpIds: state._chainedOpIds };
    const allBatches = [...(state.segHistoryData?.batches || []), ...data.batches];
    const splitLineage = _buildSplitLineage(allBatches);
    const { chains, chainedOpIds } = _buildSplitChains(allBatches, splitLineage);
    state._splitChains = chains;
    state._chainedOpIds = chainedOpIds;

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

    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByPreview = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { controls.dataset.hiddenByPreview = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByPreview = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    dom.segHistoryView.hidden = true;

    dom.segSavePreview.hidden = false;

    const observer = _ensureWaveformObserver();
    dom.segSavePreview.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        dom.segSavePreview.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
}

function hideSavePreview(restoreScroll = true) {
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
    const controls = panel.querySelector('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByPreview !== '1') controls.hidden = false; delete controls.dataset.hiddenByPreview; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
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

async function confirmSaveFromPreview() {
    hideSavePreview(false);
    await executeSave();
}

async function executeSave() {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;

    dom.segSaveBtn.disabled = true;
    dom.segSaveBtn.textContent = 'Saving...';

    let savedChanges = 0;
    let savedChapters = 0;
    let allOk = true;

    try {
        for (const [ch, entry] of state.segDirtyMap) {
            const chSegs = getChapterSegments(ch);
            let payload;
            const chOps = state.segOpLog.get(ch) || [];

            if (entry.structural) {
                payload = {
                    full_replace: true,
                    segments: chSegs.map(s => {
                        const o = {
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
                const updates = [];
                for (const idx of entry.indices) {
                    const seg = chSegs.find(s => s.index === idx);
                    if (seg) {
                        const upd = {
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

            const resp = await fetch(`/api/seg/save/${reciter}/${ch}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await resp.json();
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
            fetch(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' })
                .then(() => refreshValidation())
                .catch(() => refreshValidation());
            try {
                const histResp = await fetch(`/api/seg/edit-history/${reciter}`);
                if (histResp.ok) {
                    state.segHistoryData = await histResp.json();
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


async function _afterUndoSuccess(reciter, opsReversed) {
    try {
        const histResp = await fetch(`/api/seg/edit-history/${reciter}`);
        if (histResp.ok) {
            state.segHistoryData = await histResp.json();
            renderEditHistoryPanel(state.segHistoryData);
            const observer = _ensureWaveformObserver();
            dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
            requestAnimationFrame(() => {
                dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
            });
        }
    } catch (_) { /* non-critical */ }
    state._segDataStale = true;
    fetch(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' }).catch(() => {});
    dom.segPlayStatus.textContent = `Undo successful \u2014 ${opsReversed} op${opsReversed !== 1 ? 's' : ''} reversed`;
}

async function onBatchUndoClick(batchId, chapter, btn) {
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

async function onOpUndoClick(batchId, opIds, btn) {
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

function _getChainBatchIds(chain) {
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

async function onChainUndoClick(batchIds, chapter, btn) {
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

function onPendingBatchDiscard(chapter, btn) {
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
    const { chains: ch, chainedOpIds: cIds } = _buildSplitChains(allBatches, splitLineage);
    state._splitChains = ch;
    state._chainedOpIds = cIds;
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
        dom.segSavePreview.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
}


// ---------------------------------------------------------------------------
// Adjust mode
// ---------------------------------------------------------------------------

function enterEditWithBuffer(seg, row, mode, contextCategory = null) {
    if (state.segEditMode) return;

    const isErrorPlaying = state._activeAudioSource === 'error' && state.valCardAudio && !state.valCardAudio.paused;
    const prePausePlayMs = isErrorPlaying
        ? state.valCardAudio.currentTime * 1000
        : (dom.segAudioEl.paused ? null : dom.segAudioEl.currentTime * 1000);

    if (isErrorPlaying) stopErrorCardAudio();
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    state._segContinuousPlay = false;

    const playCol = row.querySelector('.seg-play-col');
    if (playCol) playCol.hidden = true;

    state._pendingOp = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    state._pendingOp.targets_before = [snapshotSeg(seg)];

    try {
        if (mode === 'trim') enterTrimMode(seg, row);
        else if (mode === 'split') enterSplitMode(seg, row, prePausePlayMs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        state._pendingOp = null;
        state.segEditMode = null;
        state.segEditIndex = -1;
        document.body.classList.remove('seg-edit-active');
        const targetRow = document.querySelector('.seg-row.seg-edit-target');
        if (targetRow) {
            targetRow.querySelector('.seg-edit-inline')?.remove();
            const acts = targetRow.querySelector('.seg-actions');
            if (acts) acts.hidden = false;
            targetRow.classList.remove('seg-edit-target');
        }
    }
}

function enterTrimMode(seg, row) {
    if (state.segEditMode) {
        console.warn('[trim] blocked: already in edit mode:', state.segEditMode);
        return;
    }
    state.segEditMode = 'trim';
    state.segEditIndex = seg.index;

    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    const actions = row.querySelector('.seg-actions');
    if (actions) actions.hidden = true;

    const canvas = row.querySelector('canvas');
    const segLeft = row.querySelector('.seg-left');

    const inline = document.createElement('div');
    inline.className = 'seg-edit-inline';

    const durationSpan = document.createElement('span');
    durationSpan.className = 'seg-edit-duration';
    durationSpan.textContent = `${((seg.time_end - seg.time_start) / 1000).toFixed(2)}s`;

    const statusSpan = document.createElement('span');
    statusSpan.className = 'seg-edit-status';
    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    const mkBtn = (text, cls, fn) => { const b = document.createElement('button'); b.className = `btn btn-sm ${cls}`; b.textContent = text; b.addEventListener('click', fn); return b; };
    btnRow.appendChild(mkBtn('Cancel', 'btn-cancel', exitEditMode));
    btnRow.appendChild(mkBtn('Preview', 'btn-preview', previewTrimAudio));
    btnRow.appendChild(mkBtn('Apply', 'btn-confirm', () => confirmTrim(seg)));
    btnRow.appendChild(durationSpan);
    btnRow.appendChild(statusSpan);
    inline.appendChild(btnRow);

    segLeft.appendChild(inline);

    canvas._trimEls = { durationSpan, statusSpan };

    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const chapterSegs = (chapter === currentChapter) ? _getChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevEnd = segIdx > 0 ? chapterSegs[segIdx - 1].time_end : 0;
    const audioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const peaksDuration = state.segPeaksByAudio?.[audioUrl]?.duration_ms;
    const nextStart = segIdx >= 0 && segIdx < chapterSegs.length - 1
        ? chapterSegs[segIdx + 1].time_start
        : (peaksDuration || seg.time_end + 1000);
    const windowStart = Math.max(prevEnd, seg.time_start - state.TRIM_PAD_LEFT);
    const windowEnd = Math.min(nextStart, seg.time_end + state.TRIM_PAD_RIGHT);
    canvas._trimWindow = { windowStart, windowEnd, currentStart: seg.time_start, currentEnd: seg.time_end, audioUrl };
    canvas._wfCache = null;
    canvas._trimBaseCache = null;

    drawTrimWaveform(canvas);
    setupTrimDragHandles(canvas, seg);
}

function _ensureTrimBaseCache(canvas) {
    if (canvas._trimBaseCache) return true;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const tw = canvas._trimWindow;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    const audioUrl = tw.audioUrl || '';
    const data = _slicePeaks(audioUrl, tw.windowStart, tw.windowEnd, width);
    if (!data) return false;

    const scale = height / 2 * 0.9;

    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - data.minVals[i] * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.stroke();

    canvas._trimBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

function drawTrimWaveform(canvas) {
    if (!_ensureTrimBaseCache(canvas)) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const tw = canvas._trimWindow;

    ctx.putImageData(canvas._trimBaseCache, 0, 0);

    const startX = ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;
    const endX = ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;

    ctx.fillStyle = `rgba(0, 0, 0, ${state.TRIM_DIM_ALPHA})`;
    ctx.fillRect(0, 0, startX, height);
    ctx.fillRect(endX, 0, width - endX, height);

    ctx.strokeStyle = '#4caf50';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();
    ctx.fillStyle = '#4caf50';
    ctx.fillRect(startX - 4, height / 2 - 10, 8, 20);

    ctx.strokeStyle = '#f44336';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(endX, 0);
    ctx.lineTo(endX, height);
    ctx.stroke();
    ctx.fillStyle = '#f44336';
    ctx.fillRect(endX - 4, height / 2 - 10, 8, 20);
}

function setupTrimDragHandles(canvas, seg) {
    let dragging = null;
    let didDrag = false;
    const HANDLE_THRESHOLD = 12;

    function _getHandleXs() {
        const tw = canvas._trimWindow, w = canvas.width;
        return {
            startX: ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
            endX: ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
        };
    }

    function onMousedown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const { startX, endX } = _getHandleXs();
        didDrag = false;

        if (Math.abs(x - startX) < HANDLE_THRESHOLD) dragging = 'start';
        else if (Math.abs(x - endX) < HANDLE_THRESHOLD) dragging = 'end';
        if (dragging) canvas.style.cursor = 'col-resize';
    }

    function onMousemove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const tw = canvas._trimWindow;
        const width = canvas.width;

        if (!dragging) {
            const { startX, endX } = _getHandleXs();
            canvas.style.cursor = (Math.abs(x - startX) < HANDLE_THRESHOLD || Math.abs(x - endX) < HANDLE_THRESHOLD) ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        const timeAtX = tw.windowStart + (x / width) * (tw.windowEnd - tw.windowStart);
        const snapped = Math.round(timeAtX / 10) * 10;

        if (dragging === 'start') {
            tw.currentStart = Math.max(tw.windowStart, Math.min(snapped, tw.currentEnd - 50));
        } else {
            tw.currentEnd = Math.max(tw.currentStart + 50, Math.min(snapped, tw.windowEnd));
        }
        updateTrimDuration(canvas);
        drawTrimWaveform(canvas);
    }

    function onMouseup(e) {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const tw = canvas._trimWindow;
            const timeAtX = tw.windowStart + (x / canvas.width) * (tw.windowEnd - tw.windowStart);
            const snapped = Math.round(timeAtX / 10) * 10;
            _playRange(snapped, tw.currentEnd);
        }
        dragging = null;
        canvas.style.cursor = '';
    }
    function onMouseleave() { dragging = null; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = () => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

function updateTrimDuration(canvas) {
    canvas = canvas || _getEditCanvas();
    const tw = canvas?._trimWindow;
    const el = canvas?._trimEls?.durationSpan;
    if (!tw || !el) return;
    el.textContent = `${((tw.currentEnd - tw.currentStart) / 1000).toFixed(2)}s`;
}

function confirmTrim(seg) {
    const canvas = _getEditCanvas();
    const tw = canvas?._trimWindow;
    const trimStatus = canvas?._trimEls?.statusSpan || null;
    const newStart = tw?.currentStart;
    const newEnd = tw?.currentEnd;
    if (newStart == null || newEnd == null || newStart >= newEnd) {
        if (trimStatus) trimStatus.textContent = 'Invalid time range';
        return;
    }

    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const chapterSegs = chapter === currentChapter ? _getChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevSeg = segIdx > 0 ? chapterSegs[segIdx - 1] : null;
    const nextSeg = (segIdx >= 0 && segIdx < chapterSegs.length - 1) ? chapterSegs[segIdx + 1] : null;

    if (prevSeg && prevSeg.audio_url === seg.audio_url && newStart < prevSeg.time_end) {
        if (trimStatus) trimStatus.textContent = 'Start overlaps with previous segment';
        return;
    }
    if (nextSeg && nextSeg.audio_url === seg.audio_url && newEnd > nextSeg.time_start) {
        if (trimStatus) trimStatus.textContent = 'End overlaps with next segment';
        return;
    }

    seg.time_start = newStart;
    seg.time_end = newEnd;
    seg.confidence = 1.0;
    if (state._pendingOp?.op_context_category) {
        if (!seg.ignored_categories) seg.ignored_categories = [];
        if (!seg.ignored_categories.includes(state._pendingOp.op_context_category))
            seg.ignored_categories.push(state._pendingOp.op_context_category);
    }
    markDirty(chapter, undefined, true);

    const trimOp = state._pendingOp;
    state._pendingOp = null;
    if (trimOp) {
        trimOp.applied_at_utc = new Date().toISOString();
        trimOp.targets_after = [snapshotSeg(seg)];
    }

    if (chapter !== currentChapter || !state.segData?.segments) {
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    } else {
        syncChapterSegsToAll();
    }

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();
    syncAllCardsForSegment(seg);

    if (trimOp) finalizeOp(chapter, trimOp);

    dom.segPlayStatus.textContent = 'Adjusted (unsaved)';
}

function previewTrimAudio() {
    const canvas = _getEditCanvas();
    const tw = canvas?._trimWindow;
    if (!tw) return;
    if (state._previewLooping && !dom.segAudioEl.paused) {
        state._previewLooping = false;
        state._previewJustSeeked = false;
        dom.segAudioEl.pause();
        if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
        if (canvas._trimWindow) drawTrimWaveform(canvas);
        return;
    }
    state._previewLooping = 'trim';
    _playRange(tw.currentStart, tw.currentEnd);
}

function _playRange(startMs, endMs) {
    if (state._previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', state._previewStopHandler);
        state._previewStopHandler = null;
    }
    if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = _getEditCanvas();

    let wfStart, wfEnd;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = () => {
        if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
        if (canvas?._splitData) drawSplitWaveform(canvas);
        else if (canvas?._trimWindow) drawTrimWaveform(canvas);
    };

    const inEditMode = canvas && (canvas._splitData || canvas._trimWindow);
    let _playRangeSnapshot = null;
    if (canvas && !inEditMode) {
        _playRangeSnapshot = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
    }

    function animatePlayhead() {
        if (!canvas || dom.segAudioEl.paused) return;
        const curMs = dom.segAudioEl.currentTime * 1000;
        let effectiveEnd = endMs;
        let loopStart = null;
        if (state._previewLooping === 'trim' && canvas?._trimWindow) {
            effectiveEnd = canvas._trimWindow.currentEnd;
            loopStart = canvas._trimWindow.currentStart;
        } else if (state._previewLooping === 'split-left' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.currentSplit;
            loopStart = canvas._splitData.seg.time_start;
        } else if (state._previewLooping === 'split-right' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.seg.time_end;
            loopStart = canvas._splitData.currentSplit;
        } else if (canvas?._splitData && endMs !== canvas._splitData.seg.time_end) {
            effectiveEnd = canvas._splitData.currentSplit;
        }
        if (state._previewJustSeeked && curMs < effectiveEnd) {
            state._previewJustSeeked = false;
        }
        if (curMs >= effectiveEnd && !state._previewJustSeeked) {
            if (state._previewLooping && loopStart !== null) {
                dom.segAudioEl.currentTime = loopStart / 1000;
                state._previewJustSeeked = true;
                state._playRangeRAF = requestAnimationFrame(animatePlayhead);
                return;
            }
            dom.segAudioEl.pause();
            cleanup();
            return;
        }
        if (canvas._splitData) drawSplitWaveform(canvas);
        else if (canvas._trimWindow) drawTrimWaveform(canvas);
        else if (_playRangeSnapshot) {
            canvas.getContext('2d').putImageData(_playRangeSnapshot, 0, 0);
        }
        if (curMs >= wfStart && curMs <= wfEnd) {
            const ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
            const x = ((curMs - wfStart) / (wfEnd - wfStart)) * w;
            ctx.strokeStyle = '#f72585'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = '#f72585';
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        state._playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = () => {
        dom.segAudioEl.currentTime = start;
        dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
        dom.segAudioEl.play();
        state._playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    const targetUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null;
                     const s = ch != null ? getSegByChapterIndex(ch, state.segEditIndex) : null;
                     return s && s.audio_url; })();
    if (targetUrl && !dom.segAudioEl.src.endsWith(targetUrl)) {
        dom.segAudioEl.src = targetUrl;
        dom.segAudioEl.addEventListener('canplay', doPlay, { once: true });
        dom.segAudioEl.load();
    } else if (dom.segAudioEl.src && dom.segAudioEl.readyState >= 1) {
        doPlay();
    } else if (targetUrl) {
        dom.segAudioEl.src = targetUrl;
        dom.segAudioEl.addEventListener('canplay', doPlay, { once: true });
        dom.segAudioEl.load();
    }
}

function previewSplitAudio(side) {
    const canvas = _getEditCanvas();
    const sd = canvas?._splitData;
    if (!sd) return;
    const loopKey = `split-${side}`;
    if (state._previewLooping === loopKey && !dom.segAudioEl.paused) {
        state._previewLooping = false;
        state._previewJustSeeked = false;
        dom.segAudioEl.pause();
        if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
        if (canvas._splitData) drawSplitWaveform(canvas);
        return;
    }
    state._previewLooping = loopKey;
    const splitTime = sd.currentSplit;
    _playRange(
        side === 'left' ? sd.seg.time_start : splitTime,
        side === 'left' ? splitTime : sd.seg.time_end
    );
}

// ---------------------------------------------------------------------------
// Split mode
// ---------------------------------------------------------------------------

function enterSplitMode(seg, row, prePausePlayMs = null) {
    if (state.segEditMode) {
        console.warn('[split] blocked: already in edit mode:', state.segEditMode);
        return;
    }
    state.segEditMode = 'split';
    state.segEditIndex = seg.index;

    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    const actions = row.querySelector('.seg-actions');
    if (actions) actions.hidden = true;

    const canvas = row.querySelector('canvas');
    const segLeft = row.querySelector('.seg-left');

    const mid = Math.round((seg.time_start + seg.time_end) / 2);
    const defaultSplit = (prePausePlayMs !== null && prePausePlayMs > seg.time_start && prePausePlayMs < seg.time_end)
        ? Math.round(prePausePlayMs)
        : mid;

    const inline = document.createElement('div');
    inline.className = 'seg-edit-inline';

    const infoSpan = document.createElement('span');
    infoSpan.className = 'seg-edit-info';
    infoSpan.textContent = `L ${((defaultSplit - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - defaultSplit) / 1000).toFixed(2)}s`;

    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    const mkBtn = (text, cls, fn) => { const b = document.createElement('button'); b.className = `btn btn-sm ${cls}`; b.textContent = text; b.addEventListener('click', fn); return b; };
    btnRow.appendChild(mkBtn('Cancel', 'btn-cancel', exitEditMode));
    btnRow.appendChild(mkBtn('Play Left', 'btn-preview', () => previewSplitAudio('left')));
    btnRow.appendChild(mkBtn('Play Right', 'btn-preview', () => previewSplitAudio('right')));
    btnRow.appendChild(mkBtn('Split', 'btn-confirm', () => confirmSplit(seg)));
    btnRow.appendChild(infoSpan);
    inline.appendChild(btnRow);

    segLeft.appendChild(inline);

    canvas._splitEls = { infoSpan };
    canvas._wfCache = null;

    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const splitAudioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    canvas._splitData = { seg, currentSplit: defaultSplit, audioUrl: splitAudioUrl };
    canvas._splitBaseCache = null;
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);
}

function _ensureSplitBaseCache(canvas) {
    if (canvas._splitBaseCache) return true;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const sd = canvas._splitData;
    const seg = sd.seg;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    const audioUrl = sd.audioUrl || '';
    const data = _slicePeaks(audioUrl, seg.time_start, seg.time_end, width);
    if (!data) {
        ctx.fillStyle = '#888';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No waveform data', width / 2, height / 2);
        return false;
    }

    const scale = height / 2 * 0.9;

    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - data.minVals[i] * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    ctx.stroke();

    canvas._splitBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

function drawSplitWaveform(canvas) {
    const hasCachedBase = _ensureSplitBaseCache(canvas);
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const sd = canvas._splitData;
    const seg = sd.seg;

    if (hasCachedBase) ctx.putImageData(canvas._splitBaseCache, 0, 0);

    const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * width;

    ctx.fillStyle = 'rgba(255, 152, 0, 0.15)';
    ctx.fillRect(splitX, 0, width - splitX, height);

    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(splitX, 0);
    ctx.lineTo(splitX, height);
    ctx.stroke();
    ctx.fillStyle = '#ffeb3b';
    ctx.beginPath();
    ctx.moveTo(splitX - 6, 0);
    ctx.lineTo(splitX + 6, 0);
    ctx.lineTo(splitX, 8);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(splitX - 6, height);
    ctx.lineTo(splitX + 6, height);
    ctx.lineTo(splitX, height - 8);
    ctx.closePath();
    ctx.fill();
}

function setupSplitDragHandle(canvas, seg) {
    let dragging = false;
    let didDrag = false;

    function onMousedown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;
        didDrag = false;
        if (Math.abs(x - splitX) < 15) {
            dragging = true;
            canvas.style.cursor = 'col-resize';
        }
    }

    function onMousemove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;

        if (!dragging) {
            canvas.style.cursor = Math.abs(x - splitX) < 15 ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
        const snapped = Math.round(timeAtX / 10) * 10;
        sd.currentSplit = Math.max(seg.time_start + 50, Math.min(snapped, seg.time_end - 50));
        updateSplitInfo(canvas, seg, sd.currentSplit);
        drawSplitWaveform(canvas);
    }

    function onMouseup(e) {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const sd = canvas._splitData;
            const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
            if (timeAtX < sd.currentSplit) {
                _playRange(timeAtX, sd.currentSplit);
            } else {
                _playRange(timeAtX, seg.time_end);
            }
        }
        dragging = false;
        canvas.style.cursor = '';
    }
    function onMouseleave() { dragging = false; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = () => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

function updateSplitInfo(canvas, seg, splitTime) {
    canvas = canvas || _getEditCanvas();
    const el = canvas?._splitEls?.infoSpan;
    if (el) {
        el.textContent = `L ${((splitTime - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - splitTime) / 1000).toFixed(2)}s`;
    }
}

function confirmSplit(seg) {
    const canvas = _getEditCanvas();
    const splitTime = canvas?._splitData?.currentSplit;
    if (splitTime == null || splitTime <= seg.time_start || splitTime >= seg.time_end) {
        dom.segPlayStatus.textContent = 'Invalid split point';
        return;
    }

    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const useSegData = chapter === currentChapter && state.segData?.segments;

    const firstHalf = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        time_end: splitTime,
    };
    const secondHalf = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        index: seg.index + 1,
        time_start: splitTime,
    };

    const splitOp = state._pendingOp;
    state._pendingOp = null;
    if (splitOp) {
        splitOp.applied_at_utc = new Date().toISOString();
        splitOp.targets_after = [snapshotSeg(firstHalf), snapshotSeg(secondHalf)];
    }

    if (useSegData) {
        const segIdx = state.segData.segments.findIndex(s => s.index === seg.index);
        state.segData.segments.splice(segIdx, 1, firstHalf, secondHalf);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        state.segData.segments = getChapterSegments(chapter);
    } else {
        const globalIdx = state.segAllData.segments.indexOf(seg);
        if (globalIdx !== -1) {
            state.segAllData.segments.splice(globalIdx, 1, firstHalf, secondHalf);
        }
        let reIdx = 0;
        state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForSplit(chapter, seg.index);

    const accCtx = state._accordionOpCtx;
    state._accordionOpCtx = null;

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();

    if (accCtx) {
        _rebuildAccordionAfterSplit(accCtx.wrapper, chapter, seg, firstHalf, secondHalf);
    } else {
        refreshOpenAccordionCards();
    }

    if (splitOp) finalizeOp(chapter, splitOp);

    dom.segPlayStatus.textContent = 'Split \u2014 edit first half reference, then second';

    state._splitChainUid = secondHalf.segment_uid;
    state._splitChainCategory = splitOp?.op_context_category || null;
    state._splitChainWrapper = accCtx ? accCtx.wrapper : null;
    const searchRoot = accCtx ? accCtx.wrapper : dom.segListEl;
    const firstRow = searchRoot.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${firstHalf.index}"]`);
    if (firstRow) {
        firstRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const refSpan = firstRow.querySelector('.seg-text-ref');
        if (refSpan) {
            startRefEdit(refSpan, firstHalf, firstRow, state._splitChainCategory);
        }
    }
}


// ---------------------------------------------------------------------------
// Merge
// ---------------------------------------------------------------------------

async function mergeAdjacent(seg, direction, contextCategory = null) {
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);

    let chapterSegs;
    if (chapter === currentChapter && state.segData?.segments) {
        chapterSegs = state.segData.segments;
    } else if (state.segAllData?.segments) {
        chapterSegs = getChapterSegments(chapter);
    }
    if (!chapterSegs) return;

    const idx = chapterSegs.findIndex(s => s.index === seg.index);
    if (idx === -1) return;
    const otherIdx = direction === 'prev' ? idx - 1 : idx + 1;
    if (otherIdx < 0 || otherIdx >= chapterSegs.length) return;
    const other = chapterSegs[otherIdx];

    const first = direction === 'prev' ? other : seg;
    const second = direction === 'prev' ? seg : other;

    const mergeOp = createOp('merge_segments', contextCategory ? { contextCategory } : undefined);
    mergeOp.merge_direction = direction;
    mergeOp.targets_before = [snapshotSeg(first), snapshotSeg(second)];

    const firstAudio = first.audio_url || '';
    const secondAudio = second.audio_url || '';
    if (firstAudio !== secondAudio) return;

    let mergedRef = '';
    const refs = [first.matched_ref, second.matched_ref].filter(Boolean);
    if (refs.length > 0) {
        const s = refs[0].includes('-') ? refs[0].split('-')[0] : refs[0];
        const e = refs[refs.length - 1].includes('-') ? refs[refs.length - 1].split('-')[1] : refs[refs.length - 1];
        mergedRef = `${s}-${e}`;
    }

    let mergedText = [first.matched_text, second.matched_text].filter(Boolean).join(' ');
    let mergedDisplay = [first.display_text, second.display_text].filter(Boolean).join(' ');
    if (mergedRef) {
        try {
            const resp = await fetch(`/api/seg/resolve_ref?ref=${encodeURIComponent(mergedRef)}`);
            const data = await resp.json();
            if (data.text) {
                mergedText = data.text;
                mergedDisplay = data.display_text || data.text;
            }
        } catch (e) {
            console.warn('Failed to resolve merged ref, using concatenated text:', e);
        }
    }

    const merged = {
        ...first,
        segment_uid: crypto.randomUUID(),
        index: first.index,
        time_start: first.time_start,
        time_end: second.time_end,
        matched_ref: mergedRef,
        matched_text: mergedText,
        display_text: mergedDisplay,
        confidence: 1.0,
    };
    const mergedIc = new Set([
        ...(first.ignored_categories || []),
        ...(second.ignored_categories || []),
    ]);
    if (contextCategory) mergedIc.add(contextCategory);
    if (mergedIc.size) merged.ignored_categories = [...mergedIc];

    mergeOp.applied_at_utc = new Date().toISOString();
    mergeOp.targets_after = [snapshotSeg(merged)];

    const keptOldIdx = first.index;
    const consumedOldIdx = second.index;

    if (chapter === currentChapter && state.segData?.segments) {
        const spliceIdx = Math.min(idx, otherIdx);
        state.segData.segments.splice(spliceIdx, 2, merged);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (state.segAllData?.segments) {
        const globalFirst = state.segAllData.segments.indexOf(first);
        const globalSecond = state.segAllData.segments.indexOf(second);
        const spliceStart = Math.min(globalFirst, globalSecond);
        state.segAllData.segments.splice(spliceStart, 2, merged);
        let reIdx = 0;
        state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForMerge(chapter, keptOldIdx, consumedOldIdx);
    if (chapter === currentChapter && state.segData) {
        state.segData.segments = getChapterSegments(chapter);
    }
    computeSilenceAfter();
    applyVerseFilterAndRender();

    const accCtx = state._accordionOpCtx;
    state._accordionOpCtx = null;
    const accCategory = accCtx?.wrapper?.closest('details[data-category]')?.dataset?.category;

    refreshOpenAccordionCards();

    if (accCtx && accCategory) {
        const freshDetails = document.querySelector(`details[data-category="${accCategory}"]`);
        const mergedCard = freshDetails?.querySelector(`.seg-row[data-seg-uid="${merged.segment_uid}"]`);
        const freshWrapper = mergedCard?.closest('.val-card-wrapper');
        if (freshWrapper) {
            _rebuildAccordionAfterMerge(freshWrapper, chapter, merged, accCtx.direction);
        }
    }

    finalizeOp(chapter, mergeOp);
    dom.segPlayStatus.textContent = 'Segments merged (unsaved)';
}


// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

function deleteSegment(seg, row, contextCategory = null) {
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const label = seg.chapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const deleteOp = createOp('delete_segment', contextCategory ? { contextCategory } : undefined);
    deleteOp.targets_before = [snapshotSeg(seg)];

    if (!confirm(`Delete segment ${label} (${formatRef(seg.matched_ref) || 'no match'})?`)) return;

    deleteOp.applied_at_utc = new Date().toISOString();
    deleteOp.targets_after = [];

    if (chapter === currentChapter && state.segData?.segments) {
        const segIdx = state.segData.segments.findIndex(s => s.index === seg.index);
        if (segIdx === -1) return;
        state.segData.segments.splice(segIdx, 1);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (state.segAllData?.segments) {
        const globalIdx = state.segAllData.segments.findIndex(s => s.chapter === chapter && s.index === seg.index);
        if (globalIdx === -1) return;
        state.segAllData.segments.splice(globalIdx, 1);
        let idx = 0;
        state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = idx++; });
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForDelete(chapter, seg.index);

    if (chapter === currentChapter && state.segData) {
        state.segData.segments = getChapterSegments(chapter);
    }

    computeSilenceAfter();
    applyVerseFilterAndRender();
    refreshOpenAccordionCards();

    finalizeOp(chapter, deleteOp);
    dom.segPlayStatus.textContent = 'Segment deleted (unsaved)';
}


// ---------------------------------------------------------------------------
// Shared edit mode
// ---------------------------------------------------------------------------

function exitEditMode() {
    state._pendingOp = null;
    state._accordionOpCtx = null;

    const editRow = document.querySelector('.seg-row.seg-edit-target');
    if (editRow) {
        editRow.querySelector('.seg-edit-inline')?.remove();
        const actions = editRow.querySelector('.seg-actions');
        if (actions) actions.hidden = false;
        const playCol = editRow.querySelector('.seg-play-col');
        if (playCol) playCol.hidden = false;

        const canvas = editRow.querySelector('canvas');
        if (canvas) {
            canvas._editCleanup?.();
            delete canvas._trimWindow; delete canvas._splitData;
            delete canvas._trimEls; delete canvas._splitEls;
            delete canvas._editCleanup;
            canvas._wfCache = null;
            canvas.style.cursor = '';
            const seg = resolveSegFromRow(editRow);
            if (seg) drawWaveformFromPeaksForSeg(canvas, seg, seg.chapter);
        }
    }

    state.segEditMode = null;
    state.segEditIndex = -1;
    state._previewLooping = false;
    state._previewJustSeeked = false;
    if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
    if (state._previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', state._previewStopHandler);
        state._previewStopHandler = null;
    }
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    document.body.classList.remove('seg-edit-active');
    editRow?.classList.remove('seg-edit-target');
}


// =====================================================================
// VALIDATION PANEL, ERROR CARDS, STATS, EDIT HISTORY
// (Phase 8 code -- kept in segments.js for now)
// =====================================================================

// The remaining ~2800 lines of validation panel, error cards, stats panel,
// and edit history code are kept inline below. They reference all the
// imported functions from the extracted modules.

// Re-export the full set of validation/stats/history functions that were
// in the original file. These are passed to registerSegHandlers above.

function captureValPanelState(targetEl) {
    const st = {};
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        st[d.getAttribute('data-category')] = { open: d.open };
    });
    return st;
}

function restoreValPanelState(targetEl, st) {
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        const s = st[d.getAttribute('data-category')];
        if (s && s.open) d.open = true;
    });
}

function _collapseAccordionExcept(exceptDetails) {
    const panel = exceptDetails.closest('#seg-validation-global, #seg-validation') || exceptDetails.parentElement;
    panel.querySelectorAll('details[data-category]').forEach(d => {
        if (d === exceptDetails) return;
        if (d.open) d.open = false;
    });
}

function renderValidationPanel(data, chapter = null, targetEl = dom.segValidationEl, label = null) {
    targetEl.innerHTML = '';
    if (!data) { targetEl.hidden = true; return; }

    let { errors: errs, missing_verses: mv, missing_words: mw, failed, low_confidence, boundary_adj: ba, cross_verse: cv, audio_bleeding: ab, repetitions: rep, muqattaat, qalqala } = data;

    if (chapter !== null) {
        errs           = (errs           || []).filter(i => i.chapter === chapter);
        mv             = (mv             || []).filter(i => i.chapter === chapter);
        mw             = (mw             || []).filter(i => i.chapter === chapter);
        failed         = (failed         || []).filter(i => i.chapter === chapter);
        low_confidence = (low_confidence || []).filter(i => i.chapter === chapter);
        ba             = (ba             || []).filter(i => i.chapter === chapter);
        cv             = (cv             || []).filter(i => i.chapter === chapter);
        ab             = (ab             || []).filter(i => i.chapter === chapter);
        rep            = (rep            || []).filter(i => i.chapter === chapter);
        muqattaat      = (muqattaat      || []).filter(i => i.chapter === chapter);
        qalqala        = (qalqala        || []).filter(i => i.chapter === chapter);
    }
    const hasAny = (errs && errs.length > 0) || (mv && mv.length > 0) || (mw && mw.length > 0)
        || (failed && failed.length > 0) || (low_confidence && low_confidence.length > 0) || (ba && ba.length > 0)
        || (cv && cv.length > 0) || (ab && ab.length > 0) || (rep && rep.length > 0)
        || (muqattaat && muqattaat.length > 0) || (qalqala && qalqala.length > 0);
    if (!hasAny) {
        targetEl.hidden = true;
        return;
    }
    targetEl.hidden = false;

    if (label) {
        const labelEl = document.createElement('div');
        labelEl.className = 'val-section-label';
        labelEl.textContent = label;
        targetEl.appendChild(labelEl);
    }

    // NOTE: The full validation panel rendering code (categories array, accordion toggles,
    // slider, qalqala filter, card rendering, etc.) is kept exactly as in the original.
    // For brevity in this extraction, we delegate to the original implementation below.
    // The code from lines 4325-4572 of the original file is preserved identically.
    // Due to the massive size, the remaining ~2500 lines of validation/stats/history
    // are preserved in this file as-is. They will be extracted in Phase 8.

    const isGlobal = chapter === null;

    const categories = [
        {
            name: 'Failed Alignments', items: failed, type: 'failed', countClass: 'has-errors',
            getLabel: i => `${i.chapter}:#${i.seg_index}`, getTitle: i => `${i.time}`, btnClass: 'val-error',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Missing Verses', items: mv, type: 'missing_verses', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToMissingVerseContext(i.chapter, i.verse_key)
        },
        {
            name: 'Missing Words', items: mw, type: 'missing_words', countClass: 'has-errors',
            getLabel: i => {
                const indices = i.seg_indices || [];
                return indices.length > 0 ? `${i.verse_key} #${indices.join('/#')}` : i.verse_key;
            },
            getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => {
                const indices = i.seg_indices || [];
                if (indices.length > 0) jumpToSegment(i.chapter, indices[0]);
                else jumpToVerse(i.chapter, i.verse_key);
            }
        },
        {
            name: 'Structural Errors', items: errs, type: 'errors', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToVerse(i.chapter, i.verse_key)
        },
        {
            name: 'Detected Repetitions', items: rep, type: 'repetitions', countClass: 'val-rep-count',
            getLabel: i => i.display_ref || i.ref, getTitle: i => i.text, btnClass: 'val-rep',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Low Confidence', items: low_confidence, type: 'low_confidence', countClass: 'has-warnings',
            getLabel: i => i.ref, getTitle: i => `${(i.confidence * 100).toFixed(1)}%`,
            btnClass: i => i.confidence < 0.60 ? 'val-conf-low' : 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'May Require Boundary Adjustment', items: ba, type: 'boundary_adj', countClass: 'has-warnings',
            getLabel: i => i.ref, getTitle: i => i.verse_key, btnClass: 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Cross-verse', items: cv, type: 'cross_verse', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Audio Bleeding', items: ab, type: 'audio_bleeding', countClass: 'has-warnings',
            getLabel: i => `${i.entry_ref}\u2192${i.matched_verse}`,
            getTitle: i => `audio ${i.entry_ref} contains segment matching ${i.ref} (${i.time})`,
            btnClass: 'val-bleed',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Muqatta\u02bcat', items: muqattaat || [], type: 'muqattaat', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Qalqala', items: qalqala || [], type: 'qalqala', countClass: 'val-cross-count',
            isQalqala: true,
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
    ];

    const QALQALA_LETTERS_ORDER = ['\u0642', '\u0637', '\u0628', '\u062c', '\u062f'];

    categories.forEach(cat => {
        if (!cat.items || cat.items.length === 0) return;

        const isLowConf = cat.type === 'low_confidence';
        const isQalqala = !!cat.isQalqala;
        const LC_DEFAULT = state._lcDefaultThreshold;

        let lcThreshold = LC_DEFAULT;
        let activeQalqalaLetter = null;
        const getVisibleItems = () => {
            if (isLowConf) return cat.items.filter(i => (i.confidence * 100) < lcThreshold).sort((a, b) => a.confidence - b.confidence);
            if (isQalqala && activeQalqalaLetter) return cat.items.filter(i => i.qalqala_letter === activeQalqalaLetter);
            return cat.items;
        };

        const details = document.createElement('details');
        details.setAttribute('data-category', cat.type);
        details._valCatType = cat.type;
        details._valCatItems = cat.items;
        const summary = document.createElement('summary');
        const countForSummary = isLowConf ? cat.items.filter(i => (i.confidence * 100) < LC_DEFAULT).length : cat.items.length;
        summary.innerHTML = `${cat.name} <span class="val-count ${cat.countClass}" data-lc-count>${countForSummary}</span>`;

        details.appendChild(summary);

        let sliderRow = null;
        if (isLowConf) {
            sliderRow = document.createElement('div');
            sliderRow.className = 'lc-slider-row';
            sliderRow.hidden = true;
            sliderRow.innerHTML = `<label class="lc-slider-label">Show confidence &lt; <span class="lc-slider-val">${LC_DEFAULT}%</span></label><input type="range" class="lc-slider" min="50" max="99" step="1" value="${LC_DEFAULT}">`;
            details.appendChild(sliderRow);
        }

        let qalqalaFilterRow = null;
        if (isQalqala) {
            qalqalaFilterRow = document.createElement('div');
            qalqalaFilterRow.className = 'lc-slider-row qalqala-filter-row';
            qalqalaFilterRow.hidden = true;
            const filterLabel = document.createElement('span');
            filterLabel.className = 'lc-slider-label';
            filterLabel.textContent = 'Filter by letter:';
            qalqalaFilterRow.appendChild(filterLabel);
            QALQALA_LETTERS_ORDER.forEach(letter => {
                if (!cat.items.some(i => i.qalqala_letter === letter)) return;
                const btn = document.createElement('button');
                btn.className = 'val-btn val-cross qalqala-letter-btn';
                btn.textContent = letter;
                btn.title = `Show only segments ending with ${letter}`;
                btn.setAttribute('data-letter', letter);
                btn.addEventListener('click', () => {
                    const countEl = summary.querySelector('[data-lc-count]');
                    if (activeQalqalaLetter === letter) {
                        activeQalqalaLetter = null;
                        btn.classList.remove('active');
                    } else {
                        activeQalqalaLetter = letter;
                        qalqalaFilterRow.querySelectorAll('.qalqala-letter-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                    }
                    const visible = getVisibleItems();
                    if (countEl) countEl.textContent = visible.length;
                    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                    cardsDiv.innerHTML = '';
                    renderCategoryCards(cat.type, visible, cardsDiv);
                    requestAnimationFrame(_updateCtxAllBtn);
                });
                qalqalaFilterRow.appendChild(btn);
            });
            details.appendChild(qalqalaFilterRow);
        }

        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        itemsDiv.hidden = true;
        if (isQalqala) itemsDiv.style.display = 'none';

        const rebuildButtons = (items) => {
            itemsDiv.innerHTML = '';
            items.forEach(issue => {
                const btn = document.createElement('button');
                const cls = typeof cat.btnClass === 'function' ? cat.btnClass(issue) : cat.btnClass;
                btn.className = `val-btn ${cls}`;
                btn.textContent = cat.getLabel(issue);
                btn.title = cat.getTitle(issue) || '';
                btn.addEventListener('click', () => cat.onClick(issue));
                itemsDiv.appendChild(btn);
            });
        };
        rebuildButtons(getVisibleItems());
        details.appendChild(itemsDiv);

        const cardsDiv = document.createElement('div');
        cardsDiv.className = 'val-cards-container';
        cardsDiv.hidden = true;

        const _ctxDefaultShown = cat.type === 'failed' || cat.type === 'boundary_adj' || cat.type === 'audio_bleeding' || cat.type === 'repetitions' || cat.type === 'qalqala';
        const ctxAllRow = document.createElement('div');
        ctxAllRow.className = 'val-ctx-all-row';
        ctxAllRow.hidden = true;
        const ctxAllBtn = document.createElement('button');
        ctxAllBtn.className = 'val-action-btn val-action-btn-muted';
        ctxAllBtn.textContent = _ctxDefaultShown ? 'Hide All Context' : 'Show All Context';
        ctxAllRow.appendChild(ctxAllBtn);
        details.appendChild(ctxAllRow);

        function _updateCtxAllBtn() {
            const anyShown = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')].some(b => b._isContextShown && b._isContextShown());
            ctxAllBtn.textContent = anyShown ? 'Hide All Context' : 'Show All Context';
        }
        ctxAllBtn.addEventListener('click', () => {
            const allBtns = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')];
            const anyShown = allBtns.some(b => b._isContextShown && b._isContextShown());
            allBtns.forEach(b => {
                if (anyShown && b._isContextShown && b._isContextShown()) b.click();
                else if (!anyShown && b._showContext && !b._isContextShown()) b.click();
            });
            _updateCtxAllBtn();
        });

        details.appendChild(cardsDiv);

        if (isLowConf && sliderRow) {
            const sliderEl = sliderRow.querySelector('.lc-slider');
            const sliderValEl = sliderRow.querySelector('.lc-slider-val');
            const countEl = summary.querySelector('[data-lc-count]');
            sliderEl.addEventListener('input', () => {
                lcThreshold = parseInt(sliderEl.value);
                sliderValEl.textContent = `${lcThreshold}%`;
                const visible = getVisibleItems();
                if (countEl) countEl.textContent = visible.length;
                rebuildButtons(visible);
                if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                cardsDiv.innerHTML = '';
                renderCategoryCards(cat.type, visible, cardsDiv);
            });
        }

        details.addEventListener('toggle', () => {
            if (details.open) {
                _collapseAccordionExcept(details);
                if (sliderRow) sliderRow.hidden = false;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = false;
                if (!isQalqala) itemsDiv.hidden = false;
                const visible = getVisibleItems();
                if (!isQalqala) rebuildButtons(visible);
                renderCategoryCards(cat.type, visible, cardsDiv);
                cardsDiv.hidden = false;
                ctxAllRow.hidden = false;
                requestAnimationFrame(_updateCtxAllBtn);
            } else {
                if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
                if (sliderRow) sliderRow.hidden = true;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = true;
                itemsDiv.hidden = true;
                cardsDiv.innerHTML = '';
                cardsDiv.hidden = true;
                ctxAllRow.hidden = true;
            }
        });

        targetEl.appendChild(details);
    });
}

async function refreshValidation() {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    try {
        const globalState = captureValPanelState(dom.segValidationGlobalEl);
        const chState = captureValPanelState(dom.segValidationEl);
        const valResp = await fetch(`/api/seg/validate/${reciter}`);
        state.segValidation = await valResp.json();
        const ch = dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null;
        if (ch !== null) {
            renderValidationPanel(state.segValidation, null, dom.segValidationGlobalEl, 'All Chapters');
            renderValidationPanel(state.segValidation, ch, dom.segValidationEl, `Chapter ${ch}`);
            restoreValPanelState(dom.segValidationGlobalEl, globalState);
            restoreValPanelState(dom.segValidationEl, chState);
        } else {
            dom.segValidationGlobalEl.hidden = true;
            dom.segValidationGlobalEl.innerHTML = '';
            renderValidationPanel(state.segValidation, null, dom.segValidationEl);
            restoreValPanelState(dom.segValidationEl, chState);
        }
        if (state.segData && state.segData.segments) {
            applyFiltersAndRender();
        } else if (state.segDisplayedSegments) {
            renderSegList(state.segDisplayedSegments);
        }
        if (state._segSavedPreviewState) {
            const saved = state._segSavedPreviewState;
            state._segSavedPreviewState = null;
            requestAnimationFrame(() => { dom.segListEl.scrollTop = saved.scrollTop; });
        }
    } catch (e) {
        console.error('Error refreshing validation:', e);
    }
}


// The remaining error cards, stats, and history code is kept in this file.
// Due to the massive size (~2500 lines), it's preserved as-is from the original.
// It will be extracted in Phase 8.

// IMPORTANT: The remaining functions (renderCategoryCards, renderErrorCard, resolveIssueToSegment,
// addContextToggle, ensureContextShown, _isWrapperContextShown, invalidateLoadedErrorCards,
// refreshOpenAccordionCards, _fixupValIndicesForSplit/Merge/Delete, _forEachValItem,
// _rebuildAccordionAfterSplit, _rebuildAccordionAfterMerge, getValCardAudio, stopErrorCardAudio,
// _startValCardAnimation, playErrorCardAudio, renderStatsPanel, _openChartFullscreen, _saveChart,
// _findBinIndex, drawBarChart, showHistoryView, hideHistoryView, _buildSplitLineage,
// _buildSplitChains, _computeChainLeafSnaps, renderSplitChainRow, renderEditHistoryPanel,
// renderHistorySummaryStats, _versesFromRef, _countVersesFromBatches, renderHistoryFilterBar,
// toggleHistoryFilter, applyHistoryFilters, clearHistoryFilters, setHistorySort,
// renderHistoryBatches, _renderHistoryDisplayItems, _flattenBatchesToItems, _renderOpCard,
// renderHistoryOp, renderHistoryGroupedOp, _snapToSeg, _highlightChanges, _appendValDeltas,
// _formatHistDate, _ensureHistArrowDefs, drawHistoryArrows, _drawArrowPath,
// _appendIssueDeltaBadges, _renderSpecialDeleteGroup, _groupRelatedOps,
// _histItemChapter, _histItemTimeStart, _itemMatchesOpFilter, _itemMatchesCatFilter,
// _updateFilterPillCounts, _computeFilteredItemSummary, _countVersesFromItems)
// are ALL still here — they just import their dependencies from the extracted modules.
// The full implementations are preserved from the original segments.js file (lines 4913-7471).
// I'm including stubs/references for the key ones that are registered above.

// --- Error card audio ---

function getValCardAudio() {
    if (!state.valCardAudio) {
        state.valCardAudio = document.createElement('audio');
        state.valCardAudio.addEventListener('timeupdate', () => {
            if (state.valCardStopTime !== null && state.valCardAudio.currentTime >= state.valCardStopTime) {
                stopErrorCardAudio();
            }
        });
        state.valCardAudio.addEventListener('ended', () => { stopErrorCardAudio(); });
        state.valCardAudio.addEventListener('play', () => {
            dom.segPlayBtn.textContent = 'Pause';
            state._activeAudioSource = 'error';
        });
        state.valCardAudio.addEventListener('pause', () => {
            if (dom.segAudioEl.paused) dom.segPlayBtn.textContent = 'Play';
            if (state._activeAudioSource === 'error') state._activeAudioSource = null;
        });
    }
    return state.valCardAudio;
}

function stopErrorCardAudio() {
    if (!state.valCardAudio) return;
    state.valCardAudio.pause();
    state.valCardStopTime = null;
    if (state.valCardPlayingBtn) {
        state.valCardPlayingBtn.textContent = '\u25B6';
        state.valCardPlayingBtn = null;
    }
    if (state._activeAudioSource === 'error') state._activeAudioSource = null;
}

function _startValCardAnimation(btn, seg) {
    if (state.valCardAnimId) cancelAnimationFrame(state.valCardAnimId);
    state.valCardAnimSeg = seg;
    const row = btn.closest('.seg-row');
    const canvas = row ? row.querySelector('canvas') : null;
    if (!canvas) return;
    const chapter = seg.chapter;
    const segAudioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const splitHL = canvas._splitHL;
    const wfStart = splitHL ? splitHL.wfStart : seg.time_start;
    const wfEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;

    function frame() {
        if (state.valCardPlayingBtn !== btn) {
            if (canvas && !canvas._splitData && !canvas._trimWindow) {
                const wfSeg = splitHL ? { ...seg, time_start: wfStart, time_end: wfEnd } : seg;
                drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
                if (splitHL) _drawSplitHighlight(canvas, wfSeg);
            }
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        if (canvas && (canvas._splitData || canvas._trimWindow)) {
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        const timeMs = getValCardAudio().currentTime * 1000;
        if (state.valCardStopTime !== null && getValCardAudio().currentTime >= state.valCardStopTime) {
            stopErrorCardAudio();
            return;
        }
        if (!canvas._wfCache) {
            const cacheKey = `${wfStart}:${wfEnd}`;
            canvas._wfCache = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
            canvas._wfCacheKey = cacheKey;
        }
        drawSegPlayhead(canvas, wfStart, wfEnd, timeMs, segAudioUrl);
        state.valCardAnimId = requestAnimationFrame(frame);
    }
    state.valCardAnimId = requestAnimationFrame(frame);
}

function playErrorCardAudio(seg, btn, seekToMs) {
    const audio = getValCardAudio();
    if (state.valCardPlayingBtn === btn && !audio.paused && seekToMs == null) {
        stopErrorCardAudio();
        return;
    }
    if (!dom.segAudioEl.paused) {
        state._segContinuousPlay = false;
        dom.segAudioEl.pause();
    }
    state._activeAudioSource = 'error';
    if (state.valCardPlayingBtn) state.valCardPlayingBtn.textContent = '\u25B6';
    const audioUrl = seg.audio_url || (state.segAllData && state.segAllData.audio_by_chapter && state.segAllData.audio_by_chapter[seg.chapter]) || '';
    if (!audioUrl) return;
    const seekSec = seekToMs != null ? seekToMs / 1000 : (seg.time_start || 0) / 1000;
    const endSec = (seg.time_end || 0) / 1000;
    if (audio.src !== audioUrl && audio.getAttribute('data-url') !== audioUrl) {
        audio.src = audioUrl;
        audio.setAttribute('data-url', audioUrl);
        audio.addEventListener('loadedmetadata', function onLoad() {
            audio.removeEventListener('loadedmetadata', onLoad);
            audio.currentTime = seekSec;
            state.valCardStopTime = endSec;
            audio.playbackRate = parseFloat(dom.segSpeedSelect.value);
            audio.play();
        });
    } else {
        audio.currentTime = seekSec;
        state.valCardStopTime = endSec;
        audio.playbackRate = parseFloat(dom.segSpeedSelect.value);
        audio.play();
    }
    btn.textContent = '\u23F9';
    state.valCardPlayingBtn = btn;
    _startValCardAnimation(btn, seg);
}

function invalidateLoadedErrorCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (details.open) details.open = false;
    });
}

function refreshOpenAccordionCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (!details.open) return;
        const cardsDiv = details.querySelector('.val-cards-container');
        if (!cardsDiv || !details._valCatItems) return;
        renderCategoryCards(details._valCatType, details._valCatItems, cardsDiv);
    });
}

// --- Validation index fixup ---

function _forEachValItem(chapter, fn) {
    if (!state.segValidation) return;
    for (const cat of state._VAL_SINGLE_INDEX_CATS) {
        const arr = state.segValidation[cat];
        if (!arr) continue;
        for (const item of arr) {
            if (item.chapter === chapter) fn(item, 'seg_index');
        }
    }
    const mw = state.segValidation.missing_words;
    if (mw) {
        for (const item of mw) {
            if (item.chapter !== chapter) continue;
            if (item.seg_indices) {
                for (let i = 0; i < item.seg_indices.length; i++) {
                    const wrapped = { seg_index: item.seg_indices[i] };
                    fn(wrapped, 'seg_index');
                    item.seg_indices[i] = wrapped.seg_index;
                }
            }
            if (item.auto_fix) fn(item.auto_fix, 'target_seg_index');
        }
    }
}

function _fixupValIndicesForSplit(chapter, splitIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] > splitIndex) item[key] += 1;
    });
}

function _fixupValIndicesForMerge(chapter, keptIndex, consumedIndex) {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === consumedIndex) item[key] = keptIndex;
        else if (item[key] > maxIdx) item[key] -= 1;
    });
}

function _fixupValIndicesForDelete(chapter, deletedIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === deletedIndex) item[key] = -1;
        else if (item[key] > deletedIndex) item[key] -= 1;
    });
}

// --- Error card rendering ---

function renderErrorCard(seg, options = {}) {
    const { isContext = false, contextLabel = '', readOnly = false } = options;
    return renderSegCard(seg, {
        showChapter: true,
        showPlayBtn: true,
        showGotoBtn: !isContext && !readOnly,
        isContext,
        contextLabel,
        readOnly,
    });
}

function renderCategoryCards(type, items, container) {
    if (state._cardRenderRafId) { cancelAnimationFrame(state._cardRenderRafId); state._cardRenderRafId = null; }
    container.innerHTML = '';
    if (!state.segAllData || !items || items.length === 0) return;

    const BATCH_SIZE = 30;
    const observer = _ensureWaveformObserver();

    if (state.segPeaksByAudio) {
        const missingChapters = new Set();
        items.forEach(item => {
            const ch = item.chapter;
            if (!ch) return;
            const url = state.segAllData?.audio_by_chapter?.[String(ch)] || '';
            if (url && !state.segPeaksByAudio[url]) missingChapters.add(ch);
        });
        if (missingChapters.size > 0) {
            const reciter = dom.segReciterSelect.value;
            if (reciter) _fetchPeaks(reciter, [...missingChapters]);
        }
    }

    function renderOneItem(issue) {
        if (type === 'missing_words') {
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const gapLabel = document.createElement('div');
            gapLabel.className = 'val-card-gap-label';
            gapLabel.textContent = issue.msg || 'Missing words between segments';
            wrapper.appendChild(gapLabel);
            const indices = issue.seg_indices || [];
            const segsInWrapper = [];
            indices.forEach(idx => {
                const seg = getSegByChapterIndex(issue.chapter, idx);
                if (seg) {
                    const card = renderErrorCard(seg);
                    wrapper.appendChild(card);
                    segsInWrapper.push({ seg, card });
                }
            });
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if (issue.auto_fix) {
                const fixBtn = document.createElement('button');
                fixBtn.className = 'val-action-btn';
                fixBtn.textContent = 'Auto Fix';
                fixBtn.title = 'Extend segment ref to cover the missing word';
                fixBtn.addEventListener('click', async () => {
                    const af = issue.auto_fix;
                    const seg = getSegByChapterIndex(issue.chapter, af.target_seg_index);
                    if (!seg) return;
                    const oldRef = seg.matched_ref || '';
                    const oldText = seg.matched_text || '';
                    const oldDisplay = seg.display_text || '';
                    const oldConf = seg.confidence;
                    const oldIgnoredCats = seg.ignored_categories ? [...seg.ignored_categories] : null;
                    const segChapter = seg.chapter || issue.chapter;
                    const wasDirty = isIndexDirty(segChapter, seg.index);
                    state._pendingOp = createOp('auto_fix_missing_word', { contextCategory: 'missing_words', fixKind: 'auto_fix' });
                    state._pendingOp.targets_before = [snapshotSeg(seg)];
                    const _autoFixOpId = state._pendingOp.op_id;
                    const newRef = `${af.new_ref_start}-${af.new_ref_end}`;
                    const entry = segsInWrapper.find(s => s.seg === seg);
                    const card = entry?.card || wrapper;
                    await commitRefEdit(seg, newRef, card);
                    wrapper.style.opacity = '0.5';
                    fixBtn.disabled = true;
                    fixBtn.textContent = 'Fixed (save to apply)';
                    const undoBtn = document.createElement('button');
                    undoBtn.className = 'val-action-btn val-action-btn-danger';
                    undoBtn.textContent = 'Undo';
                    undoBtn.title = 'Revert auto-fix';
                    undoBtn.addEventListener('click', () => {
                        seg.matched_ref = oldRef;
                        seg.matched_text = oldText;
                        seg.display_text = oldDisplay;
                        seg.confidence = oldConf;
                        if (oldIgnoredCats) seg.ignored_categories = oldIgnoredCats; else delete seg.ignored_categories;
                        if (!wasDirty) unmarkDirty(segChapter, seg.index);
                        fixBtn.disabled = false;
                        fixBtn.textContent = 'Auto Fix';
                        wrapper.style.opacity = '1';
                        syncAllCardsForSegment(seg);
                        undoBtn.remove();
                        dom.segSaveBtn.disabled = !isDirty();
                        const ops = state.segOpLog.get(segChapter);
                        if (ops) { const idx = ops.findIndex(o => o.op_id === _autoFixOpId); if (idx !== -1) ops.splice(idx, 1); }
                    });
                    fixBtn.after(undoBtn);
                });
                actionsRow.appendChild(fixBtn);
            }
            if (segsInWrapper.length > 0) addContextToggle(actionsRow, segsInWrapper);
            wrapper.appendChild(actionsRow);
            container.appendChild(wrapper);
        } else if (type === 'missing_verses') {
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            const msgLabel = document.createElement('div');
            msgLabel.className = 'val-card-issue-label';
            msgLabel.textContent = issue.msg ? `${issue.verse_key} \u2014 ${issue.msg}` : issue.verse_key;
            wrapper.appendChild(msgLabel);
            const { prev, next } = findMissingVerseBoundarySegments(issue.chapter, issue.verse_key);
            const segsInWrapper = [];
            if (prev) { const prevCard = renderErrorCard(prev, { contextLabel: 'Previous verse boundary', readOnly: true }); wrapper.appendChild(prevCard); segsInWrapper.push({ seg: prev, card: prevCard }); }
            if (next && (!prev || next.index !== prev.index)) { const nextCard = renderErrorCard(next, { contextLabel: 'Next verse boundary', readOnly: true }); wrapper.appendChild(nextCard); segsInWrapper.push({ seg: next, card: nextCard }); }
            if (segsInWrapper.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-loading'; empty.textContent = 'No boundary segments found for this missing verse.'; wrapper.appendChild(empty); }
            else { const actionsRow = document.createElement('div'); actionsRow.className = 'val-card-actions'; addContextToggle(actionsRow, segsInWrapper); wrapper.appendChild(actionsRow); }
            container.appendChild(wrapper);
        } else {
            const seg = resolveIssueToSegment(type, issue);
            if (!seg) return;
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';
            if (issue.msg) { const msgLabel = document.createElement('div'); msgLabel.className = 'val-card-issue-label'; msgLabel.textContent = issue.msg; wrapper.appendChild(msgLabel); }
            const card = renderErrorCard(seg);
            wrapper.appendChild(card);
            if (type === 'boundary_adj' && state.SHOW_BOUNDARY_PHONEMES && (issue.gt_tail || issue.asr_tail)) {
                const textBox = card.querySelector('.seg-text');
                if (textBox) { const tailEl = document.createElement('div'); tailEl.className = 'val-phoneme-tail'; const gt = issue.gt_tail || ''; const asr = issue.asr_tail || ''; tailEl.innerHTML = `<span class="val-tail-label">GT:</span> <span class="val-tail-phonemes">${gt}</span>\n<span class="val-tail-label">ASR:</span> <span class="val-tail-phonemes">${asr}</span>`; textBox.appendChild(tailEl); }
            }
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';
            if ((type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala') || (type === 'low_confidence' && seg.confidence < 1.0)) {
                const ignoreBtn = document.createElement('button');
                ignoreBtn.className = 'val-action-btn ignore-btn';
                const segChapterForBtn = seg.chapter || parseInt(dom.segChapterSelect.value);
                const isDirtySegment = state.segDirtyMap.get(segChapterForBtn)?.indices?.has(seg.index);
                if (_isIgnoredFor(seg, type)) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5'; }
                else if (isDirtySegment) { ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Cannot ignore \u2014 this segment already has unsaved edits'; }
                else { ignoreBtn.textContent = 'Ignore'; ignoreBtn.title = 'Dismiss this issue for this category'; }
                ignoreBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (_isIgnoredFor(seg, type)) return;
                    const segChapter = seg.chapter || parseInt(dom.segChapterSelect.value);
                    let ignoreOp;
                    try { ignoreOp = createOp('ignore_issue', { contextCategory: type, fixKind: 'ignore' }); ignoreOp.targets_before = [snapshotSeg(seg)]; ignoreOp.applied_at_utc = ignoreOp.started_at_utc; } catch (err) { console.warn('Ignore: edit history snapshot failed:', err); }
                    if (!seg.ignored_categories) seg.ignored_categories = [];
                    seg.ignored_categories.push(type);
                    delete seg._derived;
                    markDirty(segChapter, seg.index);
                    syncAllCardsForSegment(seg);
                    if (ignoreOp) { try { ignoreOp.targets_after = [snapshotSeg(seg)]; finalizeOp(segChapter, ignoreOp); } catch (err) { console.warn('Ignore: edit history finalize failed:', err); } }
                    ignoreBtn.disabled = true; ignoreBtn.textContent = 'Ignored'; wrapper.style.opacity = '0.5';
                });
                actionsRow.appendChild(ignoreBtn);
            }
            wrapper.appendChild(actionsRow);
            const contextDefault = type === 'failed' || type === 'boundary_adj' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala';
            const nextOnly = type === 'muqattaat' || type === 'qalqala';
            addContextToggle(actionsRow, [{ seg, card }], { defaultOpen: contextDefault, nextOnly });
            container.appendChild(wrapper);
        }
    }

    function processBatch(startIdx) {
        const end = Math.min(startIdx + BATCH_SIZE, items.length);
        for (let i = startIdx; i < end; i++) renderOneItem(items[i]);
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        if (end < items.length) { state._cardRenderRafId = requestAnimationFrame(() => processBatch(end)); }
        else { state._cardRenderRafId = null; }
    }

    processBatch(0);
}

function resolveIssueToSegment(type, issue) {
    if (issue.seg_index != null && issue.seg_index < 0) return null;
    if (type === 'failed' || type === 'low_confidence' || type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'muqattaat' || type === 'qalqala') {
        const seg = getSegByChapterIndex(issue.chapter, issue.seg_index);
        if (seg && issue.ref && seg.matched_ref !== issue.ref) {
            const byRef = getChapterSegments(issue.chapter).find(s => s.matched_ref === issue.ref);
            if (byRef) return byRef;
        }
        return seg;
    }
    if (type === 'errors') {
        const parts = (issue.verse_key || '').split(':');
        const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : issue.verse_key;
        const chapterSegs = getChapterSegments(issue.chapter);
        return chapterSegs.find(s => s.matched_ref && s.matched_ref.startsWith(prefix)) || chapterSegs[0] || null;
    }
    return null;
}

function addContextToggle(actionsContainer, segsInWrapper, { defaultOpen = false, nextOnly = false } = {}) {
    const ctxBtn = document.createElement('button');
    ctxBtn.className = 'val-action-btn val-action-btn-muted val-ctx-toggle-btn';
    ctxBtn.textContent = 'Show Context';
    let contextShown = false;
    let contextEls = [];

    function showContext() {
        const first = segsInWrapper[0];
        const last = segsInWrapper[segsInWrapper.length - 1];
        const cardParent = first.card.parentNode;
        const { prev } = getAdjacentSegments(first.seg.chapter, first.seg.index);
        const { next } = getAdjacentSegments(last.seg.chapter, last.seg.index);
        if (!nextOnly && prev) { const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }); cardParent.insertBefore(prevCard, first.card); contextEls.push(prevCard); }
        if (next) { const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' }); if (last.card.nextSibling) { cardParent.insertBefore(nextCard, last.card.nextSibling); } else { cardParent.insertBefore(nextCard, actionsContainer); } contextEls.push(nextCard); }
        ctxBtn.textContent = 'Hide Context';
        contextShown = true;
    }

    function hideContext() { contextEls.forEach(el => el.remove()); contextEls = []; ctxBtn.textContent = 'Show Context'; contextShown = false; }

    ctxBtn._showContext = showContext;
    ctxBtn._isContextShown = () => contextShown;
    ctxBtn.addEventListener('click', () => { if (contextShown) hideContext(); else showContext(); });
    actionsContainer.appendChild(ctxBtn);
    if (defaultOpen) showContext();
}

function ensureContextShown(row) {
    const wrapper = row.closest('.val-card-wrapper');
    if (!wrapper) return;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return;
    for (const btn of actionsRow.children) {
        if (typeof btn._showContext === 'function') { if (!btn._isContextShown()) btn._showContext(); return; }
    }
}

function _isWrapperContextShown(wrapper) {
    if (!wrapper) return false;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return false;
    for (const btn of actionsRow.children) { if (typeof btn._isContextShown === 'function') return btn._isContextShown(); }
    return false;
}

function _rebuildAccordionAfterSplit(wrapper, chapter, origSeg, firstHalf, secondHalf) {
    const observer = _ensureWaveformObserver();
    const allSegs = state.segAllData?.segments || state.segData?.segments || [];
    wrapper.querySelectorAll('.seg-row-context').forEach(c => c.remove());
    const mainCards = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    const splitCard = mainCards.find(c => (origSeg.segment_uid && c.dataset.segUid === origSeg.segment_uid) || (parseInt(c.dataset.segChapter) === (origSeg.chapter || chapter) && parseInt(c.dataset.segIndex) === origSeg.index));
    if (splitCard) { const f = renderErrorCard(firstHalf); const s = renderErrorCard(secondHalf); wrapper.insertBefore(f, splitCard); wrapper.insertBefore(s, splitCard); splitCard.remove(); [f, s].forEach(c => c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv))); }
    else { const actionsRow = wrapper.querySelector('.val-card-actions'); [renderErrorCard(firstHalf), renderErrorCard(secondHalf)].forEach(c => { actionsRow ? wrapper.insertBefore(c, actionsRow) : wrapper.appendChild(c); c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv)); }); }
    wrapper.querySelectorAll('.seg-row:not(.seg-row-context)').forEach(card => { const uid = card.dataset.segUid; if (!uid) return; const updatedSeg = allSegs.find(s => s.segment_uid === uid); if (updatedSeg) card.dataset.segIndex = updatedSeg.index; });
    const updatedMain = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    if (updatedMain.length === 0) return;
    const firstMainSeg = resolveSegFromRow(updatedMain[0]);
    const lastMainSeg  = resolveSegFromRow(updatedMain[updatedMain.length - 1]);
    if (firstMainSeg) { const { prev } = getAdjacentSegments(firstMainSeg.chapter || chapter, firstMainSeg.index); if (prev) { const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }); wrapper.insertBefore(prevCard, updatedMain[0]); prevCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c)); } }
    if (lastMainSeg) { const { next } = getAdjacentSegments(lastMainSeg.chapter || chapter, lastMainSeg.index); if (next) { const actionsRow = wrapper.querySelector('.val-card-actions'); const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' }); actionsRow ? wrapper.insertBefore(nextCard, actionsRow) : wrapper.appendChild(nextCard); nextCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c)); } }
}

function _rebuildAccordionAfterMerge(wrapper, chapter, merged, direction) {
    const { prev, next } = getAdjacentSegments(merged.chapter || chapter, merged.index);
    const issueLabel = wrapper.querySelector('.val-card-issue-label');
    wrapper.innerHTML = '';
    if (issueLabel) wrapper.appendChild(issueLabel);
    if (direction === 'prev' && next) { wrapper.appendChild(renderErrorCard(merged)); wrapper.appendChild(renderErrorCard(next, { isContext: true, contextLabel: 'Next' })); }
    else if (direction === 'next' && prev) { wrapper.appendChild(renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' })); wrapper.appendChild(renderErrorCard(merged)); }
    else { wrapper.appendChild(renderErrorCard(merged)); }
    const observer = _ensureWaveformObserver();
    wrapper.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
}


// --- Stats Panel ---
// (renderStatsPanel, _openChartFullscreen, _saveChart, _findBinIndex, drawBarChart)
// These are large but purely self-contained. Including them as-is.

function renderStatsPanel(data) {
    if (!data || data.error) return;
    dom.segStatsPanel.hidden = false;
    const vad = data.vad_params;
    const charts = [
        { key: 'pause_duration_ms', title: 'Pause Duration (ms)', refLine: vad.min_silence_ms, refLabel: 'threshold', barColor: (bin) => bin < vad.min_silence_ms ? '#666' : '#4cc9f0', formatBin: v => v >= 3000 ? '3000+' : String(v) },
        { key: 'seg_duration_ms', title: 'Segment Duration (ms)', barColor: (bin) => bin < 1000 ? '#ff9800' : '#4cc9f0', formatBin: v => (v/1000).toFixed(1) + 's', showAllLabels: true },
        { key: 'words_per_seg', title: 'Words Per Segment', barColor: (bin) => bin === 1 ? '#f44336' : '#4cc9f0', formatBin: v => String(v), showAllLabels: true },
        { key: 'segs_per_verse', title: 'Segments Per Verse', barColor: () => '#4cc9f0', formatBin: v => v >= 8 ? '8+' : String(v) },
        { key: 'confidence', title: 'Confidence (%)', barColor: (bin) => bin < 60 ? '#f44336' : bin < 80 ? '#ff9800' : '#4caf50', formatBin: v => v >= 100 ? '100' : String(v) },
    ];
    dom.segStatsCharts.innerHTML = '';
    for (const cfg of charts) {
        const dist = data.distributions[cfg.key];
        if (!dist) continue;
        const wrap = document.createElement('div'); wrap.className = 'seg-stats-chart-wrap';
        const header = document.createElement('div'); header.className = 'seg-stats-chart-header';
        const h4 = document.createElement('h4'); h4.textContent = cfg.title; header.appendChild(h4);
        const btnGroup = document.createElement('span'); btnGroup.className = 'seg-stats-chart-btns';
        const fsBtn = document.createElement('button'); fsBtn.className = 'seg-stats-chart-btn'; fsBtn.title = 'Full screen'; fsBtn.textContent = '\u26F6';
        const saveBtn = document.createElement('button'); saveBtn.className = 'seg-stats-chart-btn'; saveBtn.title = 'Save PNG'; saveBtn.textContent = '\u2B73';
        btnGroup.appendChild(fsBtn); btnGroup.appendChild(saveBtn); header.appendChild(btnGroup); wrap.appendChild(header);
        const canvasWrap = document.createElement('div'); canvasWrap.style.position = 'relative'; canvasWrap.style.width = '100%'; canvasWrap.style.height = '160px';
        const canvas = document.createElement('canvas'); canvasWrap.appendChild(canvas); wrap.appendChild(canvasWrap);
        dom.segStatsCharts.appendChild(wrap);
        drawBarChart(canvas, dist, cfg);
        fsBtn.addEventListener('click', () => _openChartFullscreen(dist, cfg));
        saveBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
    }
}

function _openChartFullscreen(dist, cfg) {
    let overlay = document.getElementById('seg-stats-fullscreen');
    if (!overlay) {
        overlay = document.createElement('div'); overlay.id = 'seg-stats-fullscreen';
        overlay.innerHTML = '<div class="seg-stats-fs-inner"><div class="seg-stats-fs-bar"><span class="seg-stats-fs-title"></span><button class="seg-stats-chart-btn seg-stats-fs-save" title="Save PNG">\u2B73</button><button class="seg-stats-chart-btn seg-stats-fs-close" title="Close">\u2715</button></div><div style="flex:1;min-height:0;position:relative"><canvas></canvas></div></div>';
        document.body.appendChild(overlay);
        overlay.querySelector('.seg-stats-fs-close').addEventListener('click', () => { overlay.style.display = 'none'; });
        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.style.display = 'none'; });
    }
    overlay.style.display = 'flex';
    overlay.querySelector('.seg-stats-fs-title').textContent = cfg.title;
    const canvas = overlay.querySelector('canvas');
    if (canvas._chartInstance) { canvas._chartInstance.destroy(); canvas._chartInstance = null; }
    requestAnimationFrame(() => { drawBarChart(canvas, dist, cfg); });
    const saveBtn = overlay.querySelector('.seg-stats-fs-save');
    const newBtn = saveBtn.cloneNode(true); saveBtn.parentNode.replaceChild(newBtn, saveBtn);
    newBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
}

function _saveChart(canvas, key) {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    canvas.toBlob((blob) => {
        if (!blob) return;
        const fd = new FormData(); fd.append('name', key); fd.append('image', blob, key + '.png');
        fetch(`/api/seg/stats/${encodeURIComponent(reciter)}/save-chart`, { method: 'POST', body: fd })
            .then(r => r.json()).then(data => { if (data.ok) { const tip = document.createElement('span'); tip.className = 'seg-stats-saved-tip'; tip.textContent = 'Saved'; document.body.appendChild(tip); setTimeout(() => tip.remove(), 1200); } });
    }, 'image/png');
}

function _findBinIndex(bins, value) {
    if (bins.length < 2) return 0;
    const binStep = bins[1] - bins[0];
    return Math.max(-0.5, Math.min(bins.length - 0.5, (value - bins[0]) / binStep));
}

function drawBarChart(canvas, dist, cfg) {
    const { bins, counts } = dist;
    const n = counts.length;
    if (n === 0) return;
    if (canvas._chartInstance) { canvas._chartInstance.destroy(); canvas._chartInstance = null; }
    const totalCount = counts.reduce((a, b) => a + b, 0);
    const labels = bins.map(b => cfg.formatBin ? cfg.formatBin(b) : String(b));
    const bgColors = bins.map((b, i) => cfg.barColor ? cfg.barColor(b, i, bins) : '#4cc9f0');
    const hoverColors = bgColors.map(c => { const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16); return `rgb(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, b + 40)})`; });
    const annotations = {};
    if (cfg.refLine != null && bins.length >= 2) { annotations.refLine = { type: 'line', scaleID: 'x', value: _findBinIndex(bins, cfg.refLine), borderColor: '#f44336', borderWidth: 1.5, borderDash: [4, 3], label: { display: true, content: cfg.refLabel || '', position: 'start', color: '#f44336', font: { size: 9, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' } }; }
    if (dist.percentiles && bins.length >= 2) { const pCfg = { p25: { color: '#888', dash: [3, 3], label: 'P25' }, p50: { color: '#e0e040', dash: [6, 3], label: 'Med' }, p75: { color: '#888', dash: [3, 3], label: 'P75' } }; for (const [key, val] of Object.entries(dist.percentiles)) { const pc = pCfg[key]; if (!pc) continue; const fmtVal = cfg.formatBin ? cfg.formatBin(val) : String(val); annotations[key] = { type: 'line', scaleID: 'x', value: _findBinIndex(bins, val), borderColor: pc.color, borderWidth: 1, borderDash: pc.dash, label: { display: true, content: `${pc.label} ${fmtVal}`, position: 'start', color: pc.color, font: { size: 8, family: 'monospace' }, backgroundColor: 'rgba(15,15,35,0.7)' } }; } }
    const chart = new Chart(canvas, { type: 'bar', data: { labels, datasets: [{ data: counts, backgroundColor: bgColors, hoverBackgroundColor: hoverColors, borderWidth: 0, borderSkipped: false, barPercentage: 0.92, categoryPercentage: 0.92 }] }, options: { responsive: true, maintainAspectRatio: false, animation: { duration: 200 }, layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } }, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#16213e', borderColor: '#4cc9f0', borderWidth: 1, titleColor: '#4cc9f0', bodyColor: '#e0e0e0', footerColor: '#888', titleFont: { family: 'monospace', size: 11 }, bodyFont: { family: 'monospace', size: 11 }, footerFont: { family: 'monospace', size: 10 }, padding: 6, displayColors: false, callbacks: { title: (items) => items[0]?.label || '', label: (item) => `Count: ${item.raw}`, footer: (items) => { const count = items[0]?.raw || 0; return `${(count / totalCount * 100).toFixed(1)}%`; } } }, annotation: { annotations } }, scales: { x: { grid: { color: '#2a2a4a', lineWidth: 0.5 }, ticks: { color: '#888', font: { family: 'monospace', size: 9 }, autoSkip: !cfg.showAllLabels, maxRotation: 45, minRotation: 0 }, border: { color: '#2a2a4a' } }, y: { beginAtZero: true, grid: { color: '#1a1a3e', lineWidth: 0.5 }, ticks: { color: '#888', font: { family: 'monospace', size: 10 } }, border: { color: '#2a2a4a' } } } } });
    canvas._chartInstance = chart;
    return chart;
}


// --- Edit History Panel ---
// (showHistoryView, hideHistoryView, _buildSplitLineage, _buildSplitChains,
//  renderEditHistoryPanel, renderHistorySummaryStats, etc.)
// These are large but self-contained. Including as-is for Phase 8 extraction.

function showHistoryView() {
    for (const id of _SEG_NORMAL_IDS) { const el = document.getElementById(id); if (el) { el.dataset.hiddenByHistory = el.hidden ? '1' : ''; el.hidden = true; } }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls'); if (controls) { controls.dataset.hiddenByHistory = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel.querySelector('.shortcuts-guide'); if (shortcuts) { shortcuts.dataset.hiddenByHistory = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    dom.segHistoryView.hidden = false;
    state._histFilterOpTypes.clear(); state._histFilterErrCats.clear(); state._allHistoryItems = null; state._histSortMode = 'time';
    dom.segHistoryFilters.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active'));
    dom.segHistorySortTime.classList.add('active');
    dom.segHistoryFilterClear.hidden = true;
    const observer = _ensureWaveformObserver();
    dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => { dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows); });
}

function hideHistoryView() {
    stopErrorCardAudio();
    state._histFilterOpTypes.clear(); state._histFilterErrCats.clear(); state._allHistoryItems = null;
    dom.segHistoryView.hidden = true;
    for (const id of _SEG_NORMAL_IDS) { const el = document.getElementById(id); if (el) { if (el.dataset.hiddenByHistory !== '1') el.hidden = false; delete el.dataset.hiddenByHistory; } }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls'); if (controls) { if (controls.dataset.hiddenByHistory !== '1') controls.hidden = false; delete controls.dataset.hiddenByHistory; }
    const shortcuts = panel.querySelector('.shortcuts-guide'); if (shortcuts) { if (shortcuts.dataset.hiddenByHistory !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByHistory; }
    if (state._segDataStale) { state._segDataStale = false; onSegReciterChange(); }
}

function _buildSplitLineage(allBatches) { const lineage = new Map(); for (const batch of allBatches) { for (const op of (batch.operations || [])) { if (op.op_type !== 'split_segment') continue; const parent = op.targets_before?.[0]; if (!parent) continue; const parentCtx = (parent.segment_uid && lineage.has(parent.segment_uid)) ? lineage.get(parent.segment_uid) : { wfStart: parent.time_start, wfEnd: parent.time_end, audioUrl: parent.audio_url }; for (const child of (op.targets_after || [])) { if (child.segment_uid) lineage.set(child.segment_uid, parentCtx); } } } return lineage; }

function _buildSplitChains(allBatches, splitLineage) { const chains = new Map(); const chainedOpIds = new Set(); const uidToChain = new Map(); for (const batch of allBatches) { for (const op of (batch.operations || [])) { if (op.op_type !== 'split_segment') continue; const parentUid = op.targets_before?.[0]?.segment_uid; if (parentUid && splitLineage.has(parentUid)) continue; chains.set(op.op_id, { rootSnap: op.targets_before?.[0], rootBatch: batch, ops: [{ op, batch }], latestDate: batch.saved_at_utc || '' }); chainedOpIds.add(op.op_id); for (const snap of (op.targets_after || [])) { if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id); } } } const _CHAIN_ABSORB_OPS = new Set(['trim_segment', 'split_segment', 'edit_reference', 'confirm_reference']); for (const batch of allBatches) { for (const op of (batch.operations || [])) { if (chainedOpIds.has(op.op_id)) continue; if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue; const beforeUids = (op.targets_before || []).map(s => s.segment_uid).filter(Boolean); let chainId = null; for (const uid of beforeUids) { if (uidToChain.has(uid)) { chainId = uidToChain.get(uid); break; } } if (!chainId) continue; const chain = chains.get(chainId); chain.ops.push({ op, batch }); if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc; chainedOpIds.add(op.op_id); for (const snap of (op.targets_after || [])) { if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId); } } } return { chains, chainedOpIds }; }

function _computeChainLeafSnaps(chain) { const finalSnaps = new Map(); const beforeUids = new Set(); for (const { op } of chain.ops) { const afterUids = new Set((op.targets_after || []).map(s => s.segment_uid).filter(Boolean)); for (const snap of (op.targets_before || [])) { if (snap.segment_uid && !afterUids.has(snap.segment_uid)) beforeUids.add(snap.segment_uid); } for (const snap of (op.targets_after || [])) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); } } return [...finalSnaps.entries()].filter(([uid]) => !beforeUids.has(uid)).map(([, snap]) => snap).sort((a, b) => a.time_start - b.time_start); }

function renderSplitChainRow(chain) { const rootSnap = chain.rootSnap; const leafSnaps = _computeChainLeafSnaps(chain); const chapter = chain.rootBatch?.chapter ?? null; const wrapper = document.createElement('div'); wrapper.className = 'seg-history-batch seg-history-split-chain'; const header = document.createElement('div'); header.className = 'seg-history-batch-header'; const time = document.createElement('span'); time.className = 'seg-history-batch-time'; time.textContent = _formatHistDate(chain.latestDate); header.appendChild(time); if (chapter != null) { const ch = document.createElement('span'); ch.className = 'seg-history-batch-chapter'; ch.textContent = surahOptionText(chapter); header.appendChild(ch); } const badge = document.createElement('span'); badge.className = 'seg-history-batch-ops-count'; badge.textContent = `Split \u2192 ${leafSnaps.length}`; header.appendChild(badge); { const beforeIssues = new Set(); if (rootSnap) _classifySnapIssues(rootSnap).forEach(i => beforeIssues.add(i)); const afterIssues = new Set(); for (const ls of leafSnaps) _classifySnapIssues(ls).forEach(i => afterIssues.add(i)); const shortLabels = { failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary', cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed', repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala' }; for (const cat of [...beforeIssues].filter(i => !afterIssues.has(i))) { const b = document.createElement('span'); b.className = 'seg-history-val-delta improved'; b.textContent = `\u2212${shortLabels[cat] || cat}`; header.appendChild(b); } for (const cat of [...afterIssues].filter(i => !beforeIssues.has(i))) { const b = document.createElement('span'); b.className = 'seg-history-val-delta regression'; b.textContent = `+${shortLabels[cat] || cat}`; header.appendChild(b); } } const chainBatchIds = _getChainBatchIds(chain); if (chainBatchIds.length > 0) { const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onChainUndoClick(chainBatchIds, chapter, undoBtn); }); header.appendChild(undoBtn); } wrapper.appendChild(header); const body = document.createElement('div'); body.className = 'seg-history-batch-body'; const diff = document.createElement('div'); diff.className = 'seg-history-diff'; const beforeCol = document.createElement('div'); beforeCol.className = 'seg-history-before'; const arrowCol = document.createElement('div'); arrowCol.className = 'seg-history-arrows'; const arrowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); arrowSvg.setAttribute('height', '1'); arrowCol.appendChild(arrowSvg); const afterCol = document.createElement('div'); afterCol.className = 'seg-history-after'; let wfStart = rootSnap ? rootSnap.time_start : 0; let wfEnd = rootSnap ? rootSnap.time_end : 0; for (const ls of leafSnaps) { wfStart = Math.min(wfStart, ls.time_start); wfEnd = Math.max(wfEnd, ls.time_end); } const wfExpanded = rootSnap && (wfStart < rootSnap.time_start || wfEnd > rootSnap.time_end); if (rootSnap) { const beforeCard = renderSegCard(_snapToSeg(rootSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); beforeCol.appendChild(beforeCard); if (wfExpanded) { const bc = beforeCard.querySelector('canvas'); if (bc) bc._splitHL = { wfStart, wfEnd, hlStart: rootSnap.time_start, hlEnd: rootSnap.time_end }; } } if (leafSnaps.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = '(all segments deleted)'; afterCol.appendChild(empty); } else { for (const leafSnap of leafSnaps) { const card = renderSegCard(_snapToSeg(leafSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); afterCol.appendChild(card); if (rootSnap) { const canvas = card.querySelector('canvas'); if (canvas) canvas._splitHL = { wfStart, wfEnd, hlStart: leafSnap.time_start, hlEnd: leafSnap.time_end }; } } } diff.append(beforeCol, arrowCol, afterCol); body.appendChild(diff); wrapper.appendChild(body); return wrapper; }

function renderEditHistoryPanel(data) { if (!data || !data.batches || data.batches.length === 0) { dom.segHistoryBtn.hidden = true; dom.segHistoryFilters.hidden = true; return; } dom.segHistoryBtn.hidden = false; state._histFilterOpTypes.clear(); state._histFilterErrCats.clear(); state._allHistoryItems = null; const splitLineage = _buildSplitLineage(data.batches); const { chains, chainedOpIds } = _buildSplitChains(data.batches, splitLineage); state._splitChains = chains; state._chainedOpIds = chainedOpIds; { const reciter = dom.segReciterSelect.value; const allHistoryChapters = [...new Set(data.batches.flatMap(b => { const chs = []; if (b.chapter != null) chs.push(b.chapter); if (Array.isArray(b.chapters)) chs.push(...b.chapters); return chs; }).filter(ch => ch != null))]; if (reciter && allHistoryChapters.length > 0) _fetchPeaks(reciter, allHistoryChapters); } if (data.summary) { data.summary.verses_edited = _countVersesFromBatches(data.batches); renderHistorySummaryStats(data.summary); } renderHistoryFilterBar(data); renderHistoryBatches(data.batches); }

function renderHistorySummaryStats(summary, container = dom.segHistoryStats) { container.innerHTML = ''; if (!summary) return; const cardsRow = document.createElement('div'); cardsRow.className = 'seg-history-stat-cards'; const stats = [{ value: summary.total_operations, label: 'Operations' }, { value: summary.chapters_edited, label: 'Chapters' }, { value: summary.verses_edited ?? '\u2013', label: 'Verses' }]; for (const s of stats) { const card = document.createElement('div'); card.className = 'seg-history-stat-card'; card.innerHTML = `<div class="seg-history-stat-value">${s.value}</div><div class="seg-history-stat-label">${s.label}</div>`; cardsRow.appendChild(card); } container.appendChild(cardsRow); }

function _versesFromRef(ref) { if (!ref) return []; const parts = ref.split('-'); if (parts.length !== 2) return []; const sb = parts[0].split(':'), se = parts[1].split(':'); if (sb.length < 2 || se.length < 2) return []; const surah = parseInt(sb[0]), ayahStart = parseInt(sb[1]); const surahEnd = parseInt(se[0]), ayahEnd = parseInt(se[1]); if (surah !== surahEnd) return [`${surah}:${ayahStart}`, `${surahEnd}:${ayahEnd}`]; const out = []; for (let a = ayahStart; a <= ayahEnd; a++) out.push(`${surah}:${a}`); return out; }

function _countVersesFromBatches(batches) { const verses = new Set(); for (const batch of batches) { for (const op of (batch.operations || [])) { for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) { for (const v of _versesFromRef(snap.matched_ref)) verses.add(v); } } } return verses.size; }

function renderHistoryFilterBar(data) { dom.segHistoryFilterOps.innerHTML = ''; dom.segHistoryFilterCats.innerHTML = ''; dom.segHistoryFilterClear.hidden = true; if (!data.summary && (!data.batches || data.batches.length === 0)) { dom.segHistoryFilters.hidden = true; return; } const chainedOpIds = state._chainedOpIds || new Set(); const allItems = _flattenBatchesToItems(data.batches, chainedOpIds); state._allHistoryItems = allItems; const opCounts = {}; for (const item of allItems) { if (item.group.length === 0) continue; opCounts[item.group[0].op_type] = (opCounts[item.group[0].op_type] || 0) + 1; } const sortedOps = Object.entries(opCounts).sort((a, b) => b[1] - a[1]); for (const [opType, count] of sortedOps) { const pill = document.createElement('button'); pill.className = 'seg-history-filter-pill'; pill.dataset.filterType = 'op'; pill.dataset.filterValue = opType; pill.innerHTML = `${EDIT_OP_LABELS[opType] || opType} <span class="pill-count">${count}</span>`; pill.addEventListener('click', () => toggleHistoryFilter('op', opType, pill)); dom.segHistoryFilterOps.appendChild(pill); } const catCounts = {}; for (const item of allItems) { if (item.group.length === 0) continue; const delta = _deriveOpIssueDelta(item.group); const touchedCats = new Set([...delta.resolved, ...delta.introduced, ...item.group.map(op => op.op_context_category).filter(Boolean)]); for (const cat of touchedCats) catCounts[cat] = (catCounts[cat] || 0) + 1; } const sortedCats = Object.entries(catCounts).sort((a, b) => b[1] - a[1]); for (const [cat, count] of sortedCats) { const pill = document.createElement('button'); pill.className = 'seg-history-filter-pill'; pill.dataset.filterType = 'cat'; pill.dataset.filterValue = cat; pill.innerHTML = `${ERROR_CAT_LABELS[cat]} <span class="pill-count">${count}</span>`; pill.addEventListener('click', () => toggleHistoryFilter('cat', cat, pill)); dom.segHistoryFilterCats.appendChild(pill); } dom.segHistoryFilterOps.parentElement.hidden = (sortedOps.length < 2); dom.segHistoryFilterCats.parentElement.hidden = (sortedCats.length < 2); dom.segHistoryFilters.hidden = false; }

function toggleHistoryFilter(type, value, pill) { const set = type === 'op' ? state._histFilterOpTypes : state._histFilterErrCats; if (set.has(value)) { set.delete(value); pill.classList.remove('active'); } else { set.add(value); pill.classList.add('active'); } applyHistoryFilters(); }

function applyHistoryFilters() { if (!state.segHistoryData) return; const allBatches = state.segHistoryData.batches; const hasFilters = state._histFilterOpTypes.size > 0 || state._histFilterErrCats.size > 0; dom.segHistoryFilterClear.hidden = !hasFilters; const chainedIds = state._chainedOpIds || new Set(); const allItems = state._allHistoryItems || (state._allHistoryItems = _flattenBatchesToItems(allBatches, chainedIds)); const filtered = hasFilters ? allItems.filter(item => { if (state._histFilterOpTypes.size > 0 && !_itemMatchesOpFilter(item, state._histFilterOpTypes)) return false; if (state._histFilterErrCats.size > 0 && !_itemMatchesCatFilter(item, state._histFilterErrCats)) return false; return true; }) : allItems; _updateFilterPillCounts(allItems); if (hasFilters) renderHistorySummaryStats(_computeFilteredItemSummary(filtered)); else renderHistorySummaryStats(state.segHistoryData.summary); if (filtered.length === 0 && hasFilters) { dom.segHistoryBatches.innerHTML = ''; const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = 'No edits match the active filters.'; dom.segHistoryBatches.appendChild(empty); return; } _renderHistoryDisplayItems(filtered, allBatches, dom.segHistoryBatches); if (!dom.segHistoryView.hidden) { const observer = _ensureWaveformObserver(); dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c)); requestAnimationFrame(() => { dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows); }); } }

function _computeFilteredItemSummary(items) { const opCounts = {}; const fixKindCounts = {}; const chaptersEdited = new Set(); for (const item of items) { if (item.chapter != null) chaptersEdited.add(item.chapter); if (Array.isArray(item.chapters)) item.chapters.forEach(ch => chaptersEdited.add(ch)); for (const op of item.group) { opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1; fixKindCounts[op.fix_kind || 'unknown'] = (fixKindCounts[op.fix_kind || 'unknown'] || 0) + 1; } } return { total_operations: Object.values(opCounts).reduce((s, v) => s + v, 0), chapters_edited: chaptersEdited.size, verses_edited: _countVersesFromItems(items), op_counts: opCounts, fix_kind_counts: fixKindCounts }; }

function _countVersesFromItems(items) { const verses = new Set(); for (const item of items) { for (const op of item.group) { for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) { for (const v of _versesFromRef(snap.matched_ref)) verses.add(v); } } } return verses.size; }

function _itemMatchesOpFilter(item, opTypes) { return item.group.some(op => opTypes.has(op.op_type)); }
function _itemMatchesCatFilter(item, cats) { for (const op of item.group) { if (op.op_context_category && cats.has(op.op_context_category)) return true; } const delta = _deriveOpIssueDelta(item.group); for (const cat of cats) { if (delta.resolved.includes(cat) || delta.introduced.includes(cat)) return true; } return false; }

function _updateFilterPillCounts(allItems) { const catActive = state._histFilterErrCats.size > 0; const itemsForOpCounts = catActive ? allItems.filter(item => _itemMatchesCatFilter(item, state._histFilterErrCats)) : allItems; const opCounts = {}; for (const item of itemsForOpCounts) { if (item.group.length === 0) continue; opCounts[item.group[0].op_type] = (opCounts[item.group[0].op_type] || 0) + 1; } for (const pill of dom.segHistoryFilterOps.querySelectorAll('.seg-history-filter-pill')) { const span = pill.querySelector('.pill-count'); if (span) span.textContent = opCounts[pill.dataset.filterValue] || 0; } const opActive = state._histFilterOpTypes.size > 0; const itemsForCatCounts = opActive ? allItems.filter(item => _itemMatchesOpFilter(item, state._histFilterOpTypes)) : allItems; const catCounts = {}; for (const item of itemsForCatCounts) { if (item.group.length === 0) continue; const delta = _deriveOpIssueDelta(item.group); const touchedCats = new Set([...delta.resolved, ...delta.introduced, ...item.group.map(op => op.op_context_category).filter(Boolean)]); for (const cat of touchedCats) catCounts[cat] = (catCounts[cat] || 0) + 1; } for (const pill of dom.segHistoryFilterCats.querySelectorAll('.seg-history-filter-pill')) { const span = pill.querySelector('.pill-count'); if (span) span.textContent = catCounts[pill.dataset.filterValue] || 0; } }

function clearHistoryFilters() { state._histFilterOpTypes.clear(); state._histFilterErrCats.clear(); dom.segHistoryFilterOps.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active')); dom.segHistoryFilterCats.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active')); applyHistoryFilters(); }

function setHistorySort(mode) { state._histSortMode = mode; dom.segHistorySortTime.classList.toggle('active', mode === 'time'); dom.segHistorySortQuran.classList.toggle('active', mode === 'quran'); applyHistoryFilters(); }

function renderHistoryBatches(batches, container = dom.segHistoryBatches) { const chainedOpIds = state._chainedOpIds || new Set(); const items = _flattenBatchesToItems(batches, chainedOpIds); _renderHistoryDisplayItems(items, batches, container); }

function _renderHistoryDisplayItems(opItems, batches, container) { container.innerHTML = ''; const displayItems = []; if (state._splitChains && state._histFilterErrCats.size === 0) { const showSplitChains = state._histFilterOpTypes.size === 0 || state._histFilterOpTypes.has('split_segment'); if (showSplitChains) { const batchOpIds = new Set(batches.flatMap(b => (b.operations || []).map(op => op.op_id))); for (const chain of state._splitChains.values()) { if (chain.ops.some(({ op }) => batchOpIds.has(op.op_id))) displayItems.push({ type: 'chain', chain, date: chain.latestDate || '' }); } } } for (const item of opItems) displayItems.push({ type: 'op-item', item, date: item.date }); if (state._histSortMode === 'quran') { displayItems.sort((a, b) => { const aChap = _histItemChapter(a); const bChap = _histItemChapter(b); if (aChap !== bChap) return aChap - bChap; const aPos = _histItemTimeStart(a); const bPos = _histItemTimeStart(b); if (aPos !== bPos) return aPos - bPos; return b.date.localeCompare(a.date); }); } else { displayItems.sort((a, b) => { const cmp = b.date.localeCompare(a.date); if (cmp !== 0) return cmp; if (a.type === 'chain' && b.type !== 'chain') return -1; if (b.type === 'chain' && a.type !== 'chain') return 1; const aBIdx = a.item?.batchIdx ?? 0; const bBIdx = b.item?.batchIdx ?? 0; if (aBIdx !== bBIdx) return bBIdx - aBIdx; return (a.item?.groupIdx ?? 0) - (b.item?.groupIdx ?? 0); }); } for (const di of displayItems) { if (di.type === 'chain') container.appendChild(renderSplitChainRow(di.chain)); else container.appendChild(_renderOpCard(di.item)); } }

function _histItemChapter(di) { if (di.type === 'chain') return di.chain.rootBatch?.chapter ?? Infinity; const item = di.item; if (item.chapter != null) return item.chapter; if (Array.isArray(item.chapters) && item.chapters.length) return Math.min(...item.chapters); return Infinity; }
function _histItemTimeStart(di) { if (di.type === 'chain') return di.chain.rootSnap?.time_start ?? Infinity; const firstOp = di.item?.group?.[0]; return firstOp?.targets_before?.[0]?.time_start ?? Infinity; }

function _flattenBatchesToItems(batches, chainedOpIds) { const items = []; for (let bIdx = 0; bIdx < batches.length; bIdx++) { const batch = batches[bIdx]; const nonChainOps = (batch.operations || []).filter(op => !chainedOpIds.has(op.op_id)); const isMultiChapter = batch.chapter == null && Array.isArray(batch.chapters); const isStripSpecials = batch.batch_type === 'strip_specials'; if (isStripSpecials) { const byRef = new Map(); for (const op of nonChainOps) { const ref = op.targets_before?.[0]?.matched_ref || '(unknown)'; if (!byRef.has(ref)) byRef.set(ref, []); byRef.get(ref).push(op); } let gIdx = 0; for (const [, refOps] of byRef) { items.push({ type: 'strip-specials-card', group: refOps, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: gIdx++ }); } } else if (isMultiChapter) { items.push({ type: 'multi-chapter-card', group: nonChainOps, chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: 0 }); } else if (batch.is_revert && nonChainOps.length === 0) { items.push({ type: 'revert-card', group: [], chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: true, isPending: false, batchIdx: bIdx, groupIdx: 0 }); } else { const groups = _groupRelatedOps(nonChainOps); for (let gIdx = 0; gIdx < groups.length; gIdx++) { items.push({ type: 'op-card', group: groups[gIdx], chapter: batch.chapter, chapters: batch.chapters, batchId: batch.batch_id, date: batch.saved_at_utc || '', isRevert: !!batch.is_revert, isPending: !batch.batch_id && !batch.is_revert, batchIdx: bIdx, groupIdx: gIdx }); } } } return items; }

function _appendIssueDeltaBadges(container, group) { const delta = _deriveOpIssueDelta(group); const shortLabels = { failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary', cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed', repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala' }; for (const cat of delta.resolved) { const badge = document.createElement('span'); badge.className = 'seg-history-val-delta improved'; badge.textContent = `\u2212${shortLabels[cat] || cat}`; container.appendChild(badge); } for (const cat of delta.introduced) { const badge = document.createElement('span'); badge.className = 'seg-history-val-delta regression'; badge.textContent = `+${shortLabels[cat] || cat}`; container.appendChild(badge); } }

function _renderOpCard(item) { const wrapper = document.createElement('div'); wrapper.className = 'seg-history-batch' + (item.isRevert ? ' is-revert' : ''); const header = document.createElement('div'); header.className = 'seg-history-batch-header'; const group = item.group; if (item.type === 'strip-specials-card') { const badge = document.createElement('span'); badge.className = 'seg-history-op-type-badge'; badge.textContent = `Deletion \u00d7${group.length}`; header.appendChild(badge); } else if (item.type === 'multi-chapter-card') { const opType = group[0]?.op_type; const badge = document.createElement('span'); badge.className = 'seg-history-op-type-badge'; badge.textContent = `${EDIT_OP_LABELS[opType] || opType} \u00d7${group.length}`; header.appendChild(badge); } else if (item.type === 'revert-card') { } else if (group.length > 0) { const primary = group[0]; const typeBadge = document.createElement('span'); typeBadge.className = 'seg-history-op-type-badge'; typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type; header.appendChild(typeBadge); const followUp = {}; for (let i = 1; i < group.length; i++) { const t = group[i].op_type; followUp[t] = (followUp[t] || 0) + 1; } for (const [t, count] of Object.entries(followUp)) { const fb = document.createElement('span'); fb.className = 'seg-history-op-type-badge secondary'; fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` \u00d7${count}` : ''); header.appendChild(fb); } } const fixKinds = new Set(group.map(op => op.fix_kind).filter(fk => fk && fk !== 'manual')); if (item.type === 'strip-specials-card' || item.type === 'multi-chapter-card') fixKinds.add('auto_fix'); for (const fk of fixKinds) { const fkBadge = document.createElement('span'); fkBadge.className = 'seg-history-op-fix-kind'; fkBadge.textContent = fk; header.appendChild(fkBadge); } if (group.length > 0) _appendIssueDeltaBadges(header, group); if (item.isRevert) { const badge = document.createElement('span'); badge.className = 'seg-history-batch-revert-badge'; badge.textContent = 'Reverted'; header.appendChild(badge); } const ch = item.chapter; if (ch != null) { const chSpan = document.createElement('span'); chSpan.className = 'seg-history-batch-chapter'; chSpan.textContent = surahOptionText(ch); header.appendChild(chSpan); } const time = document.createElement('span'); time.className = 'seg-history-batch-time'; time.textContent = _formatHistDate(item.date || null); header.appendChild(time); if (item.isPending) { const discardBtn = document.createElement('button'); discardBtn.className = 'btn btn-sm seg-history-undo-btn'; discardBtn.textContent = 'Discard'; discardBtn.addEventListener('click', (e) => { e.stopPropagation(); onPendingBatchDiscard(item.chapter, discardBtn); }); header.appendChild(discardBtn); } else if (item.batchId && !item.isRevert) { const opIds = group.map(op => op.op_id); const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(item.batchId, opIds, undoBtn); }); header.appendChild(undoBtn); } wrapper.appendChild(header); if (group.length > 0 || item.type === 'multi-chapter-card') { const body = document.createElement('div'); body.className = 'seg-history-batch-body'; if (item.type === 'strip-specials-card') body.appendChild(_renderSpecialDeleteGroup(group)); else if (item.type === 'multi-chapter-card') { const chList = document.createElement('div'); chList.className = 'seg-history-chapter-list'; chList.textContent = 'Chapters: ' + (item.chapters || []).map(c => surahOptionText(c)).join(', '); body.appendChild(chList); } else if (group.length === 1) body.appendChild(renderHistoryOp(group[0], item.chapter, item.batchId, { skipLabel: true })); else body.appendChild(renderHistoryGroupedOp(group, item.chapter, item.batchId, { skipLabel: true })); wrapper.appendChild(body); } return wrapper; }

function _renderSpecialDeleteGroup(refOps) { const count = refOps.length; const snap = refOps[0].targets_before?.[0]; const diffEl = document.createElement('div'); diffEl.className = 'seg-history-diff'; const beforeCol = document.createElement('div'); beforeCol.className = 'seg-history-before'; if (snap) beforeCol.appendChild(renderSegCard(_snapToSeg(snap, null), { readOnly: true, showPlayBtn: true })); const afterCol = document.createElement('div'); afterCol.className = 'seg-history-after'; const emptyEl = document.createElement('div'); emptyEl.className = 'seg-history-empty'; emptyEl.textContent = count > 1 ? `\u00d7${count} deleted` : '(deleted)'; afterCol.appendChild(emptyEl); diffEl.appendChild(beforeCol); diffEl.appendChild(afterCol); return diffEl; }

function _groupRelatedOps(operations) { if (!operations || operations.length === 0) return []; if (operations.length === 1) return [[operations[0]]]; const groups = []; const opGroupIdx = new Map(); const uidToGroup = new Map(); for (let i = 0; i < operations.length; i++) { const op = operations[i]; const beforeUids = (op.targets_before || []).map(t => t.segment_uid).filter(Boolean); let parentGroup = null; for (const uid of beforeUids) { if (uidToGroup.has(uid)) { parentGroup = uidToGroup.get(uid); break; } } if (parentGroup !== null) { groups[parentGroup].push(op); opGroupIdx.set(i, parentGroup); } else { const gIdx = groups.length; groups.push([op]); opGroupIdx.set(i, gIdx); } const gIdx = opGroupIdx.get(i); for (const snap of (op.targets_after || [])) { if (snap.segment_uid) uidToGroup.set(snap.segment_uid, gIdx); } } return groups; }

function renderHistoryGroupedOp(group, chapter, batchId, { skipLabel = false } = {}) { const primary = group[0]; const finalSnaps = new Map(); for (const op of group) { for (const snap of (op.targets_after || [])) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); } } const before = primary.targets_before || []; const primaryAfterUids = (primary.targets_after || []).map(t => t.segment_uid); const after = primaryAfterUids.map(uid => finalSnaps.get(uid)).filter(Boolean); const wrap = document.createElement('div'); wrap.className = 'seg-history-op seg-history-grouped-op'; if (!skipLabel) { const label = document.createElement('div'); label.className = 'seg-history-op-label'; const typeBadge = document.createElement('span'); typeBadge.className = 'seg-history-op-type-badge'; typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type; label.appendChild(typeBadge); const followUp = {}; for (let i = 1; i < group.length; i++) { const t = group[i].op_type; followUp[t] = (followUp[t] || 0) + 1; } for (const [t, count] of Object.entries(followUp)) { const fb = document.createElement('span'); fb.className = 'seg-history-op-type-badge secondary'; fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` x${count}` : ''); label.appendChild(fb); } const fixKinds = new Set(group.map(op => op.fix_kind).filter(fk => fk && fk !== 'manual')); for (const fk of fixKinds) { const fkBadge = document.createElement('span'); fkBadge.className = 'seg-history-op-fix-kind'; fkBadge.textContent = fk; label.appendChild(fkBadge); } if (batchId) { const groupOpIds = group.map(op => op.op_id); const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-op-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(batchId, groupOpIds, undoBtn); }); label.appendChild(undoBtn); } wrap.appendChild(label); } const diff = document.createElement('div'); diff.className = 'seg-history-diff'; const beforeCol = document.createElement('div'); beforeCol.className = 'seg-history-before'; const arrowCol = document.createElement('div'); arrowCol.className = 'seg-history-arrows'; const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('height', '1'); arrowCol.appendChild(svg); const afterCol = document.createElement('div'); afterCol.className = 'seg-history-after'; const beforeCards = []; for (const snap of before) { const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); beforeCol.appendChild(card); beforeCards.push(card); } const afterCards = []; if (after.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = '(deleted)'; afterCol.appendChild(empty); } else { for (const snap of after) { const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true }); afterCol.appendChild(card); afterCards.push(card); } } if (before.length === 1 && after.length === 1) _highlightChanges(before[0], after[0], beforeCards[0], afterCards[0]); if ((primary.op_type === 'merge_segments' || primary.op_type === 'waqf_sakt') && before.length === 2 && afterCards.length === 1) { const afterCanvas = afterCards[0].querySelector('canvas'); if (afterCanvas && primary.merge_direction) { const hlSnap = primary.merge_direction === 'prev' ? before[1] : before[0]; afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end }; } } diff.append(beforeCol, arrowCol, afterCol); wrap.appendChild(diff); return wrap; }

function renderHistoryOp(op, chapter, batchId, { skipLabel = false } = {}) { const wrap = document.createElement('div'); wrap.className = 'seg-history-op'; if (!skipLabel) { const label = document.createElement('div'); label.className = 'seg-history-op-label'; const typeBadge = document.createElement('span'); typeBadge.className = 'seg-history-op-type-badge'; typeBadge.textContent = EDIT_OP_LABELS[op.op_type] || op.op_type; label.appendChild(typeBadge); if (op.fix_kind && op.fix_kind !== 'manual') { const fk = document.createElement('span'); fk.className = 'seg-history-op-fix-kind'; fk.textContent = op.fix_kind; label.appendChild(fk); } if (batchId) { const undoBtn = document.createElement('button'); undoBtn.className = 'btn btn-sm seg-history-op-undo-btn'; undoBtn.textContent = 'Undo'; undoBtn.addEventListener('click', (e) => { e.stopPropagation(); onOpUndoClick(batchId, [op.op_id], undoBtn); }); label.appendChild(undoBtn); } wrap.appendChild(label); } const diff = document.createElement('div'); diff.className = 'seg-history-diff'; const beforeCol = document.createElement('div'); beforeCol.className = 'seg-history-before'; const arrowCol = document.createElement('div'); arrowCol.className = 'seg-history-arrows'; const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('height', '1'); arrowCol.appendChild(svg); const afterCol = document.createElement('div'); afterCol.className = 'seg-history-after'; const before = op.targets_before || []; const after = op.targets_after || []; const beforeCards = []; for (const snap of before) { const pseudoSeg = _snapToSeg(snap, chapter); const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true }); beforeCol.appendChild(card); beforeCards.push(card); } const afterCards = []; if (after.length === 0) { const empty = document.createElement('div'); empty.className = 'seg-history-empty'; empty.textContent = '(deleted)'; afterCol.appendChild(empty); } else { for (const snap of after) { const pseudoSeg = _snapToSeg(snap, chapter); const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true }); afterCol.appendChild(card); afterCards.push(card); } } if (before.length === 1 && after.length === 1) _highlightChanges(before[0], after[0], beforeCards[0], afterCards[0]); if ((op.op_type === 'merge_segments' || op.op_type === 'waqf_sakt') && before.length === 2 && afterCards.length === 1) { const afterCanvas = afterCards[0].querySelector('canvas'); if (afterCanvas && op.merge_direction) { const hlSnap = op.merge_direction === 'prev' ? before[1] : before[0]; afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end }; } } diff.append(beforeCol, arrowCol, afterCol); wrap.appendChild(diff); return wrap; }

function _snapToSeg(snap, chapter) { return { index: snap.index_at_save, chapter, audio_url: snap.audio_url || '', time_start: snap.time_start, time_end: snap.time_end, matched_ref: snap.matched_ref || '', matched_text: snap.matched_text || '', display_text: snap.display_text || '', confidence: snap.confidence ?? 0, ...(snap.wrap_word_ranges ? { wrap_word_ranges: snap.wrap_word_ranges } : {}), ...(snap.has_repeated_words ? { has_repeated_words: true } : {}) }; }

function _highlightChanges(beforeSnap, afterSnap, beforeCard, afterCard) { if (beforeSnap.matched_ref !== afterSnap.matched_ref) { const el = afterCard.querySelector('.seg-text-ref'); if (el) el.classList.add('seg-history-changed'); } if (beforeSnap.time_start !== afterSnap.time_start || beforeSnap.time_end !== afterSnap.time_end) { const el = afterCard.querySelector('.seg-text-duration'); if (el) el.classList.add('seg-history-changed'); const bCanvas = beforeCard.querySelector('canvas'); const aCanvas = afterCard.querySelector('canvas'); if (bCanvas) bCanvas._trimHL = { color: 'red', otherStart: afterSnap.time_start, otherEnd: afterSnap.time_end }; if (aCanvas) aCanvas._trimHL = { color: 'green', otherStart: beforeSnap.time_start, otherEnd: beforeSnap.time_end }; } if (beforeSnap.confidence !== afterSnap.confidence) { const el = afterCard.querySelector('.seg-text-conf'); if (el) el.classList.add('seg-history-changed'); } if (beforeSnap.matched_text !== afterSnap.matched_text) { const el = afterCard.querySelector('.seg-text-body'); if (el) el.classList.add('seg-history-changed'); } }

function _appendValDeltas(container, before, after) { if (!before || !after) return; const cats = state._validationCategories || Object.keys(ERROR_CAT_LABELS); const shortLabels = { failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary', cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed', repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala' }; for (const cat of cats) { const delta = (after[cat] || 0) - (before[cat] || 0); if (delta === 0) continue; const badge = document.createElement('span'); badge.className = 'seg-history-val-delta ' + (delta < 0 ? 'improved' : 'regression'); badge.textContent = `${shortLabels[cat]} ${delta > 0 ? '+' : ''}${delta}`; container.appendChild(badge); } }

function _formatHistDate(isoStr) { if (!isoStr) return 'Pending'; try { const d = new Date(isoStr); return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }); } catch { return isoStr; } }

function _ensureHistArrowDefs() { if (document.getElementById('hist-arrow-defs')) return; const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('id', 'hist-arrow-defs'); svg.setAttribute('width', '0'); svg.setAttribute('height', '0'); svg.style.position = 'absolute'; const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs'); const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker'); marker.setAttribute('id', 'hist-arrow'); marker.setAttribute('viewBox', '0 0 10 7'); marker.setAttribute('refX', '10'); marker.setAttribute('refY', '3.5'); marker.setAttribute('markerWidth', '8'); marker.setAttribute('markerHeight', '6'); marker.setAttribute('orient', 'auto-start-reverse'); const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon'); poly.setAttribute('points', '0 0, 10 3.5, 0 7'); poly.setAttribute('fill', '#4cc9f0'); marker.appendChild(poly); defs.appendChild(marker); svg.appendChild(defs); document.body.appendChild(svg); }

function drawHistoryArrows(diffEl) { _ensureHistArrowDefs(); const svg = diffEl.querySelector('.seg-history-arrows svg'); if (!svg) return; const beforeCards = diffEl.querySelectorAll('.seg-history-before .seg-row'); const afterCards = diffEl.querySelectorAll('.seg-history-after .seg-row'); const afterEmpty = diffEl.querySelector('.seg-history-after .seg-history-empty'); svg.innerHTML = ''; const arrowCol = diffEl.querySelector('.seg-history-arrows'); const colRect = arrowCol.getBoundingClientRect(); if (colRect.height < 1) return; svg.setAttribute('height', colRect.height); svg.setAttribute('viewBox', `0 0 60 ${colRect.height}`); const midYs = (cards) => Array.from(cards).map(c => { const r = c.getBoundingClientRect(); return r.top + r.height / 2 - colRect.top; }); const bY = midYs(beforeCards); const aY = afterCards.length > 0 ? midYs(afterCards) : []; if (afterCards.length === 0 && afterEmpty) { const eRect = afterEmpty.getBoundingClientRect(); const targetY = eRect.top + eRect.height / 2 - colRect.top; for (const sy of bY) _drawArrowPath(svg, 4, sy, 56, targetY, true); const xSize = 5; const xG = document.createElementNS('http://www.w3.org/2000/svg', 'g'); xG.setAttribute('stroke', '#f44336'); xG.setAttribute('stroke-width', '2'); const cx = 52, cy = targetY; const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line'); l1.setAttribute('x1', cx - xSize); l1.setAttribute('y1', cy - xSize); l1.setAttribute('x2', cx + xSize); l1.setAttribute('y2', cy + xSize); const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line'); l2.setAttribute('x1', cx - xSize); l2.setAttribute('y1', cy + xSize); l2.setAttribute('x2', cx + xSize); l2.setAttribute('y2', cy - xSize); xG.append(l1, l2); svg.appendChild(xG); return; } if (bY.length === 1 && aY.length === 1) { _drawArrowPath(svg, 4, bY[0], 56, aY[0], false); return; } if (bY.length === 1 && aY.length > 1) { for (const ty of aY) _drawArrowPath(svg, 4, bY[0], 56, ty, false); return; } if (bY.length > 1 && aY.length === 1) { for (const sy of bY) _drawArrowPath(svg, 4, sy, 56, aY[0], false); return; } const maxLen = Math.max(bY.length, aY.length); for (let i = 0; i < maxLen; i++) { const sy = bY[Math.min(i, bY.length - 1)]; const ty = aY[Math.min(i, aY.length - 1)]; _drawArrowPath(svg, 4, sy, 56, ty, false); } }

function _drawArrowPath(svg, x1, y1, x2, y2, dashed) { const path = document.createElementNS('http://www.w3.org/2000/svg', 'path'); const midX = (x1 + x2) / 2; const d = Math.abs(y2 - y1) < 2 ? `M ${x1} ${y1} L ${x2} ${y2}` : `M ${x1} ${y1} Q ${midX} ${y1}, ${midX} ${(y1 + y2) / 2} Q ${midX} ${y2}, ${x2} ${y2}`; path.setAttribute('d', d); path.setAttribute('fill', 'none'); path.setAttribute('stroke', '#4cc9f0'); path.setAttribute('stroke-width', '1.5'); if (dashed) path.setAttribute('stroke-dasharray', '4,3'); path.setAttribute('marker-end', 'url(#hist-arrow)'); svg.appendChild(path); }
