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

import type { TsReport } from '../../../lib/types/generated/schemas';

/** Category literal union, sourced from the codegen'd wire model. */
export type ReportCategory = TsReport['category'];

export type ReportFlow = 'comment' | 'target';

export interface ReportCategoryDef {
    id: ReportCategory;
    label: string;
    /** One-line descriptor under the label. */
    blurb: string;
    flow: ReportFlow;
    /** Composer placeholder (comment flow). */
    placeholder?: string;
    /** Target-flow categories that enter the in-grid report mode. `timing` /
     *  `phonemes` enter directly; `tajweed` + `silence` enter per subtype. */
    entersMode?: 'timing' | 'tajweed' | 'phonemes' | 'silence';
}

export const REPORT_CATEGORIES: ReportCategoryDef[] = [
    {
        id: 'timing',
        label: 'Timing',
        blurb: 'A boundary starts or ends off',
        flow: 'target',
        entersMode: 'timing',
    },
    {
        id: 'tajweed',
        label: 'Tajweed',
        blurb: 'A rule is wrong, missing, or mis-applied',
        flow: 'target',
        entersMode: 'tajweed',
    },
    {
        id: 'phonemes',
        label: 'Phonemes',
        blurb: 'A phoneme is wrong or mislabeled',
        flow: 'target',
        entersMode: 'phonemes',
    },
    {
        id: 'silence',
        label: 'Silence',
        blurb: 'A pause is wrong, unwanted, or missing',
        flow: 'target',
        entersMode: 'silence',
    },
    {
        id: 'audio',
        label: 'Audio',
        blurb: 'Recording quality, or wrong / missing audio',
        flow: 'comment',
        placeholder: 'What sounds wrong on this verse?',
    },
    {
        id: 'other',
        label: 'Other',
        blurb: 'Anything else about this verse',
        flow: 'comment',
        placeholder: 'Describe the issue…',
    },
];
