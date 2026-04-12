// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Reference editing: startRefEdit, commitRefEdit, _chainSplitRefEdit.
 */

import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty } from '../state';
import { _normalizeRef, formatRef } from '../references';
import { syncAllCardsForSegment } from '../rendering';
import { stopSegAnimation } from '../playback/index';

// ---------------------------------------------------------------------------
// startRefEdit -- inline ref input on a segment card
// ---------------------------------------------------------------------------

export function startRefEdit(refSpan, seg, row, contextCategory = null) {
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

// ---------------------------------------------------------------------------
// _chainSplitRefEdit -- after split, auto-chain ref editing to second half
// ---------------------------------------------------------------------------

export function _chainSplitRefEdit(chapter) {
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

// ---------------------------------------------------------------------------
// commitRefEdit -- resolve reference and apply edit
// ---------------------------------------------------------------------------

export async function commitRefEdit(seg, newRef, row) {
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
