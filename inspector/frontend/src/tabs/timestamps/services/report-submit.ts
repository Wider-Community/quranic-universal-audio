/**
 * Persist a report-mode session: turn the staged annotations into a batch
 * create + reconcile removals.
 *
 * Staged cells become `TsReportBatchItem`s (timing cells carry their onset/offset
 * axes + optional comment; tajweed cells carry subtype + selected rule tags +
 * mandatory comment; phoneme cells carry just the target — no subtype/comment).
 * Seeded own-reports the user removed (originalId no longer staged) are
 * soft-deleted. Anonymous callers pass their localStorage token so the backend
 * keys + lets them edit later.
 */
import { currentUser } from '../../../lib/stores/current-user';
import { get } from 'svelte/store';

import type {
    TsReportBatchItem,
    TsReportTarget,
} from '../../../lib/types/generated/schemas';
import { getAnonToken } from '../../../lib/utils/anon-token';
import { isStagedComplete, type StagedAnnotation } from '../stores/report-mode';
import { createReportsBatch, deleteReport } from './reports-client';

function anonTokenIfNeeded(): string | null {
    return get(currentUser).hf_user_id === null ? getAnonToken() : null;
}

function toItem(a: StagedAnnotation): TsReportBatchItem {
    const target: TsReportTarget = a.target;
    if (a.kind === 'timing') {
        return {
            category: 'timing',
            onset: a.onset,
            offset: a.offset,
            target,
            comment: a.comment.trim() || null,
            selected_rule_tags: [],
        };
    }
    if (a.kind === 'phonemes') {
        return { category: 'phonemes', target, comment: null, selected_rule_tags: [] };
    }
    if (a.kind === 'silence') {
        const boundary = a.subtype === 'pause_boundary';
        return {
            category: 'silence',
            subtype: a.subtype,
            onset: boundary ? a.onset : null,
            offset: boundary ? a.offset : null,
            target,
            comment: null,
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
    // Defensive: only complete items persist (the UI auto-discards incompletes on
    // focus-move, but a half-filled focused cell may still be in the set).
    const ready = staged.filter(isStagedComplete);
    try {
        for (const id of deleteIds) {
            await deleteReport(slug, id, anon);
        }
        if (ready.length > 0) {
            const items = ready.map(toItem) as [TsReportBatchItem, ...TsReportBatchItem[]];
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
