// Save tests: payload includes patch field when applyCommand produces one.

import { describe, expect, it } from 'vitest';

import { buildPayloadFromCommandResult } from '../../utils/save/payload';

describe('save patch field', () => {
  it('payload includes patch field when applyCommand produces one', () => {
    const result = {
      operation: { op_id: 'x', type: 'trim' },
      affectedChapters: [1],
      patch: { before: [{ segment_uid: 'a' }], after: [{ segment_uid: 'a' }], removedIds: [], insertedIds: [], affectedChapterIds: [1] },
    };
    const payload = buildPayloadFromCommandResult(result as any);
    expect(payload.operations[0]!.patch).toBeTruthy();
    expect((payload.operations[0]!.patch as any).before[0].segment_uid).toBe('a');
  });

  it('builder omits patch field when applyCommand produced none', () => {
    // Drive the actual builder so a regression that injects a placeholder
    // patch surfaces here — the previous literal-only assertion proved
    // nothing about the production codepath.
    const result = {
      operation: { op_id: 'x', type: 'trim' },
      affectedChapters: [1],
      patch: undefined,
    };
    const payload = buildPayloadFromCommandResult(result as any);
    expect('patch' in payload.operations[0]!).toBe(false);
  });
});
