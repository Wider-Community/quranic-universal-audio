/**
 * Split edit mode: enter, drag handle, preview, confirm.
 */

import { fetchJsonOrNull } from '../../lib/api';
import type { SegResolveRefResponse } from '../../types/api';
import type { Segment } from '../../types/domain';
import { getChapterSegments, syncChapterSegsToAll } from '../data';
import { applyVerseFilterAndRender,computeSilenceAfter } from '../filters';
import { _suggestSplitRefs } from '../references';
import { _getEditCanvas } from '../rendering';
import { dom, finalizeOp, markDirty,snapshotSeg, state } from '../state';
import { _rebuildAccordionAfterSplit, _refreshStaleSegIndices } from '../validation/error-cards';
import { _fixupValIndicesForSplit } from '../validation/index';
import { refreshOpenAccordionCards } from '../validation/index';
import { _slicePeaks } from '../waveform/draw';
import { _fetchChapterPeaksIfNeeded } from '../waveform/index';
import type { SegCanvas } from '../waveform/types';
import { _addEditOverlay,_playRange, exitEditMode } from './common';
import { startRefEdit } from './reference';

// ---------------------------------------------------------------------------
// enterSplitMode
// ---------------------------------------------------------------------------

export function enterSplitMode(seg: Segment, row: HTMLElement, prePausePlayMs: number | null = null): void {
    if (state.segEditMode) {
        console.warn('[split] blocked: already in edit mode:', state.segEditMode);
        return;
    }
    state.segEditMode = 'split';
    state.segEditIndex = seg.index;

    row.classList.add('seg-edit-target');
    _addEditOverlay();

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
    const splitAudioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    canvas._splitData = { seg, currentSplit: defaultSplit, audioUrl: splitAudioUrl };
    canvas._splitBaseCache = null;
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);

    // Pre-fetch peaks for the segment being split if not available
    if (splitAudioUrl && !state.segPeaksByAudio?.[splitAudioUrl]) {
        _fetchChapterPeaksIfNeeded(dom.segReciterSelect.value, chapter);
    }
}

// ---------------------------------------------------------------------------
// _ensureSplitBaseCache
// ---------------------------------------------------------------------------

export function _ensureSplitBaseCache(canvas: SegCanvas): boolean {
    if (canvas._splitBaseCache) return true;
    const ctx = canvas.getContext('2d');
    if (!ctx) return false;
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const sd = canvas._splitData;
    if (!sd) return false;
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
        const y = centerY - (data.maxVals[i] ?? 0) * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - (data.minVals[i] ?? 0) * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - (data.maxVals[i] ?? 0) * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    ctx.stroke();

    canvas._splitBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

// ---------------------------------------------------------------------------
// drawSplitWaveform -- redraw split overlay (yellow line + right-tint)
// ---------------------------------------------------------------------------

export function drawSplitWaveform(canvas: SegCanvas): void {
    const c = canvas;
    const hasCachedBase = _ensureSplitBaseCache(c);
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const width = c.width;
    const height = c.height;
    const sd = c._splitData;
    if (!sd) return;
    const seg = sd.seg;

    if (hasCachedBase && c._splitBaseCache) ctx.putImageData(c._splitBaseCache, 0, 0);

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

// ---------------------------------------------------------------------------
// setupSplitDragHandle -- mouse event handlers for split line
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
// updateSplitInfo -- update the L/R duration display
// ---------------------------------------------------------------------------

export function updateSplitInfo(canvas: SegCanvas | null | undefined, seg: Segment, splitTime: number): void {
    const c = (canvas ?? (_getEditCanvas() as SegCanvas | null)) ?? null;
    const el = c?._splitEls?.infoSpan;
    if (el) {
        el.textContent = `L ${((splitTime - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - splitTime) / 1000).toFixed(2)}s`;
    }
}

// ---------------------------------------------------------------------------
// confirmSplit -- apply the split and chain ref editing
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
    const useSegData = chapter === currentChapter && state.segData?.segments;

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

    const splitOp = state._pendingOp;
    state._pendingOp = null;
    if (splitOp) {
        splitOp.applied_at_utc = new Date().toISOString();
        splitOp.targets_after = [snapshotSeg(firstHalf), snapshotSeg(secondHalf)];
    }

    if (useSegData && state.segData) {
        const segIdx = state.segData.segments.findIndex(s => s.index === seg.index);
        state.segData.segments.splice(segIdx, 1, firstHalf, secondHalf);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        state.segData.segments = getChapterSegments(chapter);
    } else if (state.segAllData) {
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
        // Other open accordion wrappers keep stale data-seg-index values after
        // the reindex; without this sweep, resolveSegFromRow on their play
        // buttons maps stale index → wrong segment → wrong time.
        _refreshStaleSegIndices(accCtx.wrapper);
    } else {
        refreshOpenAccordionCards();
    }

    if (splitOp) finalizeOp(chapter, splitOp);

    dom.segPlayStatus.textContent = 'Split \u2014 edit first half reference, then second';

    state._splitChainUid = secondHalf.segment_uid ?? null;
    state._splitChainCategory = splitOp?.op_context_category || null;
    state._splitChainWrapper = accCtx ? accCtx.wrapper : null;
    const searchRoot: ParentNode = accCtx ? accCtx.wrapper : dom.segListEl;
    const firstRow = searchRoot.querySelector<HTMLElement>(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${firstHalf.index}"]`);
    if (firstRow) {
        firstRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const refSpan = firstRow.querySelector<HTMLElement>('.seg-text-ref');
        if (refSpan) {
            startRefEdit(refSpan, firstHalf, firstRow, state._splitChainCategory);
        }
    }
}

// ---------------------------------------------------------------------------
// previewSplitAudio -- toggle looping preview of left/right half
// ---------------------------------------------------------------------------

export function previewSplitAudio(side: 'left' | 'right'): void {
    const canvas = _getEditCanvas() as SegCanvas | null;
    const sd = canvas?._splitData;
    if (!sd || !canvas) return;
    const loopKey = `split-${side}` as const;
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
