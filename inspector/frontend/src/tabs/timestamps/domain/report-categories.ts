/**
 * Timestamps report taxonomy — the categories + subtypes shown in the footer
 * Report drop-up, mirroring the backend wire contract
 * (`qua_shared/schemas/wire/ts_reports.py`).
 *
 * `flow` splits the categories by how a report is started:
 * - `comment` — verse-level, no target needed; the drop-up opens a comment
 *   composer inline (audio, other). Wired end-to-end.
 * - `target`  — the issue points at a specific spot (word / cell / phoneme /
 *   column) the user picks on the analysis grid (timing, tajweed, phonemes).
 *
 * Drop-up order is timing → tajweed → phonemes → silence → audio → other.
 * `mapping` is a valid backend category but intentionally not surfaced — kept as
 * `MAPPING_CATEGORY` for if we revisit the letter↔sound flow.
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
     *  deferred). `timing` / `phonemes` enter directly; `tajweed` + `silence`
     *  enter per subtype. */
    entersMode?: 'timing' | 'tajweed' | 'phonemes' | 'silence';
}

export const REPORT_CATEGORIES: ReportCategoryDef[] = [
    {
        id: 'timing',
        label: 'Timing',
        blurb: 'A boundary starts or ends off',
        flow: 'target',
        entersMode: 'timing',
        targetHint: 'Pick the word or cell on the analysis grid',
        // Timing classification is the two-axis onset/offset picker in the in-grid
        // control strip, not a category-level subtype list.
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
        id: 'phonemes',
        label: 'Phonemes',
        blurb: 'A phoneme is wrong or mislabeled',
        flow: 'target',
        entersMode: 'phonemes',
        targetHint: 'Pick the phonemes on the grid',
        subtypes: [],
    },
    {
        id: 'silence',
        label: 'Silence',
        blurb: 'A pause is wrong, unwanted, or missing',
        flow: 'target',
        entersMode: 'silence',
        targetHint: 'Pick a pause on the grid',
        subtypes: [
            { id: 'pause_boundary', label: 'Pause timing off' },
            { id: 'pause_wasl', label: "Pause shouldn't be here" },
            { id: 'pause_missed', label: 'Missing pause' },
        ],
    },
    {
        id: 'audio',
        label: 'Audio',
        blurb: 'Recording quality, or wrong / missing audio',
        flow: 'comment',
        subtypes: [],
        placeholder: 'What sounds wrong on this verse?',
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

/**
 * `mapping` (a letter bound to the wrong sound) — a valid backend category that
 * is intentionally not surfaced in the drop-up. Kept here so re-adding it later
 * is just a matter of slotting it back into `REPORT_CATEGORIES`.
 */
export const MAPPING_CATEGORY: ReportCategoryDef = {
    id: 'mapping',
    label: 'Mapping',
    blurb: 'A letter is bound to the wrong sound',
    flow: 'target',
    targetHint: 'Pick the letter-to-sound column on the grid',
    subtypes: [],
};
