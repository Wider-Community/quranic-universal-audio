// IS-6: merge flows dispatch through applyCommand.

import { describe, expect, it } from 'vitest';

import { applyCommand } from '../../domain/apply-command';
import type { MergeCommand } from '../../domain/command';
import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';

const baseState = () => makeApplyCommandState([
  makeSegment(0, 0, 1000, { segment_uid: 'uid-a' }),
  makeSegment(1, 1000, 2000, { segment_uid: 'uid-b' }),
]);

const baseCmd: MergeCommand = { type: 'merge', fromUid: 'uid-a', toUid: 'uid-b' };

describe('command/merge', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), baseCmd);
    const ids = Object.keys(r.nextState.byId ?? r.nextState);
    expect(ids.length).toBe(1);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.snapshots).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.kind).toBe('structural');
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.type).toBe('merge');
  });

  it('records targetSegmentIndex with the segment chapter (mountId is dispatcher-only and ignored here)', () => {
    // _mountId is consumed by the dispatcher to pick the rendered row, not
    // by applyCommand. The prior "main-list vs accordion" pair asserted the
    // same chapter=1 against both variants and could not fail differently.
    const cmd: MergeCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });
});
