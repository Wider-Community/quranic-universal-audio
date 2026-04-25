/**
 * Reference editing: beginRefEdit (store setter) + commitRefEdit (apply).
 *
 * The inline `<input>` is owned by `tabs/segments/edit/ReferenceEditor.svelte`,
 * which is conditionally mounted by SegmentRow in place of the `.seg-text-ref`
 * span when the row is the current reference-edit target. This module only
 * owns the store/pending-op transitions and the async commit path.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegResolveRefResponse } from '../../../../lib/types/api';
import type { EditOp, Segment } from '../../../../lib/types/domain';
import {
    refreshSegInStore,
    selectedChapter,
} from '../../stores/chapter';
import {
    createOp,
    getPendingOp,
    markDirty,
    setPendingOp,
    snapshotSeg,
} from '../../stores/dirty';
import {
    clearEdit,
    pendingChainTarget,
    setEdit,
    setEditingSegIndex,
} from '../../stores/edit';
import {
    continuousPlay,
    segAudioElement,
} from '../../stores/playback';
import { applyAutoSuppress } from '../../domain/registry';
import { _normalizeRef as _normalizeRefLib, getVerseWordCounts } from '../data/references';
import { stopSegAnimation } from '../playback/playback';
import type { RowEntry, RowInstanceRole } from '../playback/row-registry';
import { getRowEntriesFor } from '../playback/row-registry';
import { finalizeEdit } from './common';

function _normalizeRef(ref: Parameters<typeof _normalizeRefLib>[0]): ReturnType<typeof _normalizeRefLib> {
    return _normalizeRefLib(ref, getVerseWordCounts());
}

// ---------------------------------------------------------------------------
// beginRefEdit — enter reference-edit mode for a segment
// ---------------------------------------------------------------------------

/**
 * Enter reference-edit mode for `seg`. Pauses audio, creates the pending op,
 * and flips the edit store. SegmentRow reactively swaps the `.seg-text-ref`
 * span for a `<ReferenceEditor>` input once the store updates.
 *
 * `mountId` (optional) pins the initiating SegmentRow instance so its twins
 * stay passive. Pass `null` only for programmatic entries that are OK routing
 * to the main-list row via the `editingMountId === null && instanceRole ===
 * 'main'` fallback in `SegmentRow.svelte` (e.g. keyboard `E`). Callers that
 * might land on a non-current-chapter segment (split-chain handoff) should
 * resolve a concrete mountId from the row registry first via
 * `pickProgrammaticMountId(chapter, index)` — otherwise, if no main-list row
 * is mounted, the edit sits with `editMode='reference'` and nothing claiming
 * it, silently blocking subsequent Split/Adjust clicks.
 */
export function beginRefEdit(
    seg: Segment,
    contextCategory: string | null = null,
    mountId: symbol | null = null,
): void {
    const audioEl = get(segAudioElement);
    if (audioEl && !audioEl.paused) { audioEl.pause(); stopSegAnimation(); }
    continuousPlay.set(false);

    setEdit('reference', seg.segment_uid ?? null, mountId);
    setEditingSegIndex(seg.index);

    const pending = createOp('edit_reference', contextCategory ? { contextCategory } : undefined);
    pending.targets_before = [snapshotSeg(seg)];
    setPendingOp(pending);
}

// ---------------------------------------------------------------------------
// commitRefEdit — resolve reference and apply edit
// ---------------------------------------------------------------------------

/**
 * Shared tail for both commitRefEdit branches: route the op-context category
 * through the registry's auto-suppress helper, clear derived cache, mark
 * dirty, re-publish the seg to the store, and finalize the pending op.
 */
function _applyRefChange(seg: Segment, pending: EditOp | null, chapter: number): void {
    const ctxCat = pending?.op_context_category;
    if (ctxCat) applyAutoSuppress(seg, ctxCat, 'card');
    delete seg._derived;
    markDirty(chapter, seg.index);
    refreshSegInStore(seg);
    if (pending) {
        finalizeEdit(pending, chapter, [seg], {
            skipSilence: true,
            skipFilterRender: true,
            skipAccordion: true,
        });
    }
}

