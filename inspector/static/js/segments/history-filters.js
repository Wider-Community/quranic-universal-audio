/**
 * Edit history filter bar, sort controls, and filter application.
 */

import { state, dom, EDIT_OP_LABELS, ERROR_CAT_LABELS } from './state.js';
import { _deriveOpIssueDelta } from './categories.js';
import { _ensureWaveformObserver } from './waveform.js';
import {
    renderHistorySummaryStats, renderHistoryBatches,
    _flattenBatchesToItems, _renderHistoryDisplayItems,
    drawHistoryArrows, _versesFromRef,
} from './history-rendering.js';

// ---------------------------------------------------------------------------
// renderHistoryFilterBar
// ---------------------------------------------------------------------------

export function renderHistoryFilterBar(data) {
    dom.segHistoryFilterOps.innerHTML = '';
    dom.segHistoryFilterCats.innerHTML = '';
    dom.segHistoryFilterClear.hidden = true;
    if (!data.summary && (!data.batches || data.batches.length === 0)) { dom.segHistoryFilters.hidden = true; return; }
    const chainedOpIds = state._chainedOpIds || new Set();
    const allItems = _flattenBatchesToItems(data.batches, chainedOpIds);
    state._allHistoryItems = allItems;

    const opCounts = {};
    for (const item of allItems) { if (item.group.length === 0) continue; opCounts[item.group[0].op_type] = (opCounts[item.group[0].op_type] || 0) + 1; }
    const sortedOps = Object.entries(opCounts).sort((a, b) => b[1] - a[1]);
    for (const [opType, count] of sortedOps) {
        const pill = document.createElement('button');
        pill.className = 'seg-history-filter-pill';
        pill.dataset.filterType = 'op';
        pill.dataset.filterValue = opType;
        pill.innerHTML = `${EDIT_OP_LABELS[opType] || opType} <span class="pill-count">${count}</span>`;
        pill.addEventListener('click', () => toggleHistoryFilter('op', opType, pill));
        dom.segHistoryFilterOps.appendChild(pill);
    }

    const catCounts = {};
    for (const item of allItems) {
        if (item.group.length === 0) continue;
        const delta = _deriveOpIssueDelta(item.group);
        const touchedCats = new Set([...delta.resolved, ...delta.introduced, ...item.group.map(op => op.op_context_category).filter(Boolean)]);
        for (const cat of touchedCats) catCounts[cat] = (catCounts[cat] || 0) + 1;
    }
    const sortedCats = Object.entries(catCounts).sort((a, b) => b[1] - a[1]);
    for (const [cat, count] of sortedCats) {
        const pill = document.createElement('button');
        pill.className = 'seg-history-filter-pill';
        pill.dataset.filterType = 'cat';
        pill.dataset.filterValue = cat;
        pill.innerHTML = `${ERROR_CAT_LABELS[cat]} <span class="pill-count">${count}</span>`;
        pill.addEventListener('click', () => toggleHistoryFilter('cat', cat, pill));
        dom.segHistoryFilterCats.appendChild(pill);
    }

    dom.segHistoryFilterOps.parentElement.hidden = (sortedOps.length < 2);
    dom.segHistoryFilterCats.parentElement.hidden = (sortedCats.length < 2);
    dom.segHistoryFilters.hidden = false;
}

// ---------------------------------------------------------------------------
// toggleHistoryFilter
// ---------------------------------------------------------------------------

export function toggleHistoryFilter(type, value, pill) {
    const set = type === 'op' ? state._histFilterOpTypes : state._histFilterErrCats;
    if (set.has(value)) { set.delete(value); pill.classList.remove('active'); }
    else { set.add(value); pill.classList.add('active'); }
    applyHistoryFilters();
}

// ---------------------------------------------------------------------------
// applyHistoryFilters
// ---------------------------------------------------------------------------

export function applyHistoryFilters() {
    if (!state.segHistoryData) return;
    const allBatches = state.segHistoryData.batches;
    const hasFilters = state._histFilterOpTypes.size > 0 || state._histFilterErrCats.size > 0;
    dom.segHistoryFilterClear.hidden = !hasFilters;
    const chainedIds = state._chainedOpIds || new Set();
    const allItems = state._allHistoryItems || (state._allHistoryItems = _flattenBatchesToItems(allBatches, chainedIds));
    const filtered = hasFilters
        ? allItems.filter(item => {
            if (state._histFilterOpTypes.size > 0 && !_itemMatchesOpFilter(item, state._histFilterOpTypes)) return false;
            if (state._histFilterErrCats.size > 0 && !_itemMatchesCatFilter(item, state._histFilterErrCats)) return false;
            return true;
        })
        : allItems;
    _updateFilterPillCounts(allItems);
    if (hasFilters) renderHistorySummaryStats(_computeFilteredItemSummary(filtered));
    else renderHistorySummaryStats(state.segHistoryData.summary);

    if (filtered.length === 0 && hasFilters) {
        dom.segHistoryBatches.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = 'No edits match the active filters.';
        dom.segHistoryBatches.appendChild(empty);
        return;
    }
    _renderHistoryDisplayItems(filtered, allBatches, dom.segHistoryBatches);
    if (!dom.segHistoryView.hidden) {
        const observer = _ensureWaveformObserver();
        dom.segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        requestAnimationFrame(() => { dom.segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows); });
    }
}

