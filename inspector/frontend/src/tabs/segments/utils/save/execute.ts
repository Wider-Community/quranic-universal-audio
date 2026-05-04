/**
 * Execute the save operation — iterate dirty chapters, POST to server,
 * clean up dirty state on success.
 */

import { get as storeGet } from 'svelte/store';

import { fetchJson, fetchJsonOrNull } from '../../../../lib/api';
import type { SegEditHistoryResponse, SegSaveResponse } from '../../../../lib/types/api';
import type { EditOp, Segment } from '../../../../lib/types/domain';
import {
    getChapterSegments,
    selectedReciter,
} from '../../stores/chapter';
import {
    clearSavedOps,
    getChapterOps,
    getDirtyMap,
} from '../../stores/dirty';
import { saveButtonLabel } from '../../stores/save';
import { renderEditHistoryPanel } from '../history/render';
import { refreshValidation } from '../validation/refresh';
import { collectOpPeaks, type OpPeakRecord } from '../waveform/op-peaks';

// ---------------------------------------------------------------------------
// Payload types
// ---------------------------------------------------------------------------

interface SaveSegmentPayloadFull {
    segment_uid: string;
    time_start: number;
    time_end: number;
    matched_ref: string;
    matched_text: string;
    confidence: number;
    phonemes_asr: string;
    audio_url: string;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    ignored_categories?: string[];
}

interface SaveSegmentPayloadPatch {
    index: number;
    segment_uid: string;
    matched_ref: string;
    matched_text: string;
    confidence: number;
    ignored_categories?: string[];
}

interface SavePayloadFull {
    full_replace: true;
    segments: SaveSegmentPayloadFull[];
    operations: EditOp[];
    op_peaks?: OpPeakRecord[];
}

interface SavePayloadPatch {
    segments: SaveSegmentPayloadPatch[];
    operations: EditOp[];
    op_peaks?: OpPeakRecord[];
}

// ---------------------------------------------------------------------------
// CommandResult → save payload bridge
// ---------------------------------------------------------------------------

interface CommandResultLike {
    operation: EditOp & { type?: string; [k: string]: unknown };
    affectedChapters?: number[];
    patch?: unknown;
    [k: string]: unknown;
}

/**
 * Build a partial save payload from a `CommandResult`.
 *
 * Used by command-layer call sites that want to inspect the payload shape
 * (or pre-bundle it for save) without going through the full
 * dirty-map iteration in `executeSave`. The returned object carries the
 * same `{segments, operations}` envelope that `/api/seg/save` accepts;
 * the segments slice is left empty here — callers fill it from the
 * mutated chapter ids carried by `result.affectedChapters`.
 *
 * In production, dispatchers attach `result.patch` to `result.operation`
 * at finalize time (`finalizeEdit` / direct dispatcher writes), so
 * `executeSave`'s loop reads patch off the op naturally. This helper
 * also accepts the legacy `result.patch` shape as a fallback for callers
 * that still pass it at the result level.
 */
export function buildPayloadFromCommandResult(result: CommandResultLike): {
    segments: SaveSegmentPayloadPatch[];
    operations: EditOp[];
    affected_chapters: number[];
} {
    const op: EditOp & { patch?: unknown } = { ...result.operation };
    if (op.patch === undefined && result.patch != null) {
        op.patch = result.patch as EditOp['patch'];
    }
    return {
        segments: [],
        operations: [op],
        affected_chapters: result.affectedChapters ?? [],
    };
}

// ---------------------------------------------------------------------------
// executeSave
// ---------------------------------------------------------------------------

function isChapterHalfDirty(chOps: EditOp[]): boolean {
    const splitOps = chOps.filter(o => o.op_type === 'split_segment');
    if (splitOps.length === 0) return false;

    for (const splitOp of splitOps) {
        const afterSegs = splitOp.targets_after as Record<string, any>[] | undefined;
        if (!afterSegs || afterSegs.length < 2) continue;
        
        const uid1 = afterSegs[0]!.segment_uid as string;
        const uid2 = afterSegs[1]!.segment_uid as string;
        
        if (!uid1 || !uid2) continue;

        let uid1Confirmed = false;
        let uid2Confirmed = false;

        const splitIndex = chOps.indexOf(splitOp);
        for (let i = splitIndex + 1; i < chOps.length; i++) {
            const o = chOps[i];
            if (!o) continue;
            
            if (o.op_type === 'edit_reference' || o.op_type === 'confirm_reference') {
                const ta = o.targets_after as Record<string, any>[] | undefined;
                if (ta && ta[0] && ta[0].segment_uid === uid1) uid1Confirmed = true;
                if (ta && ta[0] && ta[0].segment_uid === uid2) uid2Confirmed = true;
            }
            
            if (o.op_type === 'merge_segments' || o.op_type === 'delete_segment') {
                const tb = o.targets_before as Record<string, any>[] | undefined;
                if (tb) {
                    if (tb.some(t => t.segment_uid === uid1)) uid1Confirmed = true;
                    if (tb.some(t => t.segment_uid === uid2)) uid2Confirmed = true;
                }
            }
        }

        if (!uid1Confirmed || !uid2Confirmed) return true;
    }
    
    return false;
}

