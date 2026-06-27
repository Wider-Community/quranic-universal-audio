/**
 * Persist a report-mode session: turn the staged annotations into a batch
 * create + reconcile removals.
 *
 * Staged cells become `TsReportBatchItem`s (timing cells carry their subtype +
 * comment; tajweed cells carry subtype + selected rule tags + mandatory
 * comment). Seeded own-reports the user removed (originalId no longer staged)
 * are soft-deleted. Anonymous callers pass their localStorage token so the
 * backend keys + lets them edit later.
 */
import { currentUser } from '../../../lib/stores/current-user';
import { get } from 'svelte/store';

import type {
    TsReportBatchItem,
    TsReportTarget,
} from '../../../lib/types/generated/schemas';
import { getAnonToken } from '../../../lib/utils/anon-token';
import type { StagedAnnotation } from '../stores/report-mode';
import { createReportsBatch, deleteReport } from './reports-client';

function anonTokenIfNeeded(): string | null {
    return get(currentUser).hf_user_id === null ? getAnonToken() : null;
}

function toItem(a: StagedAnnotation): TsReportBatchItem {
    const target: TsReportTarget = a.target;
    if (a.kind === 'timing') {
        return {
            category: 'timing',
            subtype: a.subtype,
            target,
            comment: a.comment.trim() || null,
            selected_rule_tags: [],
        };
    }
    return {
        category: 'tajweed',
        subtype: a.subtype,
        target,
        comment: a.comment.trim() || null,
        selected_rule_tags: a.subtype === 'wrong_rule' ? a.selectedRuleTags : [],
    };
}

export interface SubmitResult {
    ok: boolean;
    error?: string;
}

/** Persist the session. `deleteIds` are the caller's own reports to remove. */
export async function submitReportSession(
    slug: string,
    verseKey: string,
    staged: StagedAnnotation[],
    deleteIds: number[],
): Promise<SubmitResult> {
    const anon = anonTokenIfNeeded();
    try {
        for (const id of deleteIds) {
            await deleteReport(slug, id, anon);
        }
        if (staged.length > 0) {
            const items = staged.map(toItem) as [TsReportBatchItem, ...TsReportBatchItem[]];
            const res = await createReportsBatch(slug, {
                verse_key: verseKey,
                items,
                anon_token: anon,
            });
            if (res?.error) return { ok: false, error: res.error };
        }
        return { ok: true };
    } catch (e) {
        return { ok: false, error: e instanceof Error ? e.message : 'Failed to submit' };
    }
}
