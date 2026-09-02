/**
 * Locale lookup for edit-history operation-type labels, keyed by `op_type`.
 *
 * The English source of truth is `EDIT_OP_LABELS` in `../utils/constants`; this
 * module is the render-site indirection so the history UI (filter pills, batch and
 * op rows) localizes without those components reading the raw English map. Consumers
 * call `EDIT_OP_TITLE[opType]?.() ?? opType`. Keep this in sync with `EDIT_OP_LABELS`.
 */
import * as m from '../../../lib/paraglide/messages';

export const EDIT_OP_TITLE: Readonly<Record<string, () => string>> = Object.freeze({
    trim_segment: m.segments_history_optype_trim_segment,
    split_segment: m.segments_history_optype_split_segment,
    merge_segments: m.segments_history_optype_merge_segments,
    delete_segment: m.segments_history_optype_delete_segment,
    edit_reference: m.segments_history_optype_edit_reference,
    confirm_reference: m.segments_history_optype_confirm_reference,
    auto_fix_missing_word: m.segments_history_optype_auto_fix_missing_word,
    ignore_issue: m.segments_history_optype_ignore_issue,
    set_is_wasl: m.segments_history_optype_set_is_wasl,
    set_word_timings: m.segments_history_optype_set_word_timings,
    flag_segment: m.segments_history_optype_flag_segment,
    pipeline: m.segments_history_optype_pipeline,
    remove_sadaqa: m.segments_history_optype_remove_sadaqa,
});

/** Localized op-type label with a raw-value fallback for unmapped ops. */
export function editOpLabel(opType: string | null | undefined): string {
    if (!opType) return '';
    return EDIT_OP_TITLE[opType]?.() ?? opType;
}
