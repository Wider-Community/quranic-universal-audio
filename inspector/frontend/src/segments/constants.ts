/**
 * Segments-tab module-level constants — label dictionaries, filter field/op
 * registries, playback-speed list, ID allowlists, and pre-compiled regexes.
 *
 * Pulled out of `state.ts` so the hub stays focused on mutable state + helpers.
 * No runtime state here; every symbol is a `const` or `as const`.
 */

export const EDIT_OP_LABELS: Record<string, string> = {
    trim_segment: 'Boundary adjustment', split_segment: 'Split',
    merge_segments: 'Merge', delete_segment: 'Deletion',
    edit_reference: 'Reference edit', confirm_reference: 'Reference confirmation',
    auto_fix_missing_word: 'Auto-fix missing word', ignore_issue: 'Ignored issue',
    waqf_sakt: 'Waqf sakt merge', remove_sadaqa: 'Remove Sadaqa',
};

export const ERROR_CAT_LABELS: Record<string, string> = {
    failed: 'Failed', low_confidence: 'Low confidence',
    boundary_adj: 'Boundary adj.',
    cross_verse: 'Cross-verse', missing_words: 'Missing words',
    audio_bleeding: 'Audio bleeding',
    repetitions: 'Repetitions',
    muqattaat: 'Muqattaat letters',
    qalqala: 'Qalqala',
};

/** Filter field descriptor — referenced by filters.ts / state.segActiveFilters. */
export interface SegFilterField {
    value: string;
    label: string;
    type: 'float' | 'int';
    neighbour?: boolean;
}

export const SEG_FILTER_FIELDS: readonly SegFilterField[] = [
    { value: 'duration_s',        label: 'Duration (s)',       type: 'float' },
    { value: 'num_words',         label: 'Word count',         type: 'int'   },
    { value: 'num_verses',        label: 'Verses spanned',     type: 'int'   },
    { value: 'confidence_pct',    label: 'Confidence (%)',      type: 'float' },
    { value: 'silence_after_ms',  label: 'Silence after (ms)',  type: 'float', neighbour: true },
];

export const SEG_FILTER_OPS: readonly string[] = ['>', '>=', '<', '<=', '='];

export const SEG_SPEEDS: readonly number[] = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];

export const _SEG_NORMAL_IDS: readonly string[] = ['seg-stats-panel', 'seg-validation-global', 'seg-validation',
    'seg-filter-bar', 'seg-list'];

export const _ARABIC_DIGITS: readonly string[] = ['\u0660','\u0661','\u0662','\u0663','\u0664','\u0665','\u0666','\u0667','\u0668','\u0669'];

export const _MN_RE = /[\u0300-\u036F\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06E8\u06EA-\u06ED\u08D3-\u08FF\uFE20-\uFE2F]/;
export const _STRIP_CHARS: ReadonlySet<string> = new Set(['\u0640', '\u06DE', '\u06E6', '\u06E9', '\u200F']);
export const _LETTER_RE = /\p{L}/u;
