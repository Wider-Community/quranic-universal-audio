// Integration tests for onPendingOpsDiscard — atomic per-card discard.
// Builds pending ops with patches, exercises the discard handler, and
// asserts that only the discarded ops' effects are reverted while other
// pending ops survive both in `_opLog` and in `segAllData`.

import { get as storeGet } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { EditOp, EditOpPatch, Segment } from '../../../../lib/types/domain';
import { segAllData } from '../../stores/chapter';
import {
    clearDirtyMap,
    clearOpLog,
    finalizeOp,
    getChapterOps,
    isDirty,
    markDirty,
} from '../../stores/dirty';
import { onPendingOpsDiscard } from '../../utils/save/undo';

function makeSeg(overrides: Partial<Segment> & { segment_uid: string; chapter: number; time_start: number }): Segment {
    return {
        index: 0,
        entry_idx: 0,
        time_end: overrides.time_start + 1000,
        matched_ref: '',
        matched_text: '',
        confidence: 1,
        audio_url: '',
        ...overrides,
    };
}

function snap(s: Segment): Record<string, unknown> {
    return {
        segment_uid: s.segment_uid,
        index_at_save: s.index,
        audio_url: s.audio_url,
        time_start: s.time_start,
        time_end: s.time_end,
        matched_ref: s.matched_ref,
        matched_text: s.matched_text,
        confidence: s.confidence,
        chapter: s.chapter,
    };
}

function makeTrimOp(opId: string, before: Segment, after: Segment): EditOp {
    const patch: EditOpPatch = {
        before: [snap(before)],
        after: [snap(after)],
        removedIds: [],
        insertedIds: [],
        affectedChapterIds: [before.chapter ?? 1],
    };
    return {
        op_id: opId,
        op_type: 'trim_segment',
        op_context_category: null,
        fix_kind: 'manual',
        started_at_utc: new Date().toISOString(),
        applied_at_utc: new Date().toISOString(),
        ready_at_utc: null,
        targets_before: [snap(before)],
        targets_after: [snap(after)],
        patch,
    };
}

const fakeBtn: HTMLButtonElement = { disabled: false, textContent: '' } as HTMLButtonElement;

let originalConfirm: typeof window.confirm | undefined;

beforeEach(() => {
    originalConfirm = window.confirm;
    window.confirm = (() => true) as typeof window.confirm;
    clearDirtyMap();
    clearOpLog();
});

afterEach(() => {
    if (originalConfirm) window.confirm = originalConfirm;
    vi.restoreAllMocks();
    segAllData.set(null);
    clearDirtyMap();
    clearOpLog();
});

