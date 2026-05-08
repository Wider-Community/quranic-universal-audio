/**
 * enterEditWithBuffer — entry point for trim/split from event delegation.
 *
 * Kept in its own module so `edit-common.ts` can stay a dependency-leaf
 * of `edit-trim.ts` / `edit-split.ts` (those modules import `_playRange`
 * and `exitEditMode` from edit-common, so edit-common must not import them).
 */

import { get } from 'svelte/store';

import { EDIT_LOAD_PAD_MS } from '../../../../lib/playback/constants';
import type { Segment } from '../../../../lib/types/domain';
import { createOp, setPendingOp, snapshotSeg } from '../../stores/dirty';
import { clearEdit, editMode } from '../../stores/edit';
import {
    continuousPlay,
    segPort,
} from '../../stores/playback';
import { disposeSegRange, stopSegAnimation } from '../playback/playback';
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

    const prePausePlayMs = segPort.paused ? null : segPort.currentTimeMs();

    if (!segPort.paused) { segPort.pause(); stopSegAnimation(); }
    // Dispose the segments-main AudioRange so its rAF + pending advance gap
    // can't fire onto the audio element while edit-preview owns it.
    disposeSegRange();
    continuousPlay.set(false);

    // Pre-load the audio for the whole segment ± edit-mode padding. Under
    // VBR this issues ONE ffmpeg invocation that covers all subsequent
    // edit-preview operations: split-left toggle, split-right toggle, trim
    // nudge, click-to-seek inside the row. Each of those was previously
    // its own clip URL → bug #2 (split latency) and #3 (drag past clip
    // edge had no audio). Now the port's idempotent fast path absorbs
    // them. CBR chapters cover everything regardless, so no-op.
    segPort.loadCovering(seg.time_start, seg.time_end, EDIT_LOAD_PAD_MS);

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