let _isSaving = false;
let _saveQueued = false;
let _queuedIsAutoSave = true;

export async function executeSave(isAutoSave = false): Promise<void> {
    if (_isSaving) {
        _saveQueued = true;
        if (!isAutoSave) _queuedIsAutoSave = false;
        return;
    }
    
    const reciter = storeGet(selectedReciter);
    if (!reciter) return;

    _isSaving = true;
    _saveQueued = false;
    const isCurrentRunAutoSave = isAutoSave;
    _queuedIsAutoSave = true;

    saveButtonLabel.set('Saving...');

    let savedChanges = 0;
    let savedChapters = 0;
    let allOk = true;

    try {
        // Snapshot the operations and build payloads BEFORE yielding to network IO
        // so that concurrent edits arriving during the fetch don't get mixed in.
        const pendingSaves = [];

        for (const [ch, entry] of getDirtyMap()) {
            const chOps = [...getChapterOps(ch)]; // copy array of current ops
            
            // Skip autosave for chapters with an incomplete (half-dirty) split
            if (isCurrentRunAutoSave && isChapterHalfDirty(chOps)) {
                continue;
            }
            
            const chSegs: Segment[] = getChapterSegments(ch);
            let payload: SavePayloadFull | SavePayloadPatch | null = null;

            if (entry.structural) {
                payload = {
                    full_replace: true,
                    segments: chSegs.map(s => {
                        const o: SaveSegmentPayloadFull = {
                            segment_uid: s.segment_uid || '',
                            time_start: s.time_start,
                            time_end: s.time_end,
                            matched_ref: s.matched_ref,
                            matched_text: s.matched_text,
                            confidence: s.confidence,
                            phonemes_asr: s.phonemes_asr || '',
                            audio_url: s.audio_url || '',
                            ignored_categories: s.ignored_categories ?? [],
                        };
                        if (s.wrap_word_ranges) o.wrap_word_ranges = s.wrap_word_ranges;
                        if (s.has_repeated_words) o.has_repeated_words = true;
                        return o;
                    }),
                    operations: chOps,
                };
            } else {
                const updates: SaveSegmentPayloadPatch[] = [];
                for (const idx of entry.indices) {
                    const seg = chSegs.find(s => s.index === idx);
                    if (seg) {
                        const upd: SaveSegmentPayloadPatch = {
                            index: seg.index,
                            segment_uid: seg.segment_uid || '',
                            matched_ref: seg.matched_ref,
                            matched_text: seg.matched_text,
                            confidence: seg.confidence,
                            ignored_categories: seg.ignored_categories ?? [],
                        };
                        updates.push(upd);
                    }
                }
                if (updates.length > 0) {
                    payload = { segments: updates, operations: chOps };
                }
            }

            if (!payload) continue;

            // Pull peaks from in-memory caches for every op that has them.
            const opPeaks = collectOpPeaks(chOps);
            if (opPeaks.length > 0) payload.op_peaks = opPeaks;

            pendingSaves.push({ chapter: ch, payload, ops: chOps });
        }

        // Execute network requests for captured snapshots
        for (const { chapter: ch, payload, ops } of pendingSaves) {
            const result = await fetchJson<SegSaveResponse & { error?: string }>(
                `/api/seg/save/${reciter}/${ch}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );
            if (!result.ok) {
                console.error(`Save error (ch ${ch}):`, result.error);
                allOk = false;
                break;
            }
            // Safely clear only the operations we just saved
            clearSavedOps(ch, ops);
            savedChanges += ops.length;
            savedChapters++;
        }

        if (allOk && savedChapters > 0) {
            const msg = savedChapters > 1
                ? `Saved ${savedChanges} changes across ${savedChapters} chapters`
                : `Saved ${savedChanges} change${savedChanges !== 1 ? 's' : ''}`;
            saveButtonLabel.set(msg);
            setTimeout(() => { saveButtonLabel.set('Save'); }, 2500);
            
            fetchJson(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' })
                .then(() => {
                    if (!isCurrentRunAutoSave) {
                        return refreshValidation();
                    }
                })
                .catch((err: unknown) => { console.warn('trigger-validation failed:', err); });
            
            try {
                const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
                    `/api/seg/edit-history/${reciter}`,
                );
                if (hist) {
                    renderEditHistoryPanel(hist);
                }
            } catch (_) { /* non-critical */ }
        } else if (allOk && savedChapters === 0) {
            // Nothing to save
            saveButtonLabel.set('Save');
        } else {
            // Error occurred
            saveButtonLabel.set('Save');
        }
    } catch (e) {
        console.error('Save failed:', e);
        saveButtonLabel.set('Save');
    } finally {
        _isSaving = false;
        if (_saveQueued) {
            // Give a short breather, then process queued save
            const isAuto = _queuedIsAutoSave;
            setTimeout(() => { void executeSave(isAuto); }, 50);
        }
    }
}
