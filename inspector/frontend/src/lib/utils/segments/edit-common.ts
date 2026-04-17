/**
 * Shared edit-mode infrastructure: enterEditWithBuffer, exitEditMode,
 * _playRange, and the registration pattern for trim/split modes.
 */

import type { Segment } from '../../../types/domain';
import { createOp, dom, snapshotSeg, state } from '../../segments-state';
import { clearEdit } from '../../stores/segments/edit';
import type {
    DrawWaveformFn,
    EnterSplitModeFn,
    EnterTrimModeFn,
    SegCanvas,
} from '../../types/segments-waveform';
import { stopErrorCardAudio } from './error-card-audio';
import { _playRange as _playRangeImpl, registerPlayRangeDrawFns } from './play-range';
import { stopSegAnimation } from './playback';
import { resolveSegFromRow } from './resolve-seg-from-row';
import { drawWaveformFromPeaksForSeg } from './waveform-draw-seg';

// ---------------------------------------------------------------------------
// Registration pattern: trim/split modules register their entry functions
// ---------------------------------------------------------------------------

let _enterTrimMode: EnterTrimModeFn | null = null;
let _enterSplitMode: EnterSplitModeFn | null = null;

export function registerEditModes(trim: EnterTrimModeFn, split: EnterSplitModeFn): void {
    _enterTrimMode = trim;
    _enterSplitMode = split;
}

export function registerEditDrawFns(trimDraw: DrawWaveformFn, splitDraw: DrawWaveformFn): void {
    // Delegate to play-range module (breaks circular import).
    registerPlayRangeDrawFns(trimDraw, splitDraw);
}

// ---------------------------------------------------------------------------
// enterEditWithBuffer — entry point for trim/split from event delegation
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
// exitEditMode — shared cleanup for trim/split
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

// Re-export play-range implementation so existing callers still work.
export const _playRange = _playRangeImpl;
