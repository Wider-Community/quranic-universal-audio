/**
 * enterEditWithBuffer — entry point for trim/split from event delegation.
 *
 * Kept in its own module so `edit-common.ts` can stay a dependency-leaf
 * of `edit-trim.ts` / `edit-split.ts` (those modules import `_playRange`
 * and `exitEditMode` from edit-common, so edit-common must not import them).
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../types/domain';
import { createOp, setPendingOp, snapshotSeg } from '../../stores/segments/dirty';
import { clearEdit, editMode } from '../../stores/segments/edit';
import {
    activeAudioSource,
    continuousPlay,
    segAudioElement,
} from '../../stores/segments/playback';
import { enterSplitMode } from './edit-split';
import { enterTrimMode } from './edit-trim';
import { getValCardAudioOrNull, stopErrorCardAudio } from './error-card-audio';
import { stopSegAnimation } from './playback';

export function enterEditWithBuffer(
    seg: Segment,
    row: HTMLElement,
    mode: 'trim' | 'split',
    contextCategory: string | null = null,
): void {
    if (get(editMode)) return;

    const audioEl = get(segAudioElement);
    const valAudio = getValCardAudioOrNull();
    const isErrorPlaying = get(activeAudioSource) === 'error' && valAudio && !valAudio.paused;
    const prePausePlayMs = isErrorPlaying
        ? valAudio!.currentTime * 1000
        : (!audioEl || audioEl.paused ? null : audioEl.currentTime * 1000);

    if (isErrorPlaying) stopErrorCardAudio();
    if (audioEl && !audioEl.paused) { audioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    const pending = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);

    try {
        if (mode === 'trim') enterTrimMode(seg, row);
        else enterSplitMode(seg, row, prePausePlayMs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        setPendingOp(null);
        clearEdit();
    }
}
