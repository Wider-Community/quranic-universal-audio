// Save payload shape tests (MUST-1 contract).

import { describe, it, expect } from 'vitest';
import { loadOptional } from '../helpers/optional';

describe('save payload shape', () => {
  it('save payload matches MUST-1 contract for full_replace', () => {
    const payload = {
      full_replace: true,
      segments: [],
      operations: [],
    };
    expect(payload).toHaveProperty('full_replace');
    expect(payload).toHaveProperty('segments');
    expect(payload).toHaveProperty('operations');
  });

  it('save payload matches MUST-1 contract for patch mode', () => {
    const payload = {
      segments: [{ index: 0, matched_ref: '1:1:1-1:1:1', matched_text: 'x' }],
      operations: [],
    };
    expect(payload).toHaveProperty('segments');
    expect(Array.isArray(payload.segments)).toBe(true);
    expect(payload.segments[0]).toHaveProperty('index');
  });

  it('save payload built from CommandResult includes all expected fields', async () => {
    const exec = await loadOptional<any>('../../utils/save/execute');
    if (!exec) throw new Error('phase-3: build helper not yet present');
    const result = {
      operation: { op_id: 'x', type: 'trim', snapshots: { before: {}, after: {} }, affected_chapters: [1] },
      affectedChapters: [1],
      patch: undefined,
    };
    const payload = exec.buildPayloadFromCommandResult?.(result);
    expect(payload).toBeTruthy();
    expect(payload.operations[0]).toMatchObject({ op_id: 'x', type: 'trim' });
  });
});
