// applyCommand reducer tests (IS-5).

import { describe, expect, it } from 'vitest';

import { applyCommand } from '../../domain/apply-command';
import type { SegmentCommand } from '../../domain/command';
import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';

describe('applyCommand', () => {
  const baseState = makeApplyCommandState([
    makeSegment(0, 0, 1000, { segment_uid: 'uid-1' }),
  ]);

  const trim: SegmentCommand = { type: 'trim', segmentUid: 'uid-1', delta: { time_start: 100 } };

  it('returns CommandResult with nextState', () => {
    const r = applyCommand(baseState, trim);
    expect(r.nextState).toBeTruthy();
  });

  it('returns operation matching createOp shape', () => {
    const r = applyCommand(baseState, trim);
    expect(r.operation).toBeTruthy();
    expect(r.operation.type).toBe('trim');
  });

  it('returns affectedChapters list', () => {
    const r = applyCommand(baseState, trim);
    expect(Array.isArray(r.affectedChapters)).toBe(true);
    expect(r.affectedChapters).toContain(1);
  });

  it('returns validationDelta when applicable', () => {
    const editRef: SegmentCommand = { type: 'editReference', segmentUid: 'uid-1', matched_ref: '1:1:1-1:1:1' };
    const r = applyCommand(baseState, editRef);
    expect('validationDelta' in r).toBe(true);
  });

  it('records op_context_category and resolved delta for Basmala + Amin edits', () => {
    // basmala_amin behaves like the other resolve-by-edit categories:
    // edits from inside the accordion stamp op_context_category so the BE
    // resolved-by-edit index can suppress the flag on next revalidation.
    const cmd: SegmentCommand = {
      type: 'trim',
      segmentUid: 'uid-1',
      delta: { time_start: 100 },
      sourceCategory: 'basmala_amin',
    };
    const r = applyCommand(baseState, cmd);
    expect(r.operation.op_context_category).toBe('basmala_amin');
    expect(r.validationDelta?.resolved ?? []).toContain('basmala_amin');
  });

  it('strips history context for muqattaat edits', () => {
    const cmd: SegmentCommand = {
      type: 'trim',
      segmentUid: 'uid-1',
      delta: { time_start: 100 },
      sourceCategory: 'muqattaat',
    };
    const r = applyCommand(baseState, cmd);
    expect(r.operation.op_context_category).toBeNull();
    expect(r.validationDelta?.resolved ?? []).toEqual([]);
  });

  it('returns a populated patch field with before/after arrays', () => {
    const r = applyCommand(baseState, trim);
    expect(r.patch).toBeTruthy();
    expect(Array.isArray(r.patch.before)).toBe(true);
    expect(Array.isArray(r.patch.after)).toBe(true);
  });
});
