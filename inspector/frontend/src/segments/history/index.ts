/**
 * Edit history panel lifecycle (show/hide) and data loading.
 */

import { state, dom, _SEG_NORMAL_IDS } from '../state';
import { onSegReciterChange } from '../data';
import { _ensureWaveformObserver } from '../waveform/index';
import { _fetchPeaks } from '../waveform/index';
import { stopErrorCardAudio } from '../validation/error-card-audio';
import {
    renderHistorySummaryStats, renderHistoryBatches, drawHistoryArrows,
    _countVersesFromBatches,
} from './rendering';
import { renderHistoryFilterBar } from './filters';
import type { SegEditHistoryResponse } from '../../types/api';
import type { EditOp, HistoryBatch } from '../../types/domain';

interface SplitLineageEntry {
    wfStart: number;
    wfEnd: number;
    audioUrl: string;
}
type SplitLineage = Map<string, SplitLineageEntry>;

interface SplitChain {
    rootSnap?: Record<string, unknown>;
    rootBatch: HistoryBatch;
    ops: Array<{ op: EditOp; batch: HistoryBatch }>;
    latestDate: string;
}

interface BuildChainsResult {
    chains: Map<string, SplitChain>;
    chainedOpIds: Set<string>;
}

// ---------------------------------------------------------------------------
// showHistoryView
// ---------------------------------------------------------------------------

export function showHistoryView(): void {
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByHistory = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { controls.dataset.hiddenByHistory = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
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
    dom.segHistoryView.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => { dom.segHistoryView.querySelectorAll<HTMLElement>('.seg-history-diff').forEach(drawHistoryArrows); });
}

// ---------------------------------------------------------------------------
// hideHistoryView
// ---------------------------------------------------------------------------

export function hideHistoryView(): void {
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
    const controls = panel?.querySelector<HTMLElement>('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByHistory !== '1') controls.hidden = false; delete controls.dataset.hiddenByHistory; }
    const shortcuts = panel?.querySelector<HTMLElement>('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByHistory !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByHistory; }
    if (state._segDataStale) { state._segDataStale = false; onSegReciterChange(); }
}

// ---------------------------------------------------------------------------
// renderEditHistoryPanel -- fetch data, build summary + filter bar + batches
// ---------------------------------------------------------------------------

export function renderEditHistoryPanel(data: SegEditHistoryResponse | null | undefined): void {
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
    state._splitChains = chains as unknown as Map<string, unknown>;
    state._chainedOpIds = chainedOpIds;

    // Prefetch peaks for all history chapters
    {
        const reciter = dom.segReciterSelect.value;
        const allHistoryChapters: number[] = [...new Set<number>(data.batches.flatMap(b => {
            const chs: number[] = [];
            if (b.chapter != null) chs.push(b.chapter);
            if (Array.isArray(b.chapters)) chs.push(...b.chapters);
            return chs;
        }).filter((ch): ch is number => ch != null))];
        if (reciter && allHistoryChapters.length > 0) _fetchPeaks(reciter, allHistoryChapters);
    }

    if (data.summary) {
        (data.summary as unknown as Record<string, unknown>).verses_edited = _countVersesFromBatches(data.batches);
        renderHistorySummaryStats(data.summary as unknown as {
            total_operations: number;
            chapters_edited: number;
            verses_edited?: number;
        });
    }
    renderHistoryFilterBar(data);
    renderHistoryBatches(data.batches);
}

// ---------------------------------------------------------------------------
// _buildSplitLineage -- track parent -> child relationships for splits
// ---------------------------------------------------------------------------

export function _buildSplitLineage(allBatches: HistoryBatch[]): SplitLineage {
    const lineage: SplitLineage = new Map();
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parent = op.targets_before?.[0] as { segment_uid?: string; time_start?: number; time_end?: number; audio_url?: string } | undefined;
            if (!parent) continue;
            const parentCtx: SplitLineageEntry = (parent.segment_uid && lineage.has(parent.segment_uid))
                ? lineage.get(parent.segment_uid)!
                : { wfStart: parent.time_start ?? 0, wfEnd: parent.time_end ?? 0, audioUrl: parent.audio_url ?? '' };
            for (const child of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (child.segment_uid) lineage.set(child.segment_uid, parentCtx);
            }
        }
    }
    return lineage;
}

// ---------------------------------------------------------------------------
// _buildSplitChains -- group sequential split + refine ops into chains
// ---------------------------------------------------------------------------

export function _buildSplitChains(allBatches: HistoryBatch[], splitLineage: SplitLineage): BuildChainsResult {
    const chains = new Map<string, SplitChain>();
    const chainedOpIds = new Set<string>();
    const uidToChain = new Map<string, string>();

    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parentBefore = op.targets_before?.[0] as { segment_uid?: string } | undefined;
            const parentUid = parentBefore?.segment_uid;
            if (parentUid && splitLineage.has(parentUid)) continue;
            chains.set(op.op_id, {
                rootSnap: op.targets_before?.[0],
                rootBatch: batch,
                ops: [{ op, batch }],
                latestDate: batch.saved_at_utc || '',
            });
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id);
            }
        }
    }

    const _CHAIN_ABSORB_OPS = new Set(['trim_segment', 'split_segment', 'edit_reference', 'confirm_reference']);
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (chainedOpIds.has(op.op_id)) continue;
            if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue;
            const beforeUids = ((op.targets_before || []) as Array<{ segment_uid?: string }>).map(s => s.segment_uid).filter((u): u is string => !!u);
            let chainId: string | null = null;
            for (const uid of beforeUids) { if (uidToChain.has(uid)) { chainId = uidToChain.get(uid)!; break; } }
            if (!chainId) continue;
            const chain = chains.get(chainId);
            if (!chain) continue;
            chain.ops.push({ op, batch });
            if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc || '';
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId);
            }
        }
    }

    return { chains, chainedOpIds };
}
