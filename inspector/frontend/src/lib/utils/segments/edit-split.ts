/**
 * Split edit mode: enter, drag handle, preview, confirm.
 */

import { get } from 'svelte/store';

import type { SegResolveRefResponse } from '../../../types/api';
import type { Segment } from '../../../types/domain';
import { fetchJsonOrNull } from '../../api';
import { dom, markDirty } from '../../segments-state';
import {
    getChapterSegments,
    segAllData,
    segData,
    syncChapterSegsToAll,
} from '../../stores/segments/chapter';
import {
    finalizeOp,
    getPendingOp,
    setPendingOp,
    snapshotSeg,
} from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    editingSegIndex,
    editMode,
    setEdit,
    splitChainCategory,
    splitChainUid,
    splitChainWrapper,
} from '../../stores/segments/edit';
import type { SegCanvas } from '../../types/segments-waveform';
import { getWaveformPeaks } from '../waveform-cache';
import { _playRange, exitEditMode } from './edit-common';
import { startRefEdit } from './edit-reference';
import { _rebuildAccordionAfterSplit, _refreshStaleSegIndices } from './error-cards';
import { applyVerseFilterAndRender, computeSilenceAfter } from './filters-apply';
import { _getEditCanvas } from './get-edit-canvas';
import {
    clearPlayRangeRAF,
    getPreviewLooping,
    setPreviewJustSeeked,
    setPreviewLooping,
} from './play-range';
import { _suggestSplitRefs as _suggestSplitRefsLib } from './references';
import { _ensureSplitBaseCache, drawSplitWaveform } from './split-draw';
import { _fixupValIndicesForSplit, refreshOpenAccordionCards } from './validation-fixups';
import { _fetchChapterPeaksIfNeeded } from './waveform-utils';

function _vwc() {
    return get(segAllData)?.verse_word_counts ?? get(segData)?.verse_word_counts;
}
function _suggestSplitRefs(ref: Parameters<typeof _suggestSplitRefsLib>[0]) { return _suggestSplitRefsLib(ref, _vwc()); }

// Re-export draw functions for registration sites.
export { _ensureSplitBaseCache, drawSplitWaveform };

// ---------------------------------------------------------------------------
// enterSplitMode
// ---------------------------------------------------------------------------

export function enterSplitMode(seg: Segment, row: HTMLElement, prePausePlayMs: number | null = null): void {
    if (get(editMode)) {
        console.warn('[split] blocked: already in edit mode:', get(editMode));
        return;
    }
    setEdit('split', seg.segment_uid ?? null);
    editingSegIndex.set(seg.index);

    row.classList.add('seg-edit-target');
    const actions = row.querySelector<HTMLElement>('.seg-actions');
    if (actions) actions.hidden = true;

    const canvas = row.querySelector<SegCanvas>('canvas');
    const segLeft = row.querySelector<HTMLElement>('.seg-left');
    if (!canvas || !segLeft) return;

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
    const mkBtn = (text: string, cls: string, fn: () => void): HTMLButtonElement => {
        const b = document.createElement('button');
        b.className = `btn btn-sm ${cls}`;
        b.textContent = text;
        b.addEventListener('click', fn);
        return b;
    };
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
    const splitAudioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
    canvas._splitData = { seg, currentSplit: defaultSplit, audioUrl: splitAudioUrl };
    canvas._splitBaseCache = null;
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);

    // Pre-fetch peaks for the segment being split if not available.
    if (splitAudioUrl && !getWaveformPeaks(splitAudioUrl)) {
        _fetchChapterPeaksIfNeeded(dom.segReciterSelect.value, chapter);
    }
}

// ---------------------------------------------------------------------------
// setupSplitDragHandle — mouse event handlers for split line
// ---------------------------------------------------------------------------

