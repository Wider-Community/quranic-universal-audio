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