export async function commitRefEdit(seg: Segment, newRefIn: string): Promise<void> {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const newRef = _normalizeRef(newRefIn) ?? '';
    if (newRef === oldRef) {
        if ((seg.confidence ?? 0) < 1.0) {
            const pending = getPendingOp();
            if (pending) {
                pending.op_type = 'confirm_reference';
                pending.fix_kind = 'audit';
            }
            seg.confidence = 1.0;
            _applyRefChange(seg, pending, chapter);
        } else {
            setPendingOp(null);
        }
        clearEdit();
        _handoffPendingChain();
        return;
    }

    seg.matched_ref = newRef;
    seg.confidence = 1.0;
    const pending = getPendingOp();

    if (newRef) {
        try {
            const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`,
            );
            if (data.text) {
                seg.matched_text = data.text;
                seg.display_text = data.display_text || data.text;
            } else if (data.error) {
                console.warn('resolve_ref error:', data.error);
                seg.matched_text = '(invalid ref)';
                seg.display_text = '';
            }
        } catch (e) {
            console.error('Failed to resolve ref:', e);
            seg.matched_text = '(resolve failed)';
            seg.display_text = '';
        }
    } else {
        seg.matched_text = '';
        seg.display_text = '';
    }

    _applyRefChange(seg, pending, chapter);
    clearEdit();
    _handoffPendingChain();
}

/** Priority order for picking a mount when handing the chain off to a
 *  programmatic ref-edit. Accordion wins because the user's current
 *  viewing context (when they initiated the split) is typically the
 *  accordion card — keeping the ref editor there preserves continuity.
 *  Main is the natural fallback for the normal list editing flow.
 *  history / preview are readOnly and never register with the row
 *  registry, so they'll never appear in lookups — they're in the list
 *  only for type exhaustiveness. */
const _HANDOFF_ROLE_PREFERENCE: readonly RowInstanceRole[] = [
    'accordion',
    'main',
    'history',
    'preview',
];

/** Walk registry entries for a (chapter, index) pair and pick the best
 *  mountId to claim a programmatic edit. Exported for `confirmSplit` so
 *  keyboard-initiated splits (mountId=null) can fall back to an
 *  accordion mount if one exists. Returns `null` when no row is mounted
 *  — callers should treat that as "skip the edit; nothing can claim it". */
export function pickProgrammaticMountId(chapter: number, index: number): symbol | null {
    return _pickHandoffMountId(getRowEntriesFor(chapter, index));
}

function _pickHandoffMountId(entries: Iterable<RowEntry>): symbol | null {
    const byRole = new Map<RowInstanceRole, symbol>();
    for (const entry of entries) {
        if (!byRole.has(entry.instanceRole)) byRole.set(entry.instanceRole, entry.mountId);
    }
    for (const role of _HANDOFF_ROLE_PREFERENCE) {
        const m = byRole.get(role);
        if (m) return m;
    }
    return null;
}

/** Read-and-clear `pendingChainTarget`; if set, synchronously enter ref-edit
 *  mode on the chained segment. Called after `clearEdit()` so `setEdit` in
 *  `beginRefEdit` transitions from a clean `null` edit state rather than
 *  overlapping with the just-committed one.
 *
 *  Resolves the target mount via the row registry. If no row is currently
 *  mounted for (chapter, chain.seg.index) — user navigated away, the row was
 *  virtualized out, the chain target is in another chapter — we SKIP the
 *  chain entirely rather than calling `beginRefEdit` with `mountId=null` and
 *  nothing to claim it. An orphaned beginRefEdit would leave
 *  `editMode='reference'` stuck with no UI, silently blocking subsequent
 *  Split/Adjust/Edit Ref clicks (the `enterEditWithBuffer` + other guards
 *  bail early on any non-null editMode). */
function _handoffPendingChain(): void {
    const chain = get(pendingChainTarget);
    pendingChainTarget.set(null);
    if (!chain) return;

    const chapter = chain.seg.chapter ?? parseInt(get(selectedChapter));
    const entries = getRowEntriesFor(chapter, chain.seg.index);
    const mountId = _pickHandoffMountId(entries);
    // No row mounted → nothing to claim a programmatic beginRefEdit. Abort
    // the chain; user can Edit Ref manually on the second half later.
    if (!mountId) return;

    beginRefEdit(chain.seg, chain.category, mountId);
}
