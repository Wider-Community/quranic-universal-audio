/**
 * Execute the save operation — iterate dirty chapters, POST to server,
 * clean up dirty state on success.
 */

import { get as storeGet } from 'svelte/store';

import { fetchJson, fetchJsonOrNull } from '../../../../lib/api';
import { SIGN_IN_MESSAGES } from '../../../../lib/sign-in-messages';
import { openSignInModal } from '../../../../lib/stores/sign-in-modal';
import { pushToast } from '../../../../lib/stores/toast';
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
import { refreshStats, refreshValidation } from '../validation/refresh';
import { collectOpPeaks, type OpPeakRecord } from '../waveform/op-peaks';
export { buildPayloadFromCommandResult } from './payload';

// ---------------------------------------------------------------------------
// Payload types
// ---------------------------------------------------------------------------

// Note: matched_text is intentionally omitted from save payloads. The server
// derives it from matched_ref via dk_words (services/quran_refs.py::
// dk_text_for_ref) so detailed.json's matched_text stays consistent with the
// canonical reference text.
interface SaveSegmentPayloadFull {
    segment_uid: string;
    time_start: number;
    time_end: number;
    matched_ref: string;
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

        // Execute network requests for captured snapshots.
        // We use raw `fetch` so non-2xx responses surface a visible toast —
        // `fetchJson` swallows the HTTP status and the UI was failing silently
        // (Saving... stuck because dirty state never cleared on a 403/500).
        for (const { chapter: ch, payload, ops } of pendingSaves) {
            let res: Response;
            try {
                res = await fetch(`/api/seg/save/${reciter}/${ch}`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } catch (e) {
                console.error(`Save network error (ch ${ch}):`, e);
                pushToast({
                    kind: 'error',
                    text: `Save failed (network). Check your connection and try again.`,
                    ttl: 6000,
                });
                allOk = false;
                break;
            }
            if (!res.ok) {
                let errMsg = `Save failed (${res.status})`;
                try {
                    const body = await res.json() as { error?: string };
                    if (body?.error) errMsg = `Save failed: ${body.error}`;
                } catch { /* non-JSON body */ }
                console.error(`Save error (ch ${ch}, ${res.status}):`, errMsg);
                if (res.status === 401) {
                    openSignInModal(null, SIGN_IN_MESSAGES.save);
                } else {
                    pushToast({ kind: 'error', text: errMsg, ttl: 6000 });
                }
                allOk = false;
                break;
            }
            let result: SegSaveResponse & { error?: string };
            try {
                result = await res.json() as SegSaveResponse & { error?: string };
            } catch {
                pushToast({
                    kind: 'error',
                    text: 'Save returned a malformed response.',
                    ttl: 6000,
                });
                allOk = false;
                break;
            }
            if (!result.ok) {
                console.error(`Save error (ch ${ch}):`, result.error);
                pushToast({
                    kind: 'error',
                    text: result.error || 'Save failed (unknown error).',
                    ttl: 6000,
                });
                allOk = false;
                break;
            }
            // Safely clear only the operations we just saved
            clearSavedOps(ch, ops);
            savedChanges += ops.length;
            savedChapters++;
        }

        if (savedChapters > 0) {
            if (allOk) {
                const msg = savedChapters > 1
                    ? `Saved ${savedChanges} changes across ${savedChapters} chapters`
                    : `Saved ${savedChanges} change${savedChanges !== 1 ? 's' : ''}`;
                saveButtonLabel.set(msg);
                setTimeout(() => { saveButtonLabel.set('Save'); }, 2500);
            } else {
                saveButtonLabel.set('Save');
            }

            // Refresh validation, history, and stats whenever ANY chapter
            // saved — autosave and partial-success runs both need it so the
            // UI doesn't keep showing pre-edit counts and history rows.
            // Each fetch has its own try/catch so a single hiccup doesn't
            // skip the others.
            void refreshValidation().catch((e) => console.error('Error refreshing validation:', e));
            void refreshStats().catch((e) => console.error('Error refreshing stats:', e));
            try {
                const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
                    `/api/seg/edit-history/${reciter}`,
                );
                if (hist) {
                    renderEditHistoryPanel(hist);
                }
            } catch (_) { /* non-critical */ }
        } else {
            // Nothing saved (either nothing to save or error before first commit)
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
