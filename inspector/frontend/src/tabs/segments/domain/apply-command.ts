/**
 * applyCommand — pure reducer over a segment-slice + a SegmentCommand.
 *
 * Builds the EditOp record (snapshots + targetSegmentIndex), computes
 * mutated segments per command type, runs the registry's auto-suppress
 * rule when a `sourceCategory` is supplied, and returns a `CommandResult`
 * the dispatcher applies to the live stores.
 *
 * The reducer is pure: it does not touch the dirty/edit/playback stores,
 * does not perform I/O, does not mutate inputs. Side effects are the
 * dispatcher's job.
 */

import type { EditOp, Segment } from '../../../lib/types/domain';
import { snapshotSeg } from '../stores/dirty';
import type { SegSnapshot } from '../stores/dirty';
import {
    applyAutoSuppress,
    IssueRegistry,
} from './registry';
import type {
    ApplyCommandContext,
    ApplyCommandState,
    CommandNextState,
    CommandOperation,
    CommandResult,
    DeleteCommand,
    EditFromCardCommand,
    EditReferenceCommand,
    IgnoreIssueCommand,
    MergeCommand,
    Operation,
    SegmentCommand,
    SegmentPatch,
    SplitCommand,
    TrimCommand,
    AutoFixMissingWordCommand,
} from './command';

// ---------------------------------------------------------------------------
// Op-type translation
// ---------------------------------------------------------------------------

/**
 * Wire-level op_type names persisted in the operation log. Mirrors the
 * `createOp` call sites in the edit utilities so the save payload and
 * history records keep their existing shape.
 */
const OP_TYPE_BY_COMMAND: Readonly<Record<Operation, string>> = Object.freeze({
    trim: 'trim_segment',
    split: 'split_segment',
    merge: 'merge_segments',
    editReference: 'edit_reference',
    delete: 'delete_segment',
    ignoreIssue: 'ignore_issue',
    autoFixMissingWord: 'auto_fix_missing_word',
    editFromCard: 'edit_from_card',
});

