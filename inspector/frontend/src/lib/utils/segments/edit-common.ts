/**
 * Shared edit-mode infrastructure: enterEditWithBuffer, exitEditMode,
 * _playRange, and the registration pattern for trim/split modes.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../types/domain';
import { dom } from '../../segments-state';
import { createOp, snapshotSeg } from '../../stores/segments/dirty';
import { setPendingOp } from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    clearEdit,
    editMode,
} from '../../stores/segments/edit';
import {
    activeAudioSource,
    continuousPlay,
} from '../../stores/segments/playback';
import type {
    DrawWaveformFn,
    EnterSplitModeFn,
    EnterTrimModeFn,
    SegCanvas,
} from '../../types/segments-waveform';
import { getValCardAudioOrNull, stopErrorCardAudio } from './error-card-audio';
import {
    _playRange as _playRangeImpl,
    clearPlayRangeRAF,
    getPreviewStopHandler,
    registerPlayRangeDrawFns,
    setPreviewJustSeeked,
    setPreviewLooping,
    setPreviewStopHandler,
} from './play-range';
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
    if (get(editMode)) return;

    const valAudio = getValCardAudioOrNull();
    const isErrorPlaying = get(activeAudioSource) === 'error' && valAudio && !valAudio.paused;
    const prePausePlayMs = isErrorPlaying
        ? valAudio.currentTime * 1000
        : (dom.segAudioEl.paused ? null : dom.segAudioEl.currentTime * 1000);

    if (isErrorPlaying) stopErrorCardAudio();
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    const playCol = row.querySelector<HTMLElement>('.seg-play-col');
    if (playCol) playCol.hidden = true;

    const pending = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);

    try {
        if (mode === 'trim' && _enterTrimMode) _enterTrimMode(seg, row);
        else if (mode === 'split' && _enterSplitMode) _enterSplitMode(seg, row, prePausePlayMs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        setPendingOp(null);
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
    setPendingOp(null);
    accordionOpCtx.set(null);

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

    clearEdit();
    setPreviewLooping(false);
    setPreviewJustSeeked(false);
    clearPlayRangeRAF();
    const stopHandler = getPreviewStopHandler();
    if (stopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', stopHandler);
        setPreviewStopHandler(null);
    }
    if (!dom.segAudioEl.paused) { dom.segAudioEl.pause(); stopSegAnimation(); }
    editRow?.classList.remove('seg-edit-target');
}

// Re-export play-range implementation so existing callers still work.
export const _playRange = _playRangeImpl;
