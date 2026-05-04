// Vitest-side fixture loader. Resolves the same JSON files the backend
// pytest suite loads via ``conftest.py:load_fixture``.
//
// The Vite alias `@fixtures` is wired in `inspector/frontend/vitest.config.ts`
// to the absolute path of `inspector/tests/fixtures/segments/`. That directory
// is the single source of truth — never duplicate fixtures into the frontend
// tree.

import ikhlas from '@fixtures/112-ikhlas.detailed.json';
import falaq from '@fixtures/113-falaq.detailed.json';
import structural from '@fixtures/synthetic-structural.detailed.json';
import classifier from '@fixtures/synthetic-classifier.detailed.json';

import ikhlasExpected from '@fixtures/expected/112-ikhlas.classify.json';
import falaqExpected from '@fixtures/expected/113-falaq.classify.json';
import structuralExpected from '@fixtures/expected/synthetic-structural.classify.json';
import classifierExpected from '@fixtures/expected/synthetic-classifier.classify.json';

export type FixtureName =
  | '112-ikhlas'
  | '113-falaq'
  | 'synthetic-structural'
  | 'synthetic-classifier';

/** Minimal top-level shape of a ``*.detailed.json`` fixture file. */
export interface RawDetailedFixture {
  _meta: Record<string, unknown>;
  _fixture_meta?: Record<string, unknown>;
  entries: Array<Record<string, unknown>>;
}

/** Minimal top-level shape of a ``expected/*.classify.json`` baseline file. */
export interface RawClassifyExpected {
  _meta: Record<string, unknown>;
  by_segment_uid: Record<string, { categories: string[]; [key: string]: unknown }>;
  category_counts: Record<string, number>;
}

const FIXTURES: Record<FixtureName, unknown> = {
  '112-ikhlas': ikhlas,
  '113-falaq': falaq,
  'synthetic-structural': structural,
  'synthetic-classifier': classifier,
};

const EXPECTED_CLASSIFY: Record<FixtureName, unknown> = {
  '112-ikhlas': ikhlasExpected,
  '113-falaq': falaqExpected,
  'synthetic-structural': structuralExpected,
  'synthetic-classifier': classifierExpected,
};

export function loadFixture<T = RawDetailedFixture>(name: FixtureName): T {
  const f = FIXTURES[name];
  if (!f) throw new Error(`unknown fixture: ${name}`);
  return JSON.parse(JSON.stringify(f)) as T;
}

export function loadExpectedClassify<T = RawClassifyExpected>(name: FixtureName): T {
  const f = EXPECTED_CLASSIFY[name];
  if (!f) throw new Error(`no expected classify baseline for: ${name}`);
  return JSON.parse(JSON.stringify(f)) as T;
}

export const FIXTURE_NAMES: FixtureName[] = [
  '112-ikhlas',
  '113-falaq',
  'synthetic-structural',
  'synthetic-classifier',
];
