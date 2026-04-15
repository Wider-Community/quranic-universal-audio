/**
 * Shared edit-mode infrastructure: enterEditWithBuffer, exitEditMode,
 * _playRange, and the registration pattern for trim/split modes.
 */

import { clearEdit } from '../../lib/stores/segments/edit';
import { safePlay } from '../../lib/utils/audio';
import type { Segment } from '../../types/domain';
import { getSegByChapterIndex } from '../data';
import { stopSegAnimation } from '../playback/index';
import type { DrawWaveformFn, EnterSplitModeFn,EnterTrimModeFn } from '../registry';
import { _getEditCanvas,resolveSegFromRow } from '../rendering';
import { createOp, dom, snapshotSeg,state } from '../state';
import { stopErrorCardAudio } from '../validation/error-card-audio';
import { drawWaveformFromPeaksForSeg } from '../waveform/draw';
import type { SegCanvas } from '../waveform/types';

// ---------------------------------------------------------------------------
// Registration pattern: trim/split modules register their entry functions
// ---------------------------------------------------------------------------

// EditOverlay.svelte owns the overlay reactively from $editMode (Wave 7a.2).
// _addEditOverlay / _removeEditOverlay no-op stubs deleted in Wave 11a.

let _enterTrimMode: EnterTrimModeFn | null = null;
let _enterSplitMode: EnterSplitModeFn | null = null;
let _drawSplitWaveformFn: DrawWaveformFn | null = null;
let _drawTrimWaveformFn: DrawWaveformFn | null = null;

export function registerEditModes(trim: EnterTrimModeFn, split: EnterSplitModeFn): void {
    _enterTrimMode = trim;
    _enterSplitMode = split;
}

export function registerEditDrawFns(trimDraw: DrawWaveformFn, splitDraw: DrawWaveformFn): void {
    _drawTrimWaveformFn = trimDraw;
    _drawSplitWaveformFn = splitDraw;
}

// ---------------------------------------------------------------------------
// enterEditWithBuffer -- entry point for trim/split from event delegation
// ---------------------------------------------------------------------------

export function enterEditWithBuffer(
    seg: Segment,
    row: HTMLElement,
    mode: 'trim' | 'split',
    contextCategory: string | null = null,
): void {
    if (state.segEditMode) return;

    const isErrorPlaying = state._activeAudioSource === 'error' && state.valCardAudio && !state.valCardAudio.paused;
    const prePausePlayMs = isErrorPlaying
        ? state.valCardAudio!.currentTime * 1000
        : (dom.segAudioEl.paused ? null : dom.segAudioEl.currentTime * 1000);

    if (isErrorPlaying) stopErrorCardAudio();
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    state._segContinuousPlay = false;

    const playCol = row.querySelector<HTMLElement>('.seg-play-col');
    if (playCol) playCol.hidden = true;

    state._pendingOp = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    state._pendingOp.targets_before = [snapshotSeg(seg)];

    try {
        if (mode === 'trim' && _enterTrimMode) _enterTrimMode(seg, row);
        else if (mode === 'split' && _enterSplitMode) _enterSplitMode(seg, row, prePausePlayMs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        state._pendingOp = null;
        state.segEditMode = null;
        state.segEditIndex = -1;
        clearEdit();
        const targetRow = document.querySelector<HTMLElement>('.seg-row.seg-edit-target');
        if (targetRow) {
            targetRow.querySelector('.seg-edit-inline')?.remove();
            const acts = targetRow.querySelector<HTMLElement>('.seg-actions');
            if (acts) acts.hidden = false;
            targetRow.classList.remove('seg-edit-target');
        }
    }
}

// ---------------------------------------------------------------------------
// exitEditMode -- shared cleanup for trim/split
// ---------------------------------------------------------------------------

export function exitEditMode(): void {
    state._pendingOp = null;
    state._accordionOpCtx = null;

    const editRow = document.querySelector<HTMLElement>('.seg-row.seg-edit-target');
    if (editRow) {
        editRow.querySelector('.seg-edit-inline')?.remove();
        const actions = editRow.querySelector<HTMLElement>('.seg-actions');
        if (actions) actions.hidden = false;
        const playCol = editRow.querySelector<HTMLElement>('.seg-play-col');
        if (playCol) playCol.hidden = false;

        const canvas = editRow.querySelector<SegCanvas>('canvas');
        if (canvas) {
            canvas._editCleanup?.();
            delete canvas._trimWindow; delete canvas._splitData;
            delete canvas._trimEls; delete canvas._splitEls;
            delete canvas._editCleanup;
            canvas._wfCache = null;
            canvas.style.cursor = '';
            const seg = resolveSegFromRow(editRow);
            if (seg) drawWaveformFromPeaksForSeg(canvas, seg, seg.chapter ?? 0);
        }
    }

    state.segEditMode = null;
    state.segEditIndex = -1;
    clearEdit();
    state._previewLooping = false;
    state._previewJustSeeked = false;
    if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
    if (state._previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', state._previewStopHandler);
        state._previewStopHandler = null;
    }
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    editRow?.classList.remove('seg-edit-target');
}

// ---------------------------------------------------------------------------
// _playRange -- shared preview playback with animated playhead
// ---------------------------------------------------------------------------

export function _playRange(startMs: number, endMs: number): void {
    if (state._previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', state._previewStopHandler);
        state._previewStopHandler = null;
    }
    if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = _getEditCanvas() as SegCanvas | null;

    let wfStart: number, wfEnd: number;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = (): void => {
        if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
        if (canvas?._splitData) _drawSplitWaveformFn?.(canvas);
        else if (canvas?._trimWindow) _drawTrimWaveformFn?.(canvas);
    };

    const inEditMode = canvas && (canvas._splitData || canvas._trimWindow);
    let _playRangeSnapshot: ImageData | null = null;
    if (canvas && !inEditMode) {
        const ctx = canvas.getContext('2d');
        if (ctx) _playRangeSnapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
    }

    function animatePlayhead(): void {
        if (!canvas || dom.segAudioEl.paused) return;
        const curMs = dom.segAudioEl.currentTime * 1000;
        let effectiveEnd = endMs;
        let loopStart: number | null = null;
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
        if (canvas._splitData) _drawSplitWaveformFn?.(canvas);
        else if (canvas._trimWindow) _drawTrimWaveformFn?.(canvas);
        else if (_playRangeSnapshot) {
            const ctx2 = canvas.getContext('2d');
            if (ctx2) ctx2.putImageData(_playRangeSnapshot, 0, 0);
        }
        if (curMs >= wfStart && curMs <= wfEnd) {
            const ctx = canvas.getContext('2d');
            if (!ctx) { state._playRangeRAF = requestAnimationFrame(animatePlayhead); return; }
            const w = canvas.width, h = canvas.height;
            const x = ((curMs - wfStart) / (wfEnd - wfStart)) * w;
            ctx.strokeStyle = '#f72585'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = '#f72585';
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        state._playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = (): void => {
        dom.segAudioEl.currentTime = start;
        dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
        safePlay(dom.segAudioEl);
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
