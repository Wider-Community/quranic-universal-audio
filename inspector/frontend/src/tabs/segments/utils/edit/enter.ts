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
import { disposeSegRange } from '../playback/playback';
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

    // The edit-preview rAF (`_playRange` / `attachPreviewLoop`) takes
    // over the audio element next. Tear down the chapter-cursor rAF +
    // any bounded segment range so they can't race the preview loop —
    // segRange's `stop` policy at seg.time_end would otherwise pause
    // playback right when the preview loop wants to wrap back to its
    // loop-start. We do NOT call `segPort.pause()` here: the warm path
    // (audio playing inside the trim window / split region) keeps the
    // chapter playhead running; the cold path's `seekAndPlay` inside
    // `_playRange` resumes playback explicitly. `stopSegAnimation` is
    // implied by `disposeSegRange` so we can drop the extra call.
    disposeSegRange();

    // Bind the port to THIS seg's source. Cross-chapter Adjust/Split
    // (launched from a validation accordion row whose chapter ≠ active)
    // would otherwise build the wider clip from the active chapter's URL
    // — wrong audio. `setSource` is `_sameSource`-guarded so same-chapter
    // is a no-op; cross-chapter invalidates `_window` and the
    // loadCovering below issues a fresh clip request.
    const segSource = resolveSegSource(seg, chapterOverride);
    if (segSource) segPort.setSource(segSource);

    // Pre-load the audio for the whole segment with edit-mode post-roll.
    // Under VBR the port keeps clip byte 0 aligned to seg.time_start; it
    // never reuses an earlier-starting clip for a later playback start,
    // because that would make the browser seek inside the streamed clip.
    // CBR chapters cover everything regardless, so no-op.
    segPort.loadCovering(seg.time_start, seg.time_end, EDIT_LOAD_PAD_MS);

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