const STRUCTURAL_COMMANDS: ReadonlySet<Operation> = new Set([
    'trim',
    'split',
    'merge',
    'delete',
]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _now(ctx?: ApplyCommandContext): string {
    return (ctx?.now ?? (() => new Date().toISOString()))();
}

function _newUid(ctx?: ApplyCommandContext): string {
    return (ctx?.uid ?? (() => crypto.randomUUID()))();
}

function _kindFor(type: Operation): 'single-index' | 'structural' {
    return STRUCTURAL_COMMANDS.has(type) ? 'structural' : 'single-index';
}

/** Resolve the chapter for a segment, falling back to selectedChapter when
 *  the segment lacks a `chapter` field (mid-test fixtures sometimes omit it). */
function _chapterFor(seg: Segment | undefined, state: ApplyCommandState): number {
    const fromSeg = seg?.chapter;
    if (typeof fromSeg === 'number' && Number.isFinite(fromSeg)) return fromSeg;
    for (const [chStr, ids] of Object.entries(state.idsByChapter)) {
        if (seg?.segment_uid && ids.includes(seg.segment_uid)) return parseInt(chStr);
    }
    return state.selectedChapter ?? 0;
}

/** Find a segment by uid; falls back to scanning idsByChapter+byId for
 *  test fixtures that don't pre-populate `byId` exhaustively. */
function _findSeg(state: ApplyCommandState, uid: string): Segment | undefined {
    return state.byId[uid];
}

/** Phase 3 patch stub: undefined until Phase 5 fills the inverse-patch
 *  arrays. The type carries `patch?: SegmentPatch`; Phase 3 leaves the
 *  field absent so callers know the result lacks an inverse-patch (Phase 5
 *  populates it with `before`/`after`/`removedIds`/`insertedIds`).
 *
 *  `affectedChapters` is accepted so the Phase 5 fill site can reuse the
 *  same call shape without changing call sites. */
function _emptyPatch(affectedChapters: number[]): SegmentPatch | undefined {
    void affectedChapters;
    return undefined;
}

function _baseOperation(
    cmd: SegmentCommand,
    targetSeg: Segment | undefined,
    chapter: number,
    targetIndex: number,
    ctx: ApplyCommandContext | undefined,
): CommandOperation {
    void targetSeg;
    const startedAt = _now(ctx);
    const op: CommandOperation = {
        op_id: _newUid(ctx),
        op_type: OP_TYPE_BY_COMMAND[cmd.type],
        op_context_category: cmd.contextCategory ?? cmd.sourceCategory ?? null,
        fix_kind: cmd.fixKind ?? (cmd.type === 'ignoreIssue' ? 'ignore'
            : cmd.type === 'autoFixMissingWord' ? 'auto_fix'
            : 'manual'),
        started_at_utc: startedAt,
        applied_at_utc: startedAt,
        ready_at_utc: null,
        targets_before: [],
        targets_after: [],
        type: cmd.type,
        kind: _kindFor(cmd.type),
        snapshots: { before: [], after: [] },
        targetSegmentIndex: { chapter, index: targetIndex },
    };
    return op;
}

/**
 * Auto-suppress is only meaningful for per-segment categories. The registry
 * gate happens inside `applyAutoSuppress` itself; this helper records the
 * resolved-categories list for the validation delta.
 */
function _maybeAutoSuppress(seg: Segment, category: string | null | undefined, origin: 'card' | 'main_list'): string[] {
    if (!category) return [];
    const defn = IssueRegistry[category];
    if (!defn || !defn.autoSuppress || defn.scope !== 'per_segment') return [];
    const before = new Set(seg.ignored_categories ?? []);
    applyAutoSuppress(seg, category, origin);
    const after = seg.ignored_categories ?? [];
    return after.filter((c) => !before.has(c));
}

function _cloneSeg(seg: Segment): Segment {
    return {
        ...seg,
        ignored_categories: seg.ignored_categories ? [...seg.ignored_categories] : undefined,
    };
}

function _snapshot(seg: Segment): SegSnapshot {
    return snapshotSeg(seg);
}

// ---------------------------------------------------------------------------
// Per-command reducers
// ---------------------------------------------------------------------------

function _reduceTrim(state: ApplyCommandState, cmd: TrimCommand, ctx?: ApplyCommandContext): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[trim]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const next = _cloneSeg(target);
    if (cmd.delta.time_start != null) next.time_start = cmd.delta.time_start;
    if (cmd.delta.time_end != null) next.time_end = cmd.delta.time_end;
    next.confidence = 1.0;
    const resolved = _maybeAutoSuppress(next, cmd.sourceCategory ?? cmd.contextCategory, 'card');

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(next)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: { [next.segment_uid ?? cmd.segmentUid]: next },
        affectedChapter: chapter,
    };
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved, introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceSplit(state: ApplyCommandState, cmd: SplitCommand, ctx?: ApplyCommandContext): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[split]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);
    const splitMs = cmd.splitMs;
    if (splitMs <= target.time_start || splitMs >= target.time_end) {
        throw new Error(`applyCommand[split]: splitMs=${splitMs} out of range [${target.time_start}, ${target.time_end}]`);
    }

    const firstHalf: Segment = {
        ..._cloneSeg(target),
        time_end: splitMs,
    };
    const secondHalf: Segment = {
        ..._cloneSeg(target),
        segment_uid: cmd.secondHalfUid ?? _newUid(ctx),
        index: target.index + 1,
        time_start: splitMs,
    };
    if (cmd.firstRef !== undefined) firstHalf.matched_ref = cmd.firstRef;
    if (cmd.firstText !== undefined) firstHalf.matched_text = cmd.firstText;
    if (cmd.firstDisplayText !== undefined) firstHalf.display_text = cmd.firstDisplayText;
    if (cmd.secondRef !== undefined) secondHalf.matched_ref = cmd.secondRef;
    if (cmd.secondText !== undefined) secondHalf.matched_text = cmd.secondText;
    if (cmd.secondDisplayText !== undefined) secondHalf.display_text = cmd.secondDisplayText;

    const ctxCat = cmd.sourceCategory ?? cmd.contextCategory;
    const resolved = new Set<string>();
    for (const c of _maybeAutoSuppress(firstHalf, ctxCat, 'card')) resolved.add(c);
    for (const c of _maybeAutoSuppress(secondHalf, ctxCat, 'card')) resolved.add(c);

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(firstHalf), _snapshot(secondHalf)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const firstUid = firstHalf.segment_uid ?? cmd.segmentUid;
    const secondUid = secondHalf.segment_uid!;
    const nextState: CommandNextState = {
        byId: { [firstUid]: firstHalf, [secondUid]: secondHalf },
        affectedChapter: chapter,
        insertedSegmentUids: [secondUid],
    };
    const ids = state.idsByChapter[chapter];
    if (ids) {
        const ix = ids.indexOf(cmd.segmentUid);
        if (ix !== -1) {
            const nextIds = [...ids.slice(0, ix), firstUid, secondUid, ...ids.slice(ix + 1)];
            nextState.idsByChapter = { ...state.idsByChapter, [chapter]: nextIds };
        }
    }
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: [...resolved], introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceMerge(state: ApplyCommandState, cmd: MergeCommand, ctx?: ApplyCommandContext): CommandResult {
    const fromSeg = _findSeg(state, cmd.fromUid);
    const toSeg = _findSeg(state, cmd.toUid);
    if (!fromSeg || !toSeg) {
        throw new Error(`applyCommand[merge]: missing segments (from=${cmd.fromUid}, to=${cmd.toUid})`);
    }
    const chapter = _chapterFor(toSeg, state);
    const ids = state.idsByChapter[chapter] ?? [];
    const fromPos = ids.indexOf(cmd.fromUid);
    const toPos = ids.indexOf(cmd.toUid);
    const fromBeforeTo = fromPos !== -1 && toPos !== -1 ? fromPos < toPos : fromSeg.time_start <= toSeg.time_start;
    const first = fromBeforeTo ? fromSeg : toSeg;
    const second = fromBeforeTo ? toSeg : fromSeg;
    const direction: 'prev' | 'next' = cmd.direction
        ?? (fromBeforeTo ? 'next' : 'prev');

    const mergedIc = new Set<string>([
        ...(first.ignored_categories ?? []),
        ...(second.ignored_categories ?? []),
    ]);
    const merged: Segment = {
        ..._cloneSeg(first),
        segment_uid: first.segment_uid,
        index: first.index,
        time_start: first.time_start,
        time_end: second.time_end,
        matched_ref: cmd.mergedRef ?? _joinRefs(first.matched_ref, second.matched_ref),
        matched_text: cmd.mergedText ?? [first.matched_text, second.matched_text].filter(Boolean).join(' '),
        display_text: cmd.mergedDisplayText ?? [first.display_text, second.display_text].filter(Boolean).join(' '),
        confidence: 1.0,
    };
    const ctxCat = cmd.sourceCategory ?? cmd.contextCategory;
    if (ctxCat) {
        const defn = IssueRegistry[ctxCat];
        if (defn?.autoSuppress && defn.scope === 'per_segment') mergedIc.add(ctxCat);
    }
    if (mergedIc.size) merged.ignored_categories = [...mergedIc];
    else merged.ignored_categories = undefined;

    const op = _baseOperation(cmd, first, chapter, first.index, ctx);
    op.snapshots.before = [_snapshot(first), _snapshot(second)];
    op.snapshots.after = [_snapshot(merged)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.merge_direction = direction;
    op.affected_chapters = [chapter];

    const keptUid = merged.segment_uid ?? first.segment_uid ?? cmd.toUid;
    const consumedUid = (first === fromSeg ? toSeg : fromSeg).segment_uid ?? '';
    const nextState: CommandNextState = {
        byId: { [keptUid]: merged },
        affectedChapter: chapter,
        removedSegmentUids: consumedUid ? [consumedUid] : [],
    };
    if (ids.length) {
        const nextIds = ids.filter((u) => u !== consumedUid && u !== cmd.fromUid);
        const merger = nextIds.indexOf(cmd.toUid);
        if (merger !== -1) {
            nextIds.splice(merger, 1, keptUid);
        } else if (!nextIds.includes(keptUid)) {
            nextIds.unshift(keptUid);
        }
        nextState.idsByChapter = { ...state.idsByChapter, [chapter]: nextIds };
    }
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: ctxCat ? [ctxCat] : [], introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _joinRefs(firstRef?: string, lastRef?: string): string {
    const refs = [firstRef, lastRef].filter(Boolean) as string[];
    if (!refs.length) return '';
    const f = refs[0]!;
    const l = refs[refs.length - 1]!;
    const s = f.includes('-') ? f.split('-')[0] : f;
    const e = l.includes('-') ? l.split('-')[1] : l;
    return `${s}-${e}`;
}

function _reduceEditReference(
    state: ApplyCommandState,
    cmd: EditReferenceCommand,
    ctx?: ApplyCommandContext,
): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[editReference]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const next = _cloneSeg(target);
    next.matched_ref = cmd.matched_ref;
    if (cmd.matched_text !== undefined) next.matched_text = cmd.matched_text;
    if (cmd.display_text !== undefined) next.display_text = cmd.display_text;
    next.confidence = 1.0;
    const resolved = _maybeAutoSuppress(next, cmd.sourceCategory ?? cmd.contextCategory, 'card');

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(next)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: { [next.segment_uid ?? cmd.segmentUid]: next },
        affectedChapter: chapter,
    };
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved, introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceDelete(state: ApplyCommandState, cmd: DeleteCommand, ctx?: ApplyCommandContext): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[delete]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: {},
        affectedChapter: chapter,
        removedSegmentUids: [cmd.segmentUid],
    };
    const ids = state.idsByChapter[chapter];
    if (ids) {
        nextState.idsByChapter = {
            ...state.idsByChapter,
            [chapter]: ids.filter((u) => u !== cmd.segmentUid),
        };
    }
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: [], introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceIgnoreIssue(
    state: ApplyCommandState,
    cmd: IgnoreIssueCommand,
    ctx?: ApplyCommandContext,
): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[ignoreIssue]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const next = _cloneSeg(target);
    if (!next.ignored_categories) next.ignored_categories = [];
    if (!next.ignored_categories.includes(cmd.category)) {
        next.ignored_categories.push(cmd.category);
    }

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.op_context_category = cmd.category;
    op.fix_kind = cmd.fixKind ?? 'ignore';
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(next)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: { [next.segment_uid ?? cmd.segmentUid]: next },
        affectedChapter: chapter,
    };
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: [cmd.category], introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceAutoFixMissingWord(
    state: ApplyCommandState,
    cmd: AutoFixMissingWordCommand,
    ctx?: ApplyCommandContext,
): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[autoFixMissingWord]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const next = _cloneSeg(target);
    next.matched_ref = cmd.matched_ref;
    if (cmd.matched_text !== undefined) next.matched_text = cmd.matched_text;
    if (cmd.display_text !== undefined) next.display_text = cmd.display_text;
    next.confidence = 1.0;

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.op_context_category = cmd.contextCategory ?? cmd.sourceCategory ?? 'missing_words';
    op.fix_kind = cmd.fixKind ?? 'auto_fix';
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(next)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: { [next.segment_uid ?? cmd.segmentUid]: next },
        affectedChapter: chapter,
    };
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: [], introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

