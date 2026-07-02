/**
 * Timestamps report taxonomy — the categories shown in the footer
 * Report drop-up, mirroring the backend wire contract
 * (`qua_shared/schemas/wire/ts_reports.py`).
 *
 * `flow` splits the categories by how a report is started:
 * - `comment` — verse-level, no target needed; the drop-up opens a comment
 *   composer inline (audio, other). Wired end-to-end.
 * - `target`  — the issue points at a specific spot (word / cell / phoneme)
 *   the user picks on the analysis grid (timing, tajweed, phonemes).
 *
 * Drop-up order is timing → tajweed → phonemes → silence → audio → other.
 */

import * as m from '$lib/paraglide/messages';
import type { TsReport } from '../../../lib/types/generated/schemas';

/** Category literal union, sourced from the codegen'd wire model. */
export type ReportCategory = TsReport['category'];

export type ReportFlow = 'comment' | 'target';

export interface ReportCategoryDef {
    id: ReportCategory;
    /** Message-function reference — call at the render site so a locale switch re-evaluates it. */
    label: () => string;
    /** One-line descriptor under the label. */
    blurb: () => string;
    flow: ReportFlow;
    /** Composer placeholder (comment flow). */
    placeholder?: () => string;
    /** Target-flow categories that enter the in-grid report mode. `timing` /
     *  `phonemes` enter directly; `tajweed` + `silence` enter per subtype. */
    entersMode?: 'timing' | 'tajweed' | 'phonemes' | 'silence';
}

export const REPORT_CATEGORIES: ReportCategoryDef[] = [
    {
        id: 'timing',
        label: m.ts_report_category_timing_label,
        blurb: m.ts_report_category_timing_blurb,
        flow: 'target',
        entersMode: 'timing',
    },
    {
        id: 'tajweed',
        label: m.ts_report_category_tajweed_label,
        blurb: m.ts_report_category_tajweed_blurb,
        flow: 'target',
        entersMode: 'tajweed',
    },
    {
        id: 'phonemes',
        label: m.ts_report_category_phonemes_label,
        blurb: m.ts_report_category_phonemes_blurb,
        flow: 'target',
        entersMode: 'phonemes',
    },
    {
        id: 'silence',
        label: m.ts_report_category_silence_label,
        blurb: m.ts_report_category_silence_blurb,
        flow: 'target',
        entersMode: 'silence',
    },
    {
        id: 'audio',
        label: m.ts_report_category_audio_label,
        blurb: m.ts_report_category_audio_blurb,
        flow: 'comment',
        placeholder: m.ts_report_category_audio_placeholder,
    },
    {
        id: 'other',
        label: m.ts_report_category_other_label,
        blurb: m.ts_report_category_other_blurb,
        flow: 'comment',
        placeholder: m.ts_report_category_other_placeholder,
    },
];
