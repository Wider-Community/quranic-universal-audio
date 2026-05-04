// Placeholder list of validation category names. Mirrors what the issue
// registry will export once ``../../domain/registry.ts`` is introduced.
//
// Order matches the accordion declaration in plan §Appendix A.

export const ALL_CATEGORIES = [
  'failed',
  'missing_verses',
  'missing_words',
  'structural_errors',
  'low_confidence',
  'repetitions',
  'audio_bleeding',
  'boundary_adj',
  'cross_verse',
  'qalqala',
  'muqattaat',
] as const;

export type CategoryName = typeof ALL_CATEGORIES[number];

export const PER_SEGMENT_CATEGORIES: CategoryName[] = [
  'failed',
  'low_confidence',
  'repetitions',
  'audio_bleeding',
  'boundary_adj',
  'cross_verse',
  'qalqala',
  'muqattaat',
];

export const CAN_IGNORE_CATEGORIES: CategoryName[] = [
  'low_confidence',
  'repetitions',
  'audio_bleeding',
  'boundary_adj',
  'cross_verse',
  'qalqala',
];

export const PERSISTS_IGNORE_CATEGORIES: CategoryName[] = [...CAN_IGNORE_CATEGORIES];

export const AUTO_SUPPRESS_CATEGORIES: CategoryName[] = [
  'failed',
  'missing_verses',
  'structural_errors',
  'low_confidence',
  'repetitions',
  'audio_bleeding',
  'boundary_adj',
  'cross_verse',
  'qalqala',
];