function _reduceEditFromCard(
    state: ApplyCommandState,
    cmd: EditFromCardCommand,
    ctx?: ApplyCommandContext,
): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[editFromCard]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    const next = _cloneSeg(target);
    const resolved = _maybeAutoSuppress(next, cmd.category, 'card');

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.op_context_category = cmd.category;
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = [_snapshot(next)];
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const nextState: CommandNextState = {
        byId: { [next.segment_uid ?? cmd.segmentUid]: next },
        affectedChapter: chapter,
    };
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved, introduced: [] },
        patch: _emptyPatch([chapter]),
    };
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export function applyCommand(
    state: ApplyCommandState,
    command: SegmentCommand,
    ctx: ApplyCommandContext = {},
): CommandResult {
    switch (command.type) {
        case 'trim':
            return _reduceTrim(state, command, ctx);
        case 'split':
            return _reduceSplit(state, command, ctx);
        case 'merge':
            return _reduceMerge(state, command, ctx);
        case 'editReference':
            return _reduceEditReference(state, command, ctx);
        case 'delete':
            return _reduceDelete(state, command, ctx);
        case 'ignoreIssue':
            return _reduceIgnoreIssue(state, command, ctx);
        case 'autoFixMissingWord':
            return _reduceAutoFixMissingWord(state, command, ctx);
        case 'editFromCard':
            return _reduceEditFromCard(state, command, ctx);
        default: {
            const _exhaustive: never = command;
            throw new Error(`applyCommand: unsupported command type ${(_exhaustive as { type: string }).type}`);
        }
    }
}

// ---------------------------------------------------------------------------
// Re-exports — let callers import command shapes from one module
// ---------------------------------------------------------------------------

export type {
    ApplyCommandContext,
    ApplyCommandState,
    CommandNextState,
    CommandOperation,
    CommandResult,
    SegmentCommand,
    SegmentPatch,
} from './command';

/** Wire-level shape of the operation record — handed to finalizeOp / save. */
export type { EditOp };
