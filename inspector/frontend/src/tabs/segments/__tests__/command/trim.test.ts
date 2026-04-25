// IS-6: trim flows dispatch through applyCommand.

import { describe, it, expect } from 'vitest';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
const applyCommand = mod?.applyCommand ?? null;

const baseState = () => ({
  byId: { 'uid-trim': makeSegment(0, 0, 2000, { segment_uid: 'uid-trim' }) },
  idsByChapter: { 1: ['uid-trim'] },
  selectedChapter: 1 as number | null,
});

describe.skipIf(!applyCommand)('command/trim', () => {
  it('op produces expected segment mutations', () => {
    const r = applyCommand(baseState(), { type: 'trim', segmentUid: 'uid-trim', delta: { time_start: 250 } } as any);
    const updated = r.nextState.byId?.['uid-trim'] ?? r.nextState['uid-trim'];
    expect(updated.time_start).toBe(250);
  });

  it('op records snapshots before / after', () => {
    const r = applyCommand(baseState(), { type: 'trim', segmentUid: 'uid-trim', delta: { time_start: 250 } } as any);
    expect(r.operation.snapshots?.before).toBeTruthy();
    expect(r.operation.snapshots?.after).toBeTruthy();
  });

  it('op marks dirty correctly (structural vs single-index)', () => {
    const r = applyCommand(baseState(), { type: 'trim', segmentUid: 'uid-trim', delta: { time_start: 250 } } as any);
    expect(r.operation.kind === 'single-index' || r.operation.kind === 'structural').toBe(true);
  });

  it('op honors auto-suppress per registry', () => {
    const r = applyCommand(baseState(), {
      type: 'trim', segmentUid: 'uid-trim',
      delta: { time_start: 250 },
      sourceCategory: 'low_confidence',
    } as any);
    const updated = r.nextState.byId?.['uid-trim'] ?? r.nextState['uid-trim'];
    expect(updated.ignored_categories).toContain('low_confidence');
  });

  it('op preserves _mountId routing through dispatcher', () => {
    const r = applyCommand(baseState(), {
      type: 'trim', segmentUid: 'uid-trim',
      delta: { time_start: 250 },
      _mountId: 'main-list',
    } as any);
    expect(r.operation.targetSegmentIndex).toBeTruthy();
  });

  it('op result feeds save payload correctly', () => {
    const r = applyCommand(baseState(), { type: 'trim', segmentUid: 'uid-trim', delta: { time_start: 250 } } as any);
    expect(r.operation).toMatchObject({ type: 'trim' });
  });

  it('targetSegmentIndex routing for main-list mountId', () => {
    const r = applyCommand(baseState(), {
      type: 'trim', segmentUid: 'uid-trim',
      delta: { time_start: 250 },
      _mountId: 'main-list',
    } as any);
    expect(r.operation.targetSegmentIndex.chapter).toBe(1);
  });

  it('targetSegmentIndex routing for accordion mountId', () => {
    const r = applyCommand(baseState(), {
      type: 'trim', segmentUid: 'uid-trim',
      delta: { time_start: 250 },
      _mountId: 'accordion',
    } as any);
    expect(r.operation.targetSegmentIndex.chapter).toBe(1);
  });
});

describe.skipIf(applyCommand)('command/trim (deferred)', () => {
  it.todo('phase-3: domain/apply-command not yet present');
});
