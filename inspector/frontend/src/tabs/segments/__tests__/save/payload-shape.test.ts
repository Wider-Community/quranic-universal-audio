// Save payload shape tests (MUST-1 contract).

import { describe, expect, it } from 'vitest';

import { buildPayloadFromCommandResult } from '../../utils/save/payload';

describe('save payload shape', () => {
  it('build payload from CommandResult produces the patch-mode shape', () => {
    // Drive the actual builder so the assertion exercises production code
    // — asserting on a hand-rolled literal would prove nothing about the
    // codepath that runs in the app.
    const result = {
      operation: { op_id: 'x', type: 'trim', snapshots: { before: {}, after: {} }, affected_chapters: [1] },
      affectedChapters: [1],
      patch: undefined,
    };
    const payload = buildPayloadFromCommandResult(result as any);
    expect(payload).toBeTruthy();
    // Patch-mode wire shape: segments + operations + affected_chapters; never
    // full_replace (that envelope is constructed by execute.ts, not by this
    // builder).
    expect((payload as any).full_replace).toBeUndefined();
    expect(Array.isArray(payload.operations)).toBe(true);
    expect(payload.operations[0]).toMatchObject({ op_id: 'x', type: 'trim' });
    expect(payload.affected_chapters).toEqual([1]);
  });
});
