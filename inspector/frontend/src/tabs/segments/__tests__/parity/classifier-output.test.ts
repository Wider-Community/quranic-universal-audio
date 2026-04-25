// Phase 2: frontend reads classified_issues from backend DTO.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { loadOptional } from '../helpers/optional';

const historyItems = await loadOptional<any>('../../utils/history/items');
const classifyMod = await loadOptional<any>('../../utils/validation/classify');

describe('classifier output parity', () => {
  it('frontend reads classified_issues field from backend DTO; no local classification', xfail('phase-2', () => {
    // Phase 2 contract: when the frontend processes a snapshot, it MUST consult
    // the snapshot's `classified_issues` field rather than running a local
    // classifier. Pre-Phase-2 the local classifier (`utils/validation/classify`)
    // exists; post-Phase-2 it is deleted.
    if (classifyMod) {
      throw new Error('utils/validation/classify still present pre-Phase-2');
    }
  }));

  it('history items use stored classified_issues, not local classifier', xfail('phase-2', async () => {
    // Phase 2: history-row helper reads classified_issues from snapshot.
    // Pre-Phase-2 the helper does NOT yet expose a non-classifier code path,
    // so this assertion fails until Phase 2 lands the change.
    const items = await loadOptional<any>('../../utils/history/items');
    if (!items?.usesStoredClassifiedIssues) {
      throw new Error('phase-2: history items helper does not yet read stored classified_issues');
    }
    expect(items.usesStoredClassifiedIssues).toBe(true);
  }));

  it('_classifySegCategories is no longer exported', xfail('phase-2', () => {
    if (classifyMod && '_classifySegCategories' in classifyMod) {
      // Surprise-pass guard: the symbol is still there, so the test correctly fails.
      throw new Error('_classifySegCategories must not be exported post-Phase-2');
    }
    if (classifyMod) {
      throw new Error('classify module still present; Phase 2 must delete it');
    }
  }));
});
