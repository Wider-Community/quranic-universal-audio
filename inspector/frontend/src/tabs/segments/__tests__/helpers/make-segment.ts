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
  confidence: number;
  ignored_categories?: string[];
  wrap_word_ranges?: number[][];
  audio_url?: string;
  ignored?: boolean;
  is_wasl?: boolean;
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

export interface SegmentStateLike {
  byId: Record<string, FixtureSegment>;
  idsByChapter: Record<number, string[]>;
  selectedChapter: number | null;
}

/**
 * Build a normalized segment-state for applyCommand reducer tests.
 *
 * `segments` must each carry `segment_uid`; the helper indexes them under
 * `byId` and groups every uid under `chapter` (default 1) in `idsByChapter`.
 */
export function makeApplyCommandState(
  segments: FixtureSegment[],
  opts: { chapter?: number; selectedChapter?: number | null } = {},
): SegmentStateLike {
  const chapter = opts.chapter ?? 1;
  const selectedChapter = opts.selectedChapter ?? chapter;
  const byId: Record<string, FixtureSegment> = {};
  const ids: string[] = [];
  for (const seg of segments) {
    byId[seg.segment_uid] = seg;
    ids.push(seg.segment_uid);
  }
  return {
    byId,
    idsByChapter: { [chapter]: ids },
    selectedChapter,
  };
}

/**
 * Alias for `makeApplyCommandState` parametrised by chapter — kept as a
 * convenience for callers that read more naturally with the second argument
 * as a bare chapter number.
 */
export function makeSegmentState(
  segs: FixtureSegment[],
  chapter: number = 1,
): SegmentStateLike {
  return makeApplyCommandState(segs, { chapter });
}