describe('onPendingOpsDiscard', () => {
    it('discards one card while preserving another in the same chapter', () => {
        // Two unrelated trims in chapter 1.
        const aBefore = makeSeg({ segment_uid: 'a', chapter: 1, time_start: 0, time_end: 1000, confidence: 0.5 });
        const aAfter: Segment = { ...aBefore, time_start: 100, confidence: 1.0 };
        const bBefore = makeSeg({ segment_uid: 'b', chapter: 1, time_start: 2000, time_end: 3000, confidence: 0.5 });
        const bAfter: Segment = { ...bBefore, time_end: 2900, confidence: 1.0 };

        // Live state reflects BOTH applied trims.
        segAllData.set({ segments: [aAfter, bAfter] } as never);

        const opA = makeTrimOp('op-A', aBefore, aAfter);
        const opB = makeTrimOp('op-B', bBefore, bAfter);
        finalizeOp(1, opA);
        finalizeOp(1, opB);
        markDirty(1, undefined, true);

        // Discard only opA.
        onPendingOpsDiscard(1, ['op-A'], fakeBtn);

        // Op log: only opB remains.
        const ops = getChapterOps(1);
        expect(ops.map((o) => o.op_id)).toEqual(['op-B']);

        // Segments: a reverted to before, b stays trimmed.
        const segs = (storeGet(segAllData) as { segments: Segment[] }).segments;
        const a = segs.find((s) => s.segment_uid === 'a')!;
        const b = segs.find((s) => s.segment_uid === 'b')!;
        expect(a.time_start).toBe(0);
        expect(a.confidence).toBe(0.5);
        expect(b.time_end).toBe(2900);
        expect(b.confidence).toBe(1.0);

        // Chapter still dirty.
        expect(isDirty()).toBe(true);
    });

    it('clears dirty entry when the last card in a chapter is discarded', () => {
        const before = makeSeg({ segment_uid: 'a', chapter: 1, time_start: 0, confidence: 0.5 });
        const after: Segment = { ...before, time_start: 100, confidence: 1.0 };
        segAllData.set({ segments: [after] } as never);

        const op = makeTrimOp('op-only', before, after);
        finalizeOp(1, op);
        markDirty(1, undefined, true);

        onPendingOpsDiscard(1, ['op-only'], fakeBtn);

        expect(getChapterOps(1)).toEqual([]);
        expect(isDirty()).toBe(false);
        const segs = (storeGet(segAllData) as { segments: Segment[] }).segments;
        expect(segs[0]!.time_start).toBe(0);
        expect(segs[0]!.confidence).toBe(0.5);
    });

    it('does not affect a different dirty chapter (regression for cross-chapter race)', () => {
        const aBefore = makeSeg({ segment_uid: 'a', chapter: 1, time_start: 0, confidence: 0.5 });
        const aAfter: Segment = { ...aBefore, time_start: 100, confidence: 1.0 };
        const zBefore = makeSeg({ segment_uid: 'z', chapter: 2, time_start: 5000, confidence: 0.5 });
        const zAfter: Segment = { ...zBefore, time_start: 5100, confidence: 1.0 };
        segAllData.set({ segments: [aAfter, zAfter] } as never);

        const opCh1 = makeTrimOp('op-1', aBefore, aAfter);
        const opCh2 = makeTrimOp('op-2', zBefore, zAfter);
        finalizeOp(1, opCh1);
        finalizeOp(2, opCh2);
        markDirty(1, undefined, true);
        markDirty(2, undefined, true);

        onPendingOpsDiscard(1, ['op-1'], fakeBtn);

        // Chapter 2's dirty entry + ops untouched.
        expect(getChapterOps(2).map((o) => o.op_id)).toEqual(['op-2']);
        expect(isDirty()).toBe(true);
        const z = (storeGet(segAllData) as { segments: Segment[] }).segments.find((s) => s.segment_uid === 'z')!;
        expect(z.time_start).toBe(5100);
        expect(z.confidence).toBe(1.0);
    });

    it('reverts a chained card (split → edit-ref) atomically in reverse order', () => {
        // Forward state: original split into A (uid-a) + B (uid-b); then
        // edit-ref applied to B. Discarding the card reverts both.
        const original = makeSeg({ segment_uid: 'uid-a', chapter: 1, time_start: 0, time_end: 2000, matched_ref: '1:1:1' });
        const firstHalf = makeSeg({ segment_uid: 'uid-a', chapter: 1, time_start: 0, time_end: 1000, matched_ref: '1:1:1' });
        const secondHalfPreEdit = makeSeg({ segment_uid: 'uid-b', chapter: 1, time_start: 1000, time_end: 2000, matched_ref: '1:1:1' });
        const secondHalfPostEdit: Segment = { ...secondHalfPreEdit, matched_ref: '1:1:2' };

        segAllData.set({ segments: [firstHalf, secondHalfPostEdit] } as never);

        // Op1: split (creates uid-b)
        const splitOp: EditOp = {
            op_id: 'op-split',
            op_type: 'split_segment',
            op_context_category: null,
            fix_kind: 'manual',
            started_at_utc: new Date().toISOString(),
            applied_at_utc: new Date().toISOString(),
            ready_at_utc: null,
            targets_before: [snap(original)],
            targets_after: [snap(firstHalf), snap(secondHalfPreEdit)],
            patch: {
                before: [snap(original)],
                after: [snap(firstHalf), snap(secondHalfPreEdit)],
                removedIds: [],
                insertedIds: ['uid-b'],
                affectedChapterIds: [1],
            },
        };
        // Op2: edit-ref on uid-b (in-place)
        const editOp: EditOp = {
            op_id: 'op-edit',
            op_type: 'edit_reference',
            op_context_category: null,
            fix_kind: 'manual',
            started_at_utc: new Date().toISOString(),
            applied_at_utc: new Date().toISOString(),
            ready_at_utc: null,
            targets_before: [snap(secondHalfPreEdit)],
            targets_after: [snap(secondHalfPostEdit)],
            patch: {
                before: [snap(secondHalfPreEdit)],
                after: [snap(secondHalfPostEdit)],
                removedIds: [],
                insertedIds: [],
                affectedChapterIds: [1],
            },
        };
        finalizeOp(1, splitOp);
        finalizeOp(1, editOp);
        markDirty(1, undefined, true);

        // Discard the whole chain in one shot.
        onPendingOpsDiscard(1, ['op-split', 'op-edit'], fakeBtn);

        const segs = (storeGet(segAllData) as { segments: Segment[] }).segments;
        // Should be back to one segment with the original ref.
        expect(segs).toHaveLength(1);
        expect(segs[0]!.segment_uid).toBe('uid-a');
        expect(segs[0]!.time_start).toBe(0);
        expect(segs[0]!.time_end).toBe(2000);
        expect(segs[0]!.matched_ref).toBe('1:1:1');
        expect(isDirty()).toBe(false);
    });
});
