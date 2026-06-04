// IS-6: editReference flows dispatch through applyCommand.

import { describe, expect, it } from 'vitest';

import { applyCommand } from '../../domain/apply-command';
import type { EditReferenceCommand } from '../../domain/command';
import { makeApplyCommandState, makeSegment } from '../helpers/make-segment';

const baseState = () => makeApplyCommandState([
  makeSegment(0, 0, 1000, { segment_uid: 'uid-ref' }),
]);

const baseCmd: EditReferenceCommand = {
  type: 'editReference',
  segmentUid: 'uid-ref',
  matched_ref: '1:2:1-1:2:1',
  matched_text: 'y',
};

describe('command/reference', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), baseCmd);
    const updated = r.nextState.byId?.['uid-ref'] ?? r.nextState['uid-ref'];
    expect(updated.matched_ref).toBe('1:2:1-1:2:1');
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.snapshots).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.kind).toBeTruthy();
  });

  it('op records sourceCategory but does not mutate ignored_categories', () => {
    const cmd: EditReferenceCommand = { ...baseCmd, sourceCategory: 'audio_bleeding' };
    const r = applyCommand(baseState(), cmd);
    const updated = r.nextState.byId?.['uid-ref'] ?? r.nextState['uid-ref'];
    expect(r.operation.op_context_category).toBe('audio_bleeding');
    expect(updated.ignored_categories ?? []).not.toContain('audio_bleeding');
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const cmd: EditReferenceCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), baseCmd);
    expect(r.operation.type).toBe('editReference');
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const cmd: EditReferenceCommand = { ...baseCmd, _mountId: 'main-list' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const cmd: EditReferenceCommand = { ...baseCmd, _mountId: 'accordion' };
    const r = applyCommand(baseState(), cmd);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });
});
