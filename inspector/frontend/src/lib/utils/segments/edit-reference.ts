/**
 * Reference editing: startRefEdit, commitRefEdit, _chainSplitRefEdit.
 */

import { get } from 'svelte/store';

import type { SegResolveRefResponse } from '../../../types/api';
import type { Segment } from '../../../types/domain';
import { fetchJson } from '../../api';
import {
    refreshSegInStore,
    segAllData,
    segData,
    selectedChapter,
} from '../../stores/segments/chapter';
import {
    createOp,
    finalizeOp,
    getPendingOp,
    markDirty,
    setPendingOp,
    snapshotSeg,
} from '../../stores/segments/dirty';
import {
    clearEdit,
    setEdit,
    splitChainCategory,
    splitChainUid,
} from '../../stores/segments/edit';
import {
    continuousPlay,
    playStatusText,
    segAudioElement,
} from '../../stores/segments/playback';
import { stopSegAnimation } from './playback';
import { _normalizeRef as _normalizeRefLib, formatRef as _formatRefLib } from './references';

function _vwc() {
    return get(segAllData)?.verse_word_counts ?? get(segData)?.verse_word_counts;
}
function _normalizeRef(ref: Parameters<typeof _normalizeRefLib>[0]) { return _normalizeRefLib(ref, _vwc()); }
function formatRef(ref: Parameters<typeof _formatRefLib>[0]) { return _formatRefLib(ref, _vwc()); }

// ---------------------------------------------------------------------------
// startRefEdit — inline ref input on a segment card
// ---------------------------------------------------------------------------

export function startRefEdit(
    refSpan: HTMLElement,
    seg: Segment,
    row: HTMLElement,
    contextCategory: string | null = null,
): void {
    if (refSpan.querySelector('input')) return;

    const audioEl = get(segAudioElement);
    if (audioEl && !audioEl.paused) { audioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    // Signal reference-edit mode so EditOverlay knows an inline edit is
    // in progress. No backdrop shown for reference mode (see EditOverlay).
    setEdit('reference', seg.segment_uid ?? null);

    const pending = createOp('edit_reference', contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);

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

    function commit(): void {
        if (committed) return;
        committed = true;
        const newRef = input.value.trim();
        commitRefEdit(seg, newRef, row);
    }

    input.addEventListener('keydown', (e: KeyboardEvent) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            committed = true;
            setPendingOp(null);
            splitChainUid.set(null);
            splitChainCategory.set(null);
            clearEdit();
            refSpan.textContent = formatRef(originalRef);
        }
    });

    input.addEventListener('blur', commit);
    input.addEventListener('click', (e: MouseEvent) => e.stopPropagation());
}

// ---------------------------------------------------------------------------
// _chainSplitRefEdit — after split, auto-chain ref editing to second half
// ---------------------------------------------------------------------------

export function _chainSplitRefEdit(chapter: number): void {
    void chapter;
    const chainUid = get(splitChainUid);
    if (!chainUid) return;
    const chainCat = get(splitChainCategory);
    splitChainUid.set(null);
    splitChainCategory.set(null);
    const allSegs = get(segAllData)?.segments || get(segData)?.segments || [];
    const secondSeg = allSegs.find(s => s.segment_uid === chainUid);
    if (!secondSeg) return;
    // Broad document lookup — the second half's row may live in the main
    // list, a validation accordion card, or both. First match wins; all
    // SegmentRow sites reactively re-render from segAllData so any present
    // DOM occurrence is addressable by chapter+index.
    const selector = `.seg-row[data-seg-chapter="${secondSeg.chapter}"][data-seg-index="${secondSeg.index}"]`;
    const secondRow = document.querySelector<HTMLElement>(selector);
    if (!secondRow) return;
    secondRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const refSpan = secondRow.querySelector<HTMLElement>('.seg-text-ref');
    if (refSpan) {
        playStatusText.set('Now edit second half reference');
        setTimeout(() => startRefEdit(refSpan, secondSeg, secondRow, chainCat), 100);
    }
}

// ---------------------------------------------------------------------------
// commitRefEdit — resolve reference and apply edit
// ---------------------------------------------------------------------------

export async function commitRefEdit(seg: Segment, newRefIn: string, row: HTMLElement): Promise<void> {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const newRef = _normalizeRef(newRefIn) ?? '';
    if (newRef === oldRef) {
        if ((seg.confidence ?? 0) < 1.0) {
            const pending = getPendingOp();
            if (pending) {
                pending.op_type = 'confirm_reference';
                pending.fix_kind = 'audit';
            }
            seg.confidence = 1.0;
            const ctxCat = pending?.op_context_category;
            if (ctxCat) {
                if (ctxCat !== 'muqattaat') {
                    if (!seg.ignored_categories) seg.ignored_categories = [];
                    if (!seg.ignored_categories.includes(ctxCat))
                        seg.ignored_categories.push(ctxCat);
                }
            }
            delete seg._derived;
            markDirty(chapter, seg.index);
            refreshSegInStore(seg);
            if (pending) {
                pending.applied_at_utc = new Date().toISOString();
                pending.targets_after = [snapshotSeg(seg)];
                finalizeOp(chapter, pending);
            }
        } else {
            setPendingOp(null);
            const refSpan = row.querySelector<HTMLElement>('.seg-text-ref');
            if (refSpan) refSpan.textContent = formatRef(oldRef);
        }
        _chainSplitRefEdit(chapter);
        clearEdit();
        return;
    }

    seg.matched_ref = newRef;
    seg.confidence = 1.0;
    const pending = getPendingOp();
    const ctxCat = pending?.op_context_category;
    if (ctxCat) {
        if (ctxCat !== 'muqattaat') {
            if (!seg.ignored_categories) seg.ignored_categories = [];
            if (!seg.ignored_categories.includes(ctxCat))
                seg.ignored_categories.push(ctxCat);
        }
    }

    if (newRef) {
        try {
            const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`,
            );
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
    refreshSegInStore(seg);

    if (pending) {
        pending.applied_at_utc = new Date().toISOString();
        pending.targets_after = [snapshotSeg(seg)];
        finalizeOp(chapter, pending);
    }

    _chainSplitRefEdit(chapter);
    clearEdit();
}
