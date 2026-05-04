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
import type { Segment } from '../../../../lib/types/domain';
import {
    refreshSegInStore,
    segAllData,
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
import { applyCommand } from '../../domain/apply-command';
import {
    _advanceRefByOneWord,
    _normalizeRef as _normalizeRefLib,
    _validateRefStructural,
    getVerseWordCounts,
    parseSegRef,
} from '../data/references';
import { stopSegAnimation } from '../playback/playback';
import type { RowEntry, RowInstanceRole } from '../playback/row-registry';
import { getRowEntriesFor } from '../playback/row-registry';
import { finalizeEdit } from './common';

// ---------------------------------------------------------------------------
// beginRefEdit — enter reference-edit mode for a segment
// ---------------------------------------------------------------------------

/**
 * Initial selection range for the ReferenceEditor input on the next mount.
 * Set transiently by `_handoffPendingChain` so the chain-mounted second-half
 * editor can place the cursor at the dash boundary instead of selecting the
 * whole prefilled value. Cleared by ReferenceEditor on mount.
 */
let _pendingInitialSelection: { from: number; to: number } | null = null;

export function consumePendingInitialSelection(): { from: number; to: number } | null {
    const v = _pendingInitialSelection;
    _pendingInitialSelection = null;
    return v;
}

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
 * Apply a reference change through `applyCommand` and finalize the op.
 * Mutates `seg` in place from the reducer's `nextState`, clears derived
 * cache, marks dirty, refreshes the seg in the chapter store, and feeds
 * `result.operation` into `finalizeEdit`.
 *
 * `opType` selects 'confirm_reference' for the audit-confirm path (user
 * pressed Enter on an unchanged ref to clear a low-confidence flag) vs
 * 'edit_reference' for an actual ref change.
 */
function _dispatchRefEdit(
    seg: Segment,
    chapter: number,
    matched_ref: string,
    matched_text: string,
    display_text: string,
    contextCategory: string | null,
    opType: 'edit_reference' | 'confirm_reference',
): void {
    const uid = seg.segment_uid;
    if (!uid) {
        // Defensive: legacy fixtures without uids skip the reducer; mutate
        // in place and mark dirty so the row still renders the new values.
        seg.matched_ref = matched_ref;
        seg.matched_text = matched_text;
        seg.display_text = display_text;
        seg.confidence = 1.0;
        delete seg._derived;
        markDirty(chapter, seg.index);
        refreshSegInStore(seg);
        setPendingOp(null);
        return;
    }
    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [chapter]: [uid] },
            selectedChapter: chapter,
        },
        {
            type: 'editReference',
            segmentUid: uid,
            matched_ref,
            matched_text,
            display_text,
            sourceCategory: contextCategory ?? undefined,
            contextCategory: contextCategory ?? undefined,
            opType,
            fixKind: opType === 'confirm_reference' ? 'audit' : 'manual',
        },
    );
    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.matched_ref = updated.matched_ref;
        seg.matched_text = updated.matched_text;
        seg.display_text = updated.display_text;
        seg.confidence = updated.confidence;
        if (updated.ignored_categories) {
            seg.ignored_categories = [...updated.ignored_categories];
        }
    }
    delete seg._derived;
    markDirty(chapter, seg.index);
    refreshSegInStore(seg);
    setPendingOp(null);
    finalizeEdit(result.operation, chapter, [seg], {
        skipSilence: true,
        skipFilterRender: true,
        skipAccordion: true,
        patch: result.patch,
    });
}

export type CommitRefResult =
    | { status: 'ok' }
    | { status: 'invalid'; reason: 'malformed' | 'unknown_verse' | 'resolve_failed' };

