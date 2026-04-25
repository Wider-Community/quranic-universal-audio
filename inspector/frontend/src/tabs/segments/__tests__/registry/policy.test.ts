// Snapshot tests pinning the TS-side IssueRegistry to plan Appendix A.
//
// Pre-Phase-1 the registry module does not exist; the dynamic import skips
// the suite. Once Phase 1 lands `domain/registry.ts`, these tests become
// the load-bearing artifact for the matrix.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ IssueRegistry: any }>('../../domain/registry');
const IssueRegistry = mod?.IssueRegistry ?? null;

const EXPECTED = {
  failed:            { canIgnore: false, autoSuppress: true,  persistsIgnore: false, scope: 'per_segment', cardType: 'generic',        severity: 'error' },
  missing_verses:    { canIgnore: false, autoSuppress: true,  persistsIgnore: false, scope: 'per_verse',   cardType: 'missingVerses',  severity: 'error' },
  missing_words:     { canIgnore: false, autoSuppress: false, persistsIgnore: false, scope: 'per_verse',   cardType: 'missingWords',   severity: 'error' },
  structural_errors: { canIgnore: false, autoSuppress: true,  persistsIgnore: false, scope: 'per_chapter', cardType: 'error',          severity: 'error' },
  low_confidence:    { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'warning' },
  repetitions:       { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'warning' },
  audio_bleeding:    { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'warning' },
  boundary_adj:      { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'warning' },
  cross_verse:       { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'warning' },
  qalqala:           { canIgnore: true,  autoSuppress: true,  persistsIgnore: true,  scope: 'per_segment', cardType: 'generic',        severity: 'info' },
  muqattaat:         { canIgnore: false, autoSuppress: false, persistsIgnore: false, scope: 'per_segment', cardType: 'generic',        severity: 'info' },
};

describe.skipIf(!IssueRegistry)('registry policy snapshot', () => {
  it('pins matrix verbatim (TS)', xfail('phase-1', () => {
    for (const [cat, want] of Object.entries(EXPECTED)) {
      const row = IssueRegistry[cat];
      expect(row).toBeTruthy();
      for (const [key, value] of Object.entries(want)) {
        expect(row[key]).toBe(value);
      }
    }
  }));

  it('mirror parity with Python registry', xfail('phase-1', () => {
    const keys = Object.keys(IssueRegistry).sort();
    expect(keys).toEqual(Object.keys(EXPECTED).sort());
  }));
});

describe.skipIf(IssueRegistry)('registry policy (deferred)', () => {
  it.todo('phase-1: domain/registry not yet present — once it is, the snapshot tests above run');
});
