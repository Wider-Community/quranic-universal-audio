/**
 * Edit history panel lifecycle (show/hide) and data loading.
 */

import { state, dom, _SEG_NORMAL_IDS } from './state.js';
import { onSegReciterChange } from './data.js';
import { _ensureWaveformObserver } from './waveform.js';
import { _fetchPeaks } from './waveform.js';
import { stopErrorCardAudio } from './error-card-audio.js';
import {
    renderHistorySummaryStats, renderHistoryBatches, drawHistoryArrows,
    _countVersesFromBatches,
} from './history-rendering.js';
import { renderHistoryFilterBar, clearHistoryFilters, setHistorySort } from './history-filters.js';

// ---------------------------------------------------------------------------
// showHistoryView
// ---------------------------------------------------------------------------

export function showHistoryView() {
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByHistory = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { controls.dataset.hiddenByHistory = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByHistory = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    dom.segHistoryView.hidden = false;
    state._histFilterOpTypes.clear();
    state._histFilterErrCats.clear();
    state._allHistoryItems = null;
    state._histSortMode = 'time';
    dom.segHistoryFilters.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active'));
    dom.segHistorySortTime.classList.add('active');
    dom.segHistoryFilterClear.hidden = true;
    const observer = _ensureWaveformObserver();
    dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => { dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows); });
}

// ---------------------------------------------------------------------------
// hideHistoryView
// ---------------------------------------------------------------------------

export function hideHistoryView() {
    stopErrorCardAudio();
    state._histFilterOpTypes.clear();
    state._histFilterErrCats.clear();
    state._allHistoryItems = null;
    dom.segHistoryView.hidden = true;
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByHistory !== '1') el.hidden = false; delete el.dataset.hiddenByHistory; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByHistory !== '1') controls.hidden = false; delete controls.dataset.hiddenByHistory; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByHistory !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByHistory; }
    if (state._segDataStale) { state._segDataStale = false; onSegReciterChange(); }
}

// ---------------------------------------------------------------------------
// renderEditHistoryPanel -- fetch data, build summary + filter bar + batches
// ---------------------------------------------------------------------------

export function renderEditHistoryPanel(data) {
    if (!data || !data.batches || data.batches.length === 0) {
        dom.segHistoryBtn.hidden = true;
        dom.segHistoryFilters.hidden = true;
        return;
    }
    dom.segHistoryBtn.hidden = false;
    state._histFilterOpTypes.clear();
    state._histFilterErrCats.clear();
    state._allHistoryItems = null;
    const splitLineage = _buildSplitLineage(data.batches);
    const { chains, chainedOpIds } = _buildSplitChains(data.batches, splitLineage);
    state._splitChains = chains;
    state._chainedOpIds = chainedOpIds;

    // Prefetch peaks for all history chapters
    {
        const reciter = dom.segReciterSelect.value;
        const allHistoryChapters = [...new Set(data.batches.flatMap(b => {
            const chs = [];
            if (b.chapter != null) chs.push(b.chapter);
            if (Array.isArray(b.chapters)) chs.push(...b.chapters);
            return chs;
        }).filter(ch => ch != null))];
        if (reciter && allHistoryChapters.length > 0) _fetchPeaks(reciter, allHistoryChapters);
    }

    if (data.summary) {
        data.summary.verses_edited = _countVersesFromBatches(data.batches);
        renderHistorySummaryStats(data.summary);
    }
    renderHistoryFilterBar(data);
    renderHistoryBatches(data.batches);
}

// ---------------------------------------------------------------------------
// _buildSplitLineage -- track parent -> child relationships for splits
// ---------------------------------------------------------------------------

export function _buildSplitLineage(allBatches) {
    const lineage = new Map();
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parent = op.targets_before?.[0];
            if (!parent) continue;
            const parentCtx = (parent.segment_uid && lineage.has(parent.segment_uid))
                ? lineage.get(parent.segment_uid)
                : { wfStart: parent.time_start, wfEnd: parent.time_end, audioUrl: parent.audio_url };
            for (const child of (op.targets_after || [])) {
                if (child.segment_uid) lineage.set(child.segment_uid, parentCtx);
            }
        }
    }
    return lineage;
}

// ---------------------------------------------------------------------------
// _buildSplitChains -- group sequential split + refine ops into chains
// ---------------------------------------------------------------------------

export function _buildSplitChains(allBatches, splitLineage) {
    const chains = new Map();
    const chainedOpIds = new Set();
    const uidToChain = new Map();

    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parentUid = op.targets_before?.[0]?.segment_uid;
            if (parentUid && splitLineage.has(parentUid)) continue;
            chains.set(op.op_id, {
                rootSnap: op.targets_before?.[0], rootBatch: batch,
                ops: [{ op, batch }], latestDate: batch.saved_at_utc || '',
            });
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || [])) { if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id); }
        }
    }

    const _CHAIN_ABSORB_OPS = new Set(['trim_segment', 'split_segment', 'edit_reference', 'confirm_reference']);
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (chainedOpIds.has(op.op_id)) continue;
            if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue;
            const beforeUids = (op.targets_before || []).map(s => s.segment_uid).filter(Boolean);
            let chainId = null;
            for (const uid of beforeUids) { if (uidToChain.has(uid)) { chainId = uidToChain.get(uid); break; } }
            if (!chainId) continue;
            const chain = chains.get(chainId);
            chain.ops.push({ op, batch });
            if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc;
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || [])) { if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId); }
        }
    }

    return { chains, chainedOpIds };
}

