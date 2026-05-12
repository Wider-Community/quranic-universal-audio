/**
 * applyCommand — pure reducer over a segment-slice + a SegmentCommand.
 *
 * Builds the EditOp record (snapshots + targetSegmentIndex), computes
 * mutated segments per command type, and returns a `CommandResult` the
 * dispatcher applies to the live stores.
 *
 * The reducer never mutates `seg.ignored_categories`. Editing from a
 * validation accordion card records `cmd.sourceCategory` /
 * `cmd.contextCategory` on the op (so history pills know which card the
 * user was working from) but does not write to the segment's persisted
 * ignore list — that's reserved for the explicit Ignore action. Card
 * dismissal for soft-rule categories is handled out-of-band via the
 * session-resolved store.
 *
 * The reducer is pure: it does not touch the dirty/edit/playback stores,
 * does not perform I/O, does not mutate inputs. Side effects are the
 * dispatcher's job.
 */

import type { EditOp, Segment } from '../../../lib/types/domain';
import type { SegSnapshot } from '../stores/dirty';
import { snapshotSeg } from '../stores/dirty';
import type { SegmentState } from '../stores/segments';
import type {
    ApplyCommandContext,
    ApplyCommandState,
    AutoFixMissingWordCommand,
    CommandNextState,
    CommandOperation,
    CommandResult,
    DeleteCommand,
    EditReferenceCommand,
    IgnoreIssueCommand,
    MergeCommand,
    Operation,
    SegmentCommand,
    SegmentPatch,
    SplitCommand,
    TrimCommand,
} from './command';
import { IssueRegistry } from './registry';

const HISTORY_NEUTRAL_CONTEXT_CATEGORIES = new Set(['basmala_amin']);

function _historyContextCategory(category: string | null | undefined): string | null {
    if (!category || HISTORY_NEUTRAL_CONTEXT_CATEGORIES.has(category)) return null;
    return category;
}

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

function _buildPatch(
    before: SegSnapshot[],
    after: SegSnapshot[],
    removedIds: string[],
    insertedIds: string[],
    affectedChapterIds: number[],
): SegmentPatch {
    return { before, after, removedIds, insertedIds, affectedChapterIds };
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
        op_type: OP_TYPE_BY_COMMAND[cmd.type as Operation],
        op_context_category: _historyContextCategory(cmd.contextCategory ?? cmd.sourceCategory ?? null),
        fix_kind: cmd.fixKind ?? (cmd.type === 'ignoreIssue' ? 'ignore'
            : cmd.type === 'autoFixMissingWord' ? 'auto_fix'
            : 'manual'),
        started_at_utc: startedAt,
        applied_at_utc: startedAt,
        ready_at_utc: null,
        targets_before: [],
        targets_after: [],
        type: cmd.type as Operation,
        kind: _kindFor(cmd.type as Operation),
        snapshots: { before: [], after: [] },
        targetSegmentIndex: { chapter, index: targetIndex },
        command: { ...cmd, type: cmd.type },
    };
    return op;
}

/**
 * Compute the validation-delta `resolved` list from a command's source
 * category. Ops dispatched from an accordion card report that card's
 * category here so callers can update card-counts. This does NOT mutate
 * `seg.ignored_categories` — that's reserved for explicit Ignore actions.
 *
 * Per-segment categories only; per-verse / per-chapter categories return
 * empty (the next validation pass is the source of truth for those).
 */
function _resolvedFromContext(category: string | null | undefined): string[] {
    if (!category) return [];
    if (HISTORY_NEUTRAL_CONTEXT_CATEGORIES.has(category)) return [];
    const defn = IssueRegistry[category];
    if (!defn || defn.scope !== 'per_segment') return [];
    return [category];
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
    const resolved = _resolvedFromContext(cmd.sourceCategory ?? cmd.contextCategory);

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
        patch: _buildPatch(
            [_snapshot(target)],
            [_snapshot(next)],
            [],
            [],
            [chapter],
        ),
    };
}

