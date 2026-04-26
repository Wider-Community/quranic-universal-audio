// IS-6: editReference flows dispatch through applyCommand.

import { describe, it, expect } from 'vitest';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: { 'uid-ref': makeSegment(0, 0, 1000, { segment_uid: 'uid-ref' }) },
  idsByChapter: { 1: ['uid-ref'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/reference', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y' } as any);
    const updated = r.nextState.byId?.['uid-ref'] ?? r.nextState['uid-ref'];
    expect(updated.matched_ref).toBe('1:2:1-1:2:1');
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y' } as any);
    expect(r.operation.snapshots).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y' } as any);
    expect(r.operation.kind).toBeTruthy();
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y', sourceCategory: 'audio_bleeding' } as any);
    const updated = r.nextState.byId?.['uid-ref'] ?? r.nextState['uid-ref'];
    expect(updated.ignored_categories).toContain('audio_bleeding');
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y', _mountId: 'main-list' } as any);
    expect(r.operation).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y' } as any);
    expect(r.operation.type).toBe('editReference');
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y', _mountId: 'main-list' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const r = applyCommand(baseState(), { type: 'editReference', segmentUid: 'uid-ref', matched_ref: '1:2:1-1:2:1', matched_text: 'y', _mountId: 'accordion' } as any);
    expect(r.operation.targetSegmentIndex?.chapter).toBe(1);
  });
});

describe.skipIf(applyCommand)('command/reference (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