export function setupSplitDragHandle(canvas: SegCanvas, seg: Segment): void {
    let dragging = false;
    let didDrag = false;

    function onMousedown(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;
        didDrag = false;
        if (Math.abs(x - splitX) < 15) {
            dragging = true;
            canvas.style.cursor = 'col-resize';
        }
    }

    function onMousemove(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
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

    function onMouseup(e: MouseEvent): void {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const sd = canvas._splitData;
            if (!sd) return;
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
    function onMouseleave(): void { dragging = false; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = (): void => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

// ---------------------------------------------------------------------------
// updateSplitInfo — update the L/R duration display
// ---------------------------------------------------------------------------

export function updateSplitInfo(canvas: SegCanvas | null | undefined, seg: Segment, splitTime: number): void {
    const c = (canvas ?? (_getEditCanvas() as SegCanvas | null)) ?? null;
    const el = c?._splitEls?.infoSpan;
    if (el) {
        el.textContent = `L ${((splitTime - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - splitTime) / 1000).toFixed(2)}s`;
    }
}

// ---------------------------------------------------------------------------
// confirmSplit — apply the split and chain ref editing
// ---------------------------------------------------------------------------

export async function confirmSplit(seg: Segment): Promise<void> {
    const canvas = _getEditCanvas() as SegCanvas | null;
    const splitTime = canvas?._splitData?.currentSplit;
    if (splitTime == null || splitTime <= seg.time_start || splitTime >= seg.time_end) {
        dom.segPlayStatus.textContent = 'Invalid split point';
        return;
    }

    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const curData = get(segData);
    const useSegData = chapter === currentChapter && curData?.segments;

    const firstHalf: Segment = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        time_end: splitTime,
    };
    const secondHalf: Segment = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        index: seg.index + 1,
        time_start: splitTime,
    };

    // Auto-suggest per-verse refs for cross-verse splits
    const suggested = _suggestSplitRefs(seg.matched_ref);
    if (suggested) {
        firstHalf.matched_ref = suggested.first;
        secondHalf.matched_ref = suggested.second;
        const [r1, r2] = await Promise.allSettled([
            fetchJsonOrNull<SegResolveRefResponse>(`/api/seg/resolve_ref?ref=${encodeURIComponent(suggested.first)}`),
            fetchJsonOrNull<SegResolveRefResponse>(`/api/seg/resolve_ref?ref=${encodeURIComponent(suggested.second)}`),
        ]);
        if (r1.status === 'fulfilled' && r1.value?.text) {
            firstHalf.matched_text = r1.value.text;
            firstHalf.display_text = r1.value.display_text || r1.value.text;
        }
        if (r2.status === 'fulfilled' && r2.value?.text) {
            secondHalf.matched_text = r2.value.text;
            secondHalf.display_text = r2.value.display_text || r2.value.text;
        }
    }

    const splitOp = getPendingOp();
    setPendingOp(null);
    if (splitOp) {
        splitOp.applied_at_utc = new Date().toISOString();
        splitOp.targets_after = [snapshotSeg(firstHalf), snapshotSeg(secondHalf)];
    }

    if (useSegData && curData) {
        const segIdx = curData.segments.findIndex(s => s.index === seg.index);
        curData.segments.splice(segIdx, 1, firstHalf, secondHalf);
        curData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        curData.segments = getChapterSegments(chapter);
    } else {
        const allData = get(segAllData);
        if (allData) {
            const globalIdx = allData.segments.indexOf(seg);
            if (globalIdx !== -1) {
                allData.segments.splice(globalIdx, 1, firstHalf, secondHalf);
            }
            let reIdx = 0;
            allData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
            allData._byChapter = null; allData._byChapterIndex = null;
        }
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForSplit(chapter, seg.index);

    const accCtx = get(accordionOpCtx);
    accordionOpCtx.set(null);

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();

    if (accCtx) {
        _rebuildAccordionAfterSplit(accCtx.wrapper, chapter, seg, firstHalf, secondHalf);
        // Other open accordion wrappers keep stale data-seg-index values after
        // the reindex; without this sweep, resolveSegFromRow on their play
        // buttons maps stale index → wrong segment → wrong time.
        _refreshStaleSegIndices(accCtx.wrapper);
    } else {
        refreshOpenAccordionCards();
    }

    if (splitOp) finalizeOp(chapter, splitOp);

    dom.segPlayStatus.textContent = 'Split \u2014 edit first half reference, then second';

    splitChainUid.set(secondHalf.segment_uid ?? null);
    const chainCat = splitOp?.op_context_category || null;
    splitChainCategory.set(chainCat);
    splitChainWrapper.set(accCtx ? accCtx.wrapper : null);
    const searchRoot: ParentNode = accCtx ? accCtx.wrapper : dom.segListEl;
    const firstRow = searchRoot.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${firstHalf.index}"]`);
    if (firstRow) {
        firstRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const refSpan = firstRow.querySelector<HTMLElement>('.seg-text-ref');
        if (refSpan) {
            startRefEdit(refSpan, firstHalf, firstRow, chainCat);
        }
    }
}

// ---------------------------------------------------------------------------
// previewSplitAudio — toggle looping preview of left/right half
// ---------------------------------------------------------------------------

export function previewSplitAudio(side: 'left' | 'right'): void {
    const canvas = _getEditCanvas() as SegCanvas | null;
    const sd = canvas?._splitData;
    if (!sd || !canvas) return;
    const loopKey = `split-${side}` as const;
    if (getPreviewLooping() === loopKey && !dom.segAudioEl.paused) {
        setPreviewLooping(false);
        setPreviewJustSeeked(false);
        dom.segAudioEl.pause();
        clearPlayRangeRAF();
        if (canvas._splitData) drawSplitWaveform(canvas);
        return;
    }
    setPreviewLooping(loopKey);
    const splitTime = sd.currentSplit;
    _playRange(
        side === 'left' ? sd.seg.time_start : splitTime,
        side === 'left' ? splitTime : sd.seg.time_end
    );
}
