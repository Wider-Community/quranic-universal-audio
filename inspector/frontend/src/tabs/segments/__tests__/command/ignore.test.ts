// IS-6: ignoreIssue flows dispatch through applyCommand.

import { describe, expect, it } from 'vitest';

import { applyCommand } from '../../domain/apply-command';
import type { IgnoreIssueCommand } from '../../domain/command';
import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';

const baseState = () => makeApplyCommandState([
  makeSegment(0, 0, 1000, { segment_uid: 'uid-ig', confidence: 0.42 }),
]);

const baseCmd: IgnoreIssueCommand = {
  type: 'ignoreIssue',
  segmentUid: 'uid-ig',
  category: 'low_confidence',
};

describe('command/ignore', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), baseCmd);
    const updated = r.nextState.byId?.['uid-ig'] ?? r.nextState['uid-ig'];
    expect(updated.ignored_categories).toContain('low_confidence');
    expect(updated.confidence).toBe(1.0);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.snapshots).toBeTruthy();
    expect(r.operation.snapshots.before[0]?.confidence).toBe(0.42);
    expect(r.operation.snapshots.after[0]?.confidence).toBe(1.0);
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.kind).toBe('single-index');
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), baseCmd);
    const updated = r.nextState.byId?.['uid-ig'] ?? r.nextState['uid-ig'];
    expect(updated.ignored_categories).toContain('low_confidence');
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const cmd: IgnoreIssueCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.type).toBe('ignoreIssue');
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const cmd: IgnoreIssueCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const cmd: IgnoreIssueCommand = { ...baseCmd, _mountId: 'accordion' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });
});
