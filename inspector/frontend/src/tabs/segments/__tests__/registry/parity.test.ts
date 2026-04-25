// TS-registry ↔ Python-registry parity test.
//
// The Python side is the source of truth; the TS twin must mirror it
// row-for-row. The Phase 1 implementation either hand-writes the mirror
// or generates it; either way, these assertions guarantee no drift.

import { describe, it, expect } from 'vitest';
import { xfail } from '../helpers/xfail';
import { loadOptional } from '../helpers/optional';

const mod = await loadOptional<{ IssueRegistry: any }>('../../domain/registry');
const IssueRegistry = mod?.IssueRegistry ?? null;

const PY_SNAPSHOT = {
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

describe.skipIf(!IssueRegistry)('TS ↔ Python registry parity', () => {
  it('TS registry matches Python registry snapshot', xfail('phase-1', () => {
    for (const [cat, want] of Object.entries(PY_SNAPSHOT)) {
      const row = IssueRegistry[cat];
      expect(row).toBeTruthy();
      for (const [key, value] of Object.entries(want)) {
        expect(row[key]).toBe(value);
      }
    }
  }));
});

describe.skipIf(IssueRegistry)('TS ↔ Python registry parity (deferred)', () => {
  it.todo('phase-1: domain/registry not yet present');
});
