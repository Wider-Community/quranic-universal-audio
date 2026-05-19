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
import { segPort } from '../../stores/playback';
import { disposeSegRange, stopSegAnimation } from '../playback/playback';
import { resolveSegSource } from '../playback/source';
import { enterSplitMode } from './split';
import { enterTrimMode } from './trim';

export function enterEditWithBuffer(
    seg: Segment,
    row: HTMLElement,
    mode: 'trim' | 'split',
    contextCategory: string | null = null,
    mountId: symbol | null = null,
    chapterOverride: number | null = null,
    initialSplits: number[] | null = null,
    initialRefs: string[] | null = null,
): void {
    if (get(editMode)) return;

    const prePausePlayMs = segPort.paused ? null : segPort.currentTimeMs();

    // Resolve the seg's source up front so we can detect whether entering
    // edit mode requires switching audio (cross-chapter accordion) or can
    // piggy-back on the live chapter playhead (same-chapter same-reciter).
    const segSource = resolveSegSource(seg, chapterOverride);
    const portSource = segPort.source;
    const sameSource = !!segSource && !!portSource
        && portSource.audioUrl === segSource.audioUrl
        && portSource.reciter === segSource.reciter
        && portSource.vbr === segSource.vbr;

    // Auto-seeded splits (cross-verse / repetition cursors from `initialSplits`)
    // explicitly cold-start a preview loop in `enterSplitMode`; for that to
    // run cleanly we still need the legacy teardown (pause, dispose segRange,
    // setSource, loadCovering) even when same-source — segRange's `stop`
    // policy at seg.time_end would otherwise race the preview's loop wrap.
    // Manual Adjust / manual Split do NOT preview on entry — keep the chapter
    // playhead running through the seg so the user "continues from where it
    // plays" instead of getting yanked to seg.time_start.
    const willColdStartPreview = mode === 'split'
        && initialSplits != null && initialSplits.length > 0;
    const preservePlayback = !segPort.paused && sameSource && !willColdStartPreview;

    if (!preservePlayback) {
        if (!segPort.paused) { segPort.pause(); stopSegAnimation(); }
        // Tear down the main playhead rAF so it can't fire onto the audio
        // element while edit-preview owns it.
        disposeSegRange();

        // Bind the port to THIS seg's source. Cross-chapter Adjust/Split
        // (launched from a validation accordion row whose chapter ≠ active)
        // would otherwise build the wider clip from the active chapter's URL
        // — wrong audio. setSource is a no-op for active-chapter Adjust and
        // invalidates `_window` for cross-chapter so the loadCovering below
        // swaps to the row's chapter clip.
        if (segSource) segPort.setSource(segSource);

        // Pre-load the audio for the whole segment with edit-mode post-roll.
        // Under VBR the port keeps clip byte 0 aligned to seg.time_start; it
        // never reuses an earlier-starting clip for a later playback start,
        // because that would make the browser seek inside the streamed clip.
        // CBR chapters cover everything regardless, so no-op.
        segPort.loadCovering(seg.time_start, seg.time_end, EDIT_LOAD_PAD_MS);
    }

    const pending = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment',
        contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);

    try {
        if (mode === 'trim') enterTrimMode(seg, row, mountId);
        else enterSplitMode(seg, row, prePausePlayMs, mountId, initialSplits, initialRefs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        setPendingOp(null);
        clearEdit();
    }
}
