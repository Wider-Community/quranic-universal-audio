/**
 * Build the save-preview data structure from dirty state + op log.
 * Pure function — no DOM side effects.
 */

import {
    getChapterOps,
    getDirtyMap,
} from '../../stores/segments/dirty';
import {
    countVersesFromBatches,
} from '../../stores/segments/history';
import type {
    SavePreviewBatch,
    SavePreviewData,
} from '../../stores/segments/save';
import type { HistoryBatch } from '../../types/domain';

export function buildSavePreviewData(): SavePreviewData {
    const batches: SavePreviewBatch[] = [];
    const warningChapters: number[] = [];
    const opCounts: Record<string, number> = {};
    const fixKindCounts: Record<string, number> = {};
    let totalOps = 0;

    for (const [ch, dirtyEntry] of getDirtyMap()) {
        const chOps = getChapterOps(ch);
        if (chOps.length === 0) { warningChapters.push(ch); continue; }
        for (const op of chOps) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            const kind = op.fix_kind || 'manual';
            fixKindCounts[kind] = (fixKindCounts[kind] || 0) + 1;
            totalOps++;
        }
        batches.push({
            batch_id: null,
            saved_at_utc: null,
            chapter: ch,
            save_mode: dirtyEntry.structural ? 'full_replace' : 'patch',
            operations: chOps,
        });
    }

    const summary = {
        total_operations: totalOps,
        total_batches: batches.length + warningChapters.length,
        chapters_edited: batches.length + warningChapters.length,
        verses_edited: countVersesFromBatches(batches as HistoryBatch[]),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
    return { batches, summary, warningChapters };
}
