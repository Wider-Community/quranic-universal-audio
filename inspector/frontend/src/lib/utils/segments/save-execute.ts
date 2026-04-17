/**
 * Execute the save operation — iterate dirty chapters, POST to server,
 * clean up dirty state on success.
 *
 * Extracted from segments/save.ts (Ph4a). Still has DOM side effects
 * (dom.segSaveBtn, dom.segPlayStatus) — those will move to the Svelte
 * component in Ph4b.
 */

import { dom } from '../../../segments/state';
import type { SegEditHistoryResponse, SegSaveResponse } from '../../../types/api';
import type { EditOp, Segment } from '../../../types/domain';
import { fetchJson, fetchJsonOrNull } from '../../api';
import { getChapterSegments } from '../../stores/segments/chapter';
import {
    clearDirtyMap,
    clearOpLog,
    deleteDirtyEntry,
    deleteOpLogEntry,
    getChapterOps,
    getDirtyMap,
    isDirty,
} from '../../stores/segments/dirty';
import { renderEditHistoryPanel } from './history-render';
import { refreshValidation } from './validation-refresh';

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
}

interface SavePayloadPatch {
    segments: SaveSegmentPayloadPatch[];
    operations: EditOp[];
}

// ---------------------------------------------------------------------------
// executeSave
// ---------------------------------------------------------------------------

export async function executeSave(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;

    dom.segSaveBtn.disabled = true;
    dom.segSaveBtn.textContent = 'Saving...';

    let savedChanges = 0;
    let savedChapters = 0;
    let allOk = true;

    try {
        for (const [ch, entry] of getDirtyMap()) {
            const chSegs: Segment[] = getChapterSegments(ch);
            let payload: SavePayloadFull | SavePayloadPatch;
            const chOps = getChapterOps(ch);

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
                        };
                        if (s.wrap_word_ranges) o.wrap_word_ranges = s.wrap_word_ranges;
                        if (s.has_repeated_words) o.has_repeated_words = true;
                        if (s.ignored_categories?.length) o.ignored_categories = s.ignored_categories;
                        return o;
                    }),
                    operations: chOps,
                };
                savedChanges += chOps.length;
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
                        };
                        if (seg.ignored_categories?.length) upd.ignored_categories = seg.ignored_categories;
                        updates.push(upd);
                    }
                }
                if (updates.length === 0) continue;
                payload = { segments: updates, operations: chOps };
                savedChanges += chOps.length;
            }

            const result = await fetchJson<SegSaveResponse & { error?: string }>(
                `/api/seg/save/${reciter}/${ch}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                },
            );
            if (!result.ok) {
                dom.segPlayStatus.textContent = `Save error (ch ${ch}): ${result.error}`;
                allOk = false;
                break;
            }
            deleteDirtyEntry(ch);
            deleteOpLogEntry(ch);
            savedChapters++;
        }

        if (allOk) {
            clearDirtyMap();
            clearOpLog();
            const msg = savedChapters > 1
                ? `Saved ${savedChanges} changes across ${savedChapters} chapters`
                : `Saved ${savedChanges} change${savedChanges !== 1 ? 's' : ''}`;
            dom.segSaveBtn.textContent = msg;
            document.querySelectorAll('.seg-row.dirty').forEach(r => r.classList.remove('dirty'));
            setTimeout(() => { dom.segSaveBtn.textContent = 'Save'; }, 2500);
            fetchJson(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' })
                .then(() => refreshValidation())
                .catch(() => refreshValidation());
            try {
                const hist = await fetchJsonOrNull<SegEditHistoryResponse>(
                    `/api/seg/edit-history/${reciter}`,
                );
                if (hist) {
                    renderEditHistoryPanel(hist);
                }
            } catch (_) { /* non-critical */ }
        } else {
            dom.segSaveBtn.disabled = !isDirty();
            dom.segSaveBtn.textContent = 'Save';
        }
    } catch (e) {
        console.error('Save failed:', e);
        dom.segPlayStatus.textContent = 'Save failed';
        dom.segSaveBtn.disabled = !isDirty();
        dom.segSaveBtn.textContent = 'Save';
    }
}