function _reduceSplit(state: ApplyCommandState, cmd: SplitCommand, ctx?: ApplyCommandContext): CommandResult {
    const target = _findSeg(state, cmd.segmentUid);
    if (!target) throw new Error(`applyCommand[split]: segment '${cmd.segmentUid}' not found`);
    const chapter = _chapterFor(target, state);

    // Normalize cursors → ascending list of cuts strictly inside the seg.
    const cursors = (Array.isArray(cmd.splitMs) ? cmd.splitMs.slice() : [cmd.splitMs])
        .sort((a, b) => a - b);
    for (let i = 0; i < cursors.length; i++) {
        const cur = cursors[i]!;
        if (cur <= target.time_start || cur >= target.time_end) {
            throw new Error(
                `applyCommand[split]: splitMs=${cur} out of range `
                + `[${target.time_start}, ${target.time_end}]`,
            );
        }
        if (i > 0 && cur <= cursors[i - 1]!) {
            throw new Error(
                `applyCommand[split]: cursors must be strictly ascending (got ${cursors})`,
            );
        }
    }

    // Per-piece ref + text resolution. The array form `cmd.refs`/`cmd.texts`
    // wins (length must equal pieces.length); otherwise the legacy
    // `first*`/`second*` fields apply for the N=2 case.
    const nPieces = cursors.length + 1;
    const refs: (string | undefined)[] = new Array(nPieces).fill(undefined);
    const texts: (string | undefined)[] = new Array(nPieces).fill(undefined);
    if (cmd.refs && cmd.refs.length === nPieces) {
        for (let i = 0; i < nPieces; i++) refs[i] = cmd.refs[i];
    } else if (nPieces === 2) {
        refs[0] = cmd.firstRef;
        refs[1] = cmd.secondRef;
    }
    if (cmd.texts && cmd.texts.length === nPieces) {
        for (let i = 0; i < nPieces; i++) texts[i] = cmd.texts[i];
    } else if (nPieces === 2) {
        texts[0] = cmd.firstText;
        texts[1] = cmd.secondText;
    }

    // Build N+1 pieces. First piece reuses parent UID; the rest take from
    // `cmd.newUids` (or fall back to fresh UIDs). `cmd.secondHalfUid` is a
    // single-cursor convenience kept for older callers.
    const pieces: Segment[] = [];
    for (let i = 0; i < nPieces; i++) {
        const start = i === 0 ? target.time_start : cursors[i - 1]!;
        const end = i === nPieces - 1 ? target.time_end : cursors[i]!;
        const piece: Segment = {
            ..._cloneSeg(target),
            time_start: start,
            time_end: end,
        };
        if (i === 0) {
            // Keep parent uid + index for piece 0.
        } else {
            piece.segment_uid = cmd.newUids?.[i - 1]
                ?? (i === 1 ? cmd.secondHalfUid : undefined)
                ?? _newUid(ctx);
            piece.index = target.index + i;
        }
        if (refs[i] !== undefined) piece.matched_ref = refs[i]!;
        if (texts[i] !== undefined) piece.matched_text = texts[i]!;
        pieces.push(piece);
    }

    const ctxCat = cmd.sourceCategory ?? cmd.contextCategory;
    const resolved = new Set<string>(_resolvedFromContext(ctxCat));

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    op.snapshots.before = [_snapshot(target)];
    op.snapshots.after = pieces.map(_snapshot);
    op.targets_before = op.snapshots.before;
    op.targets_after = op.snapshots.after;
    op.affected_chapters = [chapter];

    const insertedUids = pieces.slice(1).map((p) => p.segment_uid!);
    const byId: Record<string, Segment> = {};
    for (const p of pieces) {
        const u = p.segment_uid ?? cmd.segmentUid;
        byId[u] = p;
    }
    const firstUid = pieces[0]!.segment_uid ?? cmd.segmentUid;
    const nextState: CommandNextState = {
        byId,
        affectedChapter: chapter,
        insertedSegmentUids: insertedUids,
    };
    const ids = state.idsByChapter[chapter];
    if (ids) {
        const ix = ids.indexOf(cmd.segmentUid);
        if (ix !== -1) {
            const nextIds = [
                ...ids.slice(0, ix),
                firstUid,
                ...insertedUids,
                ...ids.slice(ix + 1),
            ];
            nextState.idsByChapter = { ...state.idsByChapter, [chapter]: nextIds };
        }
    }
    return {
        nextState,
        operation: op,
        affectedChapters: [chapter],
        validationDelta: { resolved: [...resolved], introduced: [] },
        patch: _buildPatch(
            [_snapshot(target)],
            pieces.map(_snapshot),
            [],
            insertedUids,
            [chapter],
        ),
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
        confidence: 1.0,
    };
    merged.ignored_categories = mergedIc.size ? [...mergedIc] : undefined;
    const ctxCat = cmd.sourceCategory ?? cmd.contextCategory;
    const resolved = _resolvedFromContext(ctxCat);

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
        validationDelta: { resolved, introduced: [] },
        patch: _buildPatch(
            [_snapshot(first), _snapshot(second)],
            [_snapshot(merged)],
            consumedUid ? [consumedUid] : [],
            [],
            [chapter],
        ),
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
    next.confidence = 1.0;
    const resolved = _resolvedFromContext(cmd.sourceCategory ?? cmd.contextCategory);

    const op = _baseOperation(cmd, target, chapter, target.index, ctx);
    if (cmd.opType === 'confirm_reference') {
        op.op_type = 'confirm_reference';
        op.fix_kind = cmd.fixKind ?? 'audit';
    }
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
        patch: _buildPatch(
            [_snapshot(target)],
            [_snapshot(next)],
            [],
            [],
            [chapter],
        ),
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
        patch: _buildPatch(
            [_snapshot(target)],
            [],
            [cmd.segmentUid],
            [],
            [chapter],
        ),
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
    next.confidence = 1.0;

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
        patch: _buildPatch(
            [_snapshot(target)],
            [_snapshot(next)],
            [],
            [],
            [chapter],
        ),
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
        patch: _buildPatch(
            [_snapshot(target)],
            [_snapshot(next)],
            [],
            [],
            [chapter],
        ),
    };
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

export function applyCommand(
    state: ApplyCommandState | SegmentState,
    command: SegmentCommand,
    ctx: ApplyCommandContext = {},
): CommandResult {
    switch (command.type) {
        case 'trim':
            return _reduceTrim(state as ApplyCommandState, command, ctx);
        case 'split':
            return _reduceSplit(state as ApplyCommandState, command, ctx);
        case 'merge':
            return _reduceMerge(state as ApplyCommandState, command, ctx);
        case 'editReference':
            return _reduceEditReference(state as ApplyCommandState, command, ctx);
        case 'delete':
            return _reduceDelete(state as ApplyCommandState, command, ctx);
        case 'ignoreIssue':
            return _reduceIgnoreIssue(state as ApplyCommandState, command, ctx);
        case 'autoFixMissingWord':
            return _reduceAutoFixMissingWord(state as ApplyCommandState, command, ctx);
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
