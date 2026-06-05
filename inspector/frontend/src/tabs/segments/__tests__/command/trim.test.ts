// IS-6: trim flows dispatch through applyCommand.

import { describe, expect, it } from 'vitest';

import { applyCommand } from '../../domain/apply-command';
import type { TrimCommand } from '../../domain/command';
import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';

const baseState = () => makeApplyCommandState([
  makeSegment(0, 0, 2000, { segment_uid: 'uid-trim' }),
]);

const baseCmd: TrimCommand = {
  type: 'trim',
  segmentUid: 'uid-trim',
  delta: { time_start: 250 },
};

describe('command/trim', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), baseCmd);
    const updated = r.nextState.byId['uid-trim']!;
    expect(updated.time_start).toBe(250);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.snapshots?.before).toBeTruthy();
    expect(r.operation.snapshots?.after).toBeTruthy();
  });

  it('op marks dirty as structural (trim belongs to STRUCTURAL_COMMANDS)', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.kind).toBe('structural');
  });

  it('op records sourceCategory as op_context_category but does not mutate ignored_categories', () => {
    const cmd: TrimCommand = { ...baseCmd, sourceCategory: 'low_confidence' };
    const r = applyCommand(baseState(), cmd);
    const updated = r.nextState.byId['uid-trim']!;
    expect(r.operation.op_context_category).toBe('low_confidence');
    expect(updated.ignored_categories ?? []).not.toContain('low_confidence');
  });

  it('records targetSegmentIndex with the segment chapter (mountId is dispatcher-only and ignored here)', () => {
    // _mountId is consumed by the dispatcher to pick the rendered row, not by
    // applyCommand. Pin the targetSegmentIndex shape that the reducer DOES
    // populate (chapter + index); the prior "main-list vs accordion" pair
    // of tests asserted the same chapter=1 against both variants and could
    // never fail differently.
    const cmd: TrimCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex.chapter).toBe(1);
    expect(r.operation.type).toBe('trim');
  });
});