// ---------------------------------------------------------------------------
// clearHistoryFilters / setHistorySort
// ---------------------------------------------------------------------------

export function clearHistoryFilters() {
    state._histFilterOpTypes.clear();
    state._histFilterErrCats.clear();
    dom.segHistoryFilterOps.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active'));
    dom.segHistoryFilterCats.querySelectorAll('.seg-history-filter-pill.active').forEach(p => p.classList.remove('active'));
    applyHistoryFilters();
}

export function setHistorySort(mode) {
    state._histSortMode = mode;
    dom.segHistorySortTime.classList.toggle('active', mode === 'time');
    dom.segHistorySortQuran.classList.toggle('active', mode === 'quran');
    applyHistoryFilters();
}

// ---------------------------------------------------------------------------
// Filter match helpers
// ---------------------------------------------------------------------------

function _itemMatchesOpFilter(item, opTypes) {
    return item.group.some(op => opTypes.has(op.op_type));
}

function _itemMatchesCatFilter(item, cats) {
    for (const op of item.group) { if (op.op_context_category && cats.has(op.op_context_category)) return true; }
    const delta = _deriveOpIssueDelta(item.group);
    for (const cat of cats) { if (delta.resolved.includes(cat) || delta.introduced.includes(cat)) return true; }
    return false;
}

// ---------------------------------------------------------------------------
// _computeFilteredItemSummary
// ---------------------------------------------------------------------------

function _computeFilteredItemSummary(items) {
    const opCounts = {};
    const fixKindCounts = {};
    const chaptersEdited = new Set();
    for (const item of items) {
        if (item.chapter != null) chaptersEdited.add(item.chapter);
        if (Array.isArray(item.chapters)) item.chapters.forEach(ch => chaptersEdited.add(ch));
        for (const op of item.group) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            fixKindCounts[op.fix_kind || 'unknown'] = (fixKindCounts[op.fix_kind || 'unknown'] || 0) + 1;
        }
    }
    return {
        total_operations: Object.values(opCounts).reduce((s, v) => s + v, 0),
        chapters_edited: chaptersEdited.size,
        verses_edited: _countVersesFromItems(items),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
}

// ---------------------------------------------------------------------------
// _countVersesFromItems
// ---------------------------------------------------------------------------

function _countVersesFromItems(items) {
    const verses = new Set();
    for (const item of items) {
        for (const op of item.group) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                for (const v of _versesFromRef(snap.matched_ref)) verses.add(v);
            }
        }
    }
    return verses.size;
}

// ---------------------------------------------------------------------------
// _updateFilterPillCounts -- cross-filter faceted counts
// ---------------------------------------------------------------------------

function _updateFilterPillCounts(allItems) {
    const catActive = state._histFilterErrCats.size > 0;
    const itemsForOpCounts = catActive ? allItems.filter(item => _itemMatchesCatFilter(item, state._histFilterErrCats)) : allItems;
    const opCounts = {};
    for (const item of itemsForOpCounts) { if (item.group.length === 0) continue; opCounts[item.group[0].op_type] = (opCounts[item.group[0].op_type] || 0) + 1; }
    for (const pill of dom.segHistoryFilterOps.querySelectorAll('.seg-history-filter-pill')) { const span = pill.querySelector('.pill-count'); if (span) span.textContent = opCounts[pill.dataset.filterValue] || 0; }

    const opActive = state._histFilterOpTypes.size > 0;
    const itemsForCatCounts = opActive ? allItems.filter(item => _itemMatchesOpFilter(item, state._histFilterOpTypes)) : allItems;
    const catCounts = {};
    for (const item of itemsForCatCounts) {
        if (item.group.length === 0) continue;
        const delta = _deriveOpIssueDelta(item.group);
        const touchedCats = new Set([...delta.resolved, ...delta.introduced, ...item.group.map(op => op.op_context_category).filter(Boolean)]);
        for (const cat of touchedCats) catCounts[cat] = (catCounts[cat] || 0) + 1;
    }
    for (const pill of dom.segHistoryFilterCats.querySelectorAll('.seg-history-filter-pill')) { const span = pill.querySelector('.pill-count'); if (span) span.textContent = catCounts[pill.dataset.filterValue] || 0; }
}
