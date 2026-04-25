// Parametrized behavioral tests over ALL_CATEGORIES.

import { describe, it, expect } from 'vitest';
import { ALL_CATEGORIES, CAN_IGNORE_CATEGORIES, AUTO_SUPPRESS_CATEGORIES } from '../helpers/categories';
import { makeSegment } from '../helpers/make-segment';
import { loadOptional } from '../helpers/optional';

const regMod = await loadOptional<{ IssueRegistry: any }>('../../domain/registry');
const registry = regMod?.IssueRegistry ?? null;

describe.skipIf(!registry)('registry behavior — parametrized', () => {
  for (const cat of ALL_CATEGORIES) {
    it(`Ignore button visible iff registry.canIgnore (${cat})`, () => {
      const row = registry[cat];
      const wantsButton = !!row.canIgnore;
      const isInCanIgnoreList = CAN_IGNORE_CATEGORIES.includes(cat as any);
      expect(wantsButton).toBe(isInCanIgnoreList);
    });

    it(`auto_suppress flag is read from registry (${cat})`, () => {
      const row = registry[cat];
      const wants = !!row.autoSuppress;
      const expected = AUTO_SUPPRESS_CATEGORIES.includes(cat as any);
      expect(wants).toBe(expected);
    });

    it(`auto-suppress fires per registry through applyCommand (${cat})`, async () => {
      const acMod = await loadOptional<{ applyCommand: any }>('../../domain/apply-command');
      if (!acMod) throw new Error('phase-3 module not present');
      const seg = makeSegment(0, 0, 1000, { segment_uid: `uid-${cat}` });
      const result = acMod.applyCommand(
        { byId: { [`uid-${cat}`]: seg }, idsByChapter: { 1: [`uid-${cat}`] }, selectedChapter: 1 },
        { type: 'editFromCard', segmentUid: `uid-${cat}`, category: cat } as any,
      );
      const row = registry[cat];
      expect(result.operation).toBeTruthy();
      if (row.autoSuppress && row.scope === 'per_segment') {
        const updated = result.nextState.byId[`uid-${cat}`];
        expect(updated?.ignored_categories ?? []).toContain(cat);
      }
    });

    it(`card type dispatched from registry (${cat})`, () => {
      const row = registry[cat];
      expect(['generic', 'missingVerses', 'missingWords', 'error']).toContain(row.cardType);
    });
  }

  it('accordion order matches registry', () => {
    const orders = ALL_CATEGORIES.map((c) => registry[c].accordionOrder).sort((a, b) => a - b);
    expect(orders).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
  });
});

describe.skipIf(registry)('registry behavior (deferred)', () => {
  it.todo('phase-1: domain/registry not yet present');
});
