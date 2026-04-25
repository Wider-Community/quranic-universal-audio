/**
 * Ignore-issue dispatcher.
 *
 * Wraps `applyCommand({type: 'ignoreIssue', ...})` and the live-store glue:
 * resolves the seg's chapter, finalizes the EditOp through `dirty.ts`,
 * marks the chapter dirty, and refreshes the seg via the chapter store.
 * The Svelte card component dispatches this wrapper instead of building
 * an op + mutation inline.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { refreshSegInStore, selectedChapter } from '../../stores/chapter';
import {
    finalizeOp,
    markDirty,
    setPendingOp,
} from '../../stores/dirty';
import { applyCommand } from '../../domain/apply-command';
import { isIgnoredFor } from '../validation/classified-issues';

/**
 * Mark `category` ignored on `seg` by dispatching an `ignoreIssue` command,
 * then commit the resulting op to the dirty store and refresh `seg` in
 * the chapter store.
 *
 * Returns false if the seg already has the category recorded (caller
 * should disable the Ignore button via reactive guard, but this is a
 * second line of defense for keyboard / programmatic entries).
 */
export function ignoreIssueOnSegment(seg: Segment, category: string): boolean {
    if (isIgnoredFor(seg, category)) return false;
    const segChapter = seg.chapter ?? parseInt(get(selectedChapter));

    // Reducer expects a uid-keyed slice. The dispatcher provides exactly the
    // target seg; auto-suppress is irrelevant for ignoreIssue (the category
    // append IS the suppression).
    const uid = seg.segment_uid;
    if (!uid) return false;
    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [segChapter]: [uid] },
            selectedChapter: segChapter,
        },
        { type: 'ignoreIssue', segmentUid: uid, category },
    );

    const updated = result.nextState.byId[uid];
    if (updated) {
        seg.ignored_categories = updated.ignored_categories
            ? [...updated.ignored_categories]
            : seg.ignored_categories;
        delete (seg as Segment & { _derived?: unknown })._derived;
    }
    markDirty(segChapter, seg.index);
    refreshSegInStore(seg);

    setPendingOp(null);
    finalizeOp(segChapter, result.operation);
    return true;
}