export async function commitRefEdit(seg: Segment, newRefIn: string): Promise<CommitRefResult> {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const vwc = getVerseWordCounts();
    const normalized = _normalizeRefLib(newRefIn, vwc) ?? '';
    const pending = getPendingOp();
    const ctxCat = pending?.op_context_category ?? null;

    if (normalized === oldRef) {
        if ((seg.confidence ?? 0) < 1.0) {
            // Audit confirm: user pressed Enter on an unchanged low-confidence
            // ref. Records a 'confirm_reference' op with fix_kind='audit' and
            // bumps confidence to 1.0. Ref + text fields stay as-is.
            _dispatchRefEdit(
                seg,
                chapter,
                seg.matched_ref || '',
                seg.matched_text || '',
                seg.display_text || '',
                ctxCat,
                'confirm_reference',
            );
        } else {
            setPendingOp(null);
        }
        clearEdit();
        await _handoffPendingChain();
        return { status: 'ok' };
    }

    // Structural validation: malformed / unknown_verse → reject and let the
    // editor surface a red badge for re-entry. word_overshoot → silently fix
    // by clamping the word to the verse's max.
    let candidate = normalized;
    if (candidate) {
        const v = _validateRefStructural(candidate, vwc);
        if (!v.ok) {
            if (v.reason === 'word_overshoot' && v.clamped) {
                candidate = v.clamped;
            } else if (v.reason === 'malformed' || v.reason === 'unknown_verse') {
                return { status: 'invalid', reason: v.reason };
            }
        }
    }

    let matchedText = '';
    let displayText = '';
    if (candidate) {
        try {
            const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(candidate)}`,
            );
            if (data.text) {
                matchedText = data.text;
                displayText = data.display_text || data.text;
            } else {
                // Backend rejected the ref (or returned empty text). Treat as
                // invalid so the user can re-enter rather than committing a
                // junk display string into matched_text.
                if (data.error) console.warn('resolve_ref error:', data.error);
                return { status: 'invalid', reason: 'resolve_failed' };
            }
        } catch (e) {
            console.error('Failed to resolve ref:', e);
            return { status: 'invalid', reason: 'resolve_failed' };
        }
    }

    _dispatchRefEdit(seg, chapter, candidate, matchedText, displayText, ctxCat, 'edit_reference');
    clearEdit();
    await _handoffPendingChain();
    return { status: 'ok' };
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
async function _handoffPendingChain(): Promise<void> {
    const chain = get(pendingChainTarget);
    pendingChainTarget.set(null);
    if (!chain) return;

    const chapter = chain.seg.chapter ?? parseInt(get(selectedChapter));
    const entries = getRowEntriesFor(chapter, chain.seg.index);
    const mountId = _pickHandoffMountId(entries);
    // No row mounted → nothing to claim a programmatic beginRefEdit. Abort
    // the chain; user can Edit Ref manually on the second half later.
    if (!mountId) return;

    // Rebuild the second-half ref as `(advance(committedFirstEnd))-(originalEnd)`
    // ONLY when the user actually trimmed the first half — i.e. its committed
    // end is strictly before the original segment's end. When the user kept
    // first half = full original range (pressed Enter without changing the
    // suggested ref, or the suggestion already covered the whole segment),
    // advancing would push past the original range and produce an invalid ref
    // like `2:5:8-2:5:7` (single-verse split where both halves inherited the
    // full ref) or otherwise overshoot. In that case leave the second half's
    // ref untouched so the editor opens with whatever was set at split time.
    if (chain.originalEndRef) {
        const origEndParts = chain.originalEndRef.split(':').map(Number);
        const origAyah = origEndParts[1];
        const origWord = origEndParts[2];
        const all = get(segAllData);
        let firstEndRef: string | null = null;
        if (all) {
            const i = all.segments.findIndex(s =>
                s.segment_uid === chain.seg.segment_uid ||
                (s.chapter === chapter && s.index === chain.seg.index),
            );
            if (i > 0) {
                const prev = all.segments[i - 1];
                if (prev && prev.chapter === chapter) firstEndRef = prev.matched_ref ?? null;
            }
        }
        const firstParsed = parseSegRef(firstEndRef);
        const vwc = getVerseWordCounts();
        // Trim guard: only advance when first half ends BEFORE original end.
        const firstTrimmed = !!firstParsed && origAyah != null && origWord != null && (
            firstParsed.ayah_to < origAyah ||
            (firstParsed.ayah_to === origAyah && firstParsed.word_to < origWord)
        );
        if (firstParsed && firstTrimmed) {
            const next = _advanceRefByOneWord(
                { surah: firstParsed.surah, ayah: firstParsed.ayah_to, word: firstParsed.word_to },
                vwc,
            );
            if (next) {
                const rebuilt = `${next.surah}:${next.ayah}:${next.word}-${chain.originalEndRef}`;
                chain.seg.matched_ref = rebuilt;
                // Re-resolve text so the editor opens with matching matched_text
                // and display_text. Failures fall back silently to the existing
                // values; the user can correct the ref themselves.
                try {
                    const data = await fetchJson<SegResolveRefResponse & { error?: string }>(
                        `/api/seg/resolve_ref?ref=${encodeURIComponent(rebuilt)}`,
                    );
                    if (data.text) {
                        chain.seg.matched_text = data.text;
                        chain.seg.display_text = data.display_text || data.text;
                    }
                } catch (e) {
                    console.warn('chain re-resolve failed', e);
                }
                // Cursor lands right after the dash so the user can edit only
                // the end portion. Selection runs from `from` to end of value.
                const dash = rebuilt.indexOf('-');
                if (dash >= 0) {
                    _pendingInitialSelection = { from: dash + 1, to: rebuilt.length };
                }
            }
        }
    }

    beginRefEdit(chain.seg, chain.category, mountId);
}
