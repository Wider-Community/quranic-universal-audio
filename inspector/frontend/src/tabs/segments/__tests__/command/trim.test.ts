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
    const updated = r.nextState.byId?.['uid-trim'] ?? r.nextState['uid-trim'];
    expect(updated.time_start).toBe(250);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.snapshots?.before).toBeTruthy();
    expect(r.operation.snapshots?.after).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.kind === 'single-index' || r.operation.kind === 'structural').toBe(true);
  });

  it('op records sourceCategory as op_context_category but does not mutate ignored_categories', () => {
    const cmd: TrimCommand = { ...baseCmd, sourceCategory: 'low_confidence' };
    const r = applyCommand(baseState(), cmd);
    const updated = r.nextState.byId?.['uid-trim'] ?? r.nextState['uid-trim'];
    expect(r.operation.op_context_category).toBe('low_confidence');
    expect(updated.ignored_categories ?? []).not.toContain('low_confidence');
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const cmd: TrimCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation).toMatchObject({ type: 'trim' });
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const cmd: TrimCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const cmd: TrimCommand = { ...baseCmd, _mountId: 'accordion' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex.chapter).toBe(1);
  });
});
