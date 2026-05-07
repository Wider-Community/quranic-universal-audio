// Builder for synthetic segment dicts used across the vitest suite.
//
// Provides a single canonical shape so tests don't drift on which fields
// they include. Matches the on-disk detailed.json segment schema documented
// in the fixtures README.

let __uid_counter = 0;

export interface FixtureSegment {
  segment_uid: string;
  time_start: number;
  time_end: number;
  matched_ref: string;
  matched_text: string;
  phonemes_asr: string;
  confidence: number;
  ignored_categories?: string[];
  wrap_word_ranges?: number[][];
  has_repeated_words?: boolean;
  audio_url?: string;
  ignored?: boolean;
}

export function makeSegment(
  index: number,
  startMs: number,
  endMs: number,
  overrides: Partial<FixtureSegment> = {},
): FixtureSegment {
  const uid = overrides.segment_uid ?? `test-uid-${index}-${++__uid_counter}`;
  return {
    segment_uid: uid,
    time_start: startMs,
    time_end: endMs,
    matched_ref: '1:1:1-1:1:1',
    matched_text: 'x',
    phonemes_asr: '',
    confidence: 1.0,
    ...overrides,
  };
}

export function makeSegments(count: number, startMs = 0, durMs = 1000): FixtureSegment[] {
  const out: FixtureSegment[] = [];
  for (let i = 0; i < count; i++) {
    const s = startMs + i * durMs;
    out.push(makeSegment(i, s, s + durMs));
  }
  return out;
}
