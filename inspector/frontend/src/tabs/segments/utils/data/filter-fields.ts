import * as m from '../../../../lib/paraglide/messages';

/** Filter field descriptor — referenced by filters.ts / state.segActiveFilters. */
export interface SegFilterField {
    value: string;
    label: () => string;
    type: 'float' | 'int';
    neighbour?: boolean;
}

export const SEG_FILTER_FIELDS: readonly SegFilterField[] = [
    { value: 'duration_s',        label: m.segments_filter_field_duration_label,       type: 'float' },
    { value: 'num_words',         label: m.segments_filter_field_word_count_label,     type: 'int'   },
    { value: 'num_verses',        label: m.segments_filter_field_verses_spanned_label, type: 'int'   },
    { value: 'confidence_pct',    label: m.segments_filter_field_confidence_label,     type: 'float' },
    { value: 'silence_after_ms',  label: m.segments_filter_field_silence_after_label,  type: 'float', neighbour: true },
];
