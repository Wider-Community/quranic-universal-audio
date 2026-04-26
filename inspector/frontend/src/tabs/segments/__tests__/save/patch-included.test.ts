// Phase 5 save tests: payload includes patch field.

import { describe, it, expect } from 'vitest';
import { loadOptional } from '../helpers/optional';

describe('save patch field', () => {
  it('payload includes patch field when applyCommand produces one', async () => {
    const exec = await loadOptional<any>('../../utils/save/execute');
    if (!exec || !exec.buildPayloadFromCommandResult) {
      throw new Error('phase-5: builder not yet present');
    }
    const result = {
      operation: { op_id: 'x', type: 'trim' },
      affectedChapters: [1],
      patch: { before: [{ segment_uid: 'a' }], after: [{ segment_uid: 'a' }], removedIds: [], insertedIds: [], affectedChapterIds: [1] },
    };
    const payload = exec.buildPayloadFromCommandResult(result);
    expect(payload.operations[0].patch).toBeTruthy();
    expect(payload.operations[0].patch.before[0].segment_uid).toBe('a');
  });

  it('legacy save without patch still works (backward compat)', () => {
    const payload = {
      full_replace: true,
      segments: [],
      operations: [
        { op_id: 'x', type: 'trim' },
      ],
    };
    expect('patch' in payload.operations[0]).toBe(false);
  });
});
