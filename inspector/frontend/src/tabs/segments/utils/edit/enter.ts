/**
 * enterEditWithBuffer — entry point for trim/split from event delegation.
 *
 * Kept in its own module so `edit-common.ts` can stay a dependency-leaf
 * of `edit-trim.ts` / `edit-split.ts` (those modules import `_playRange`
 * and `exitEditMode` from edit-common, so edit-common must not import them).
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { createOp, setPendingOp, snapshotSeg } from '../../stores/dirty';
import { clearEdit, editMode } from '../../stores/edit';
import {
    continuousPlay,
    segAudioElement,
} from '../../stores/playback';
import { stopSegAnimation } from '../playback/playback';
import { enterSplitMode } from './split';
import { enterTrimMode } from './trim';

export function enterEditWithBuffer(
    seg: Segment,
    row: HTMLElement,
    mode: 'trim' | 'split',
    contextCategory: string | null = null,
    mountId: symbol | null = null,
): void {
    if (get(editMode)) return;

    const audioEl = get(segAudioElement);
    const prePausePlayMs = !audioEl || audioEl.paused ? null : audioEl.currentTime * 1000;

    if (audioEl && !audioEl.paused) { audioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    const pending = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);

    try {
        if (mode === 'trim') enterTrimMode(seg, row, mountId);
        else enterSplitMode(seg, row, prePausePlayMs, mountId);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        setPendingOp(null);
        clearEdit();
    }
}
