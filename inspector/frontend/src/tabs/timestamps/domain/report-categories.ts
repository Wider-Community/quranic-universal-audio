/**
 * Timestamps report taxonomy — the categories + subtypes shown in the footer
 * Report drop-up, mirroring the backend wire contract
 * (`qua_shared/schemas/wire/ts_reports.py`).
 *
 * `flow` splits the categories by how a report is started:
 * - `comment` — verse-level, no target needed; the drop-up opens a comment
 *   composer inline (audio, other). Wired end-to-end.
 * - `target`  — the issue points at a specific spot (word / cell / phoneme /
 *   column) the user picks on the analysis grid (timing, mapping, tajweed).
 *   The picker is the next step; these rows render but defer to `targetHint`.
 *
 * Order matches the backend category order. Labels/blurbs are user-facing.
 */

import type { TsReport } from '../../../lib/types/generated/schemas';

/** Category + subtype literal unions, sourced from the codegen'd wire model. */
export type ReportCategory = TsReport['category'];
export type ReportSubtype = NonNullable<TsReport['subtype']>;

export type ReportFlow = 'comment' | 'target';

export interface ReportSubtypeDef {
    id: ReportSubtype;
    label: string;
}

export interface ReportCategoryDef {
    id: ReportCategory;
    label: string;
    /** One-line descriptor under the label. */
    blurb: string;
    flow: ReportFlow;
    subtypes: ReportSubtypeDef[];
    /** Composer placeholder (comment flow). */
    placeholder?: string;
    /** What to point at on the grid (target flow). */
    targetHint?: string;
    /** Target-flow categories that enter the in-grid report mode (others stay
     *  deferred). `timing` enters directly; `tajweed` enters per subtype. */
    entersMode?: 'timing' | 'tajweed';
}

export const REPORT_CATEGORIES: ReportCategoryDef[] = [
    {
        id: 'audio',
        label: 'Audio',
        blurb: 'Recording quality, or wrong / missing audio',
        flow: 'comment',
        subtypes: [],
        placeholder: 'What sounds wrong on this verse?',
    },
    {
        id: 'timing',
        label: 'Timing',
        blurb: 'A boundary starts or ends off',
        flow: 'target',
        entersMode: 'timing',
        targetHint: 'Pick the word or cell on the analysis grid',
        subtypes: [
            { id: 'too_long', label: 'Too long' },
            { id: 'too_short', label: 'Too short' },
            { id: 'other', label: 'Other timing issue' },
        ],
    },
    {
        id: 'mapping',
        label: 'Mapping',
        blurb: 'A letter is bound to the wrong sound',
        flow: 'target',
        targetHint: 'Pick the letter-to-sound column on the grid',
        subtypes: [],
    },
    {
        id: 'tajweed',
        label: 'Tajweed',
        blurb: 'A rule is wrong, missing, or mis-applied',
        flow: 'target',
        entersMode: 'tajweed',
        targetHint: 'Pick the cell on the grid',
        subtypes: [
            { id: 'wrong_rule', label: 'Wrong rule' },
            { id: 'missing_rule', label: 'Missing rule' },
            { id: 'should_be_silent', label: 'Should be silent' },
            { id: 'should_not_be_silent', label: 'Should not be silent' },
        ],
    },
    {
        id: 'other',
        label: 'Other',
        blurb: 'Anything else about this verse',
        flow: 'comment',
        subtypes: [],
        placeholder: 'Describe the issue…',
    },
];
