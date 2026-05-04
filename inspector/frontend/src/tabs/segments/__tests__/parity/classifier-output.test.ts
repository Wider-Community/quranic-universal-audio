// Frontend reads classified_issues from backend DTOs; no live classification.

import { describe, it, expect } from 'vitest';
import { loadOptional } from '../helpers/optional';

const historyItems = await loadOptional<any>('../../utils/history/items');
const classifyMod = await loadOptional<any>('../../utils/validation/classify');
const classifiedIssues = await loadOptional<any>('../../utils/validation/classified-issues');

describe('classifier output parity', () => {
  it('frontend reads classified_issues field from backend DTO; no local classification', () => {
    expect(classifyMod).toBeNull();
    expect(classifiedIssues).not.toBeNull();
    expect(typeof classifiedIssues!.classifiedIssuesOf).toBe('function');
  });

  it('history items use stored classified_issues, not local classifier', () => {
    expect(historyItems).not.toBeNull();
    expect(historyItems!.usesStoredClassifiedIssues).toBe(true);
  });

  it('_classifySegCategories is no longer exported', () => {
    expect(classifyMod).toBeNull();
  });
});
