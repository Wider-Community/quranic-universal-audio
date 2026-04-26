/**
 * Issue Registry — TypeScript twin of
 * ``inspector/services/validation/registry.py``.
 *
 * Each row is the single source of truth for one validation category's
 * UI / persistence / suppression metadata. The Python and TS sides MUST
 * agree row-for-row; ``__tests__/registry/parity.test.ts`` enforces this.
 *
 * camelCase mirrors of the Python fields:
 *   kind / cardType / severity / accordionOrder / canIgnore /
 *   autoSuppress / persistsIgnore / scope / displayTitle / description.
 */

export type CardType = 'generic' | 'missingWords' | 'missingVerses' | 'error';
export type Severity = 'error' | 'warning' | 'info';
export type Scope = 'per_segment' | 'per_verse' | 'per_chapter';

export interface IssueDefinition {
    kind: string;
    cardType: CardType;
    severity: Severity;
    accordionOrder: number;
    canIgnore: boolean;
    autoSuppress: boolean;
    persistsIgnore: boolean;
    scope: Scope;
    displayTitle: string;
    description: string;
}

export const IssueRegistry: Readonly<Record<string, IssueDefinition>> = Object.freeze({
    failed: {
        kind: 'failed',
        cardType: 'generic',
        severity: 'error',
        accordionOrder: 1,
        canIgnore: false,
        autoSuppress: true,
        persistsIgnore: false,
        scope: 'per_segment',
        displayTitle: 'Failed Alignments',
        description: '',
    },
    missing_verses: {
        kind: 'missing_verses',
        cardType: 'missingVerses',
        severity: 'error',
        accordionOrder: 2,
        canIgnore: false,
        autoSuppress: true,
        persistsIgnore: false,
        scope: 'per_verse',
        displayTitle: 'Missing Verses',
        description: '',
    },
    missing_words: {
        kind: 'missing_words',
        cardType: 'missingWords',
        severity: 'error',
        accordionOrder: 3,
        canIgnore: false,
        autoSuppress: false,
        persistsIgnore: false,
        scope: 'per_verse',
        displayTitle: 'Missing Words',
        description: '',
    },
    structural_errors: {
        kind: 'structural_errors',
        cardType: 'error',
        severity: 'error',
        accordionOrder: 4,
        canIgnore: false,
        autoSuppress: true,
        persistsIgnore: false,
        scope: 'per_chapter',
        displayTitle: 'Structural Errors',
        description: '',
    },
    low_confidence: {
        kind: 'low_confidence',
        cardType: 'generic',
        severity: 'warning',
        accordionOrder: 5,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'Low Confidence',
        description: '',
    },
    repetitions: {
        kind: 'repetitions',
        cardType: 'generic',
        severity: 'warning',
        accordionOrder: 6,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'Detected Repetitions',
        description: '',
    },
    audio_bleeding: {
        kind: 'audio_bleeding',
        cardType: 'generic',
        severity: 'warning',
        accordionOrder: 7,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'Audio Bleeding',
        description: '',
    },
    boundary_adj: {
        kind: 'boundary_adj',
        cardType: 'generic',
        severity: 'warning',
        accordionOrder: 8,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'May Require Boundary Adjustment',
        description: '',
    },
    cross_verse: {
        kind: 'cross_verse',
        cardType: 'generic',
        severity: 'warning',
        accordionOrder: 9,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'Cross-verse',
        description: '',
    },
    qalqala: {
        kind: 'qalqala',
        cardType: 'generic',
        severity: 'info',
        accordionOrder: 10,
        canIgnore: true,
        autoSuppress: true,
        persistsIgnore: true,
        scope: 'per_segment',
        displayTitle: 'Qalqala',
        description: '',
    },
    muqattaat: {
        kind: 'muqattaat',
        cardType: 'generic',
        severity: 'info',
        accordionOrder: 11,
        canIgnore: false,
        autoSuppress: false,
        persistsIgnore: false,
        scope: 'per_segment',
        displayTitle: 'Muqattaʼat',
        description: '',
    },
});

const _entries = Object.entries(IssueRegistry) as [string, IssueDefinition][];

export const ALL_CATEGORIES: readonly string[] = _entries.map(([k]) => k);
export const PER_SEGMENT_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.scope === 'per_segment').map(([k]) => k);
export const PER_VERSE_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.scope === 'per_verse').map(([k]) => k);
export const PER_CHAPTER_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.scope === 'per_chapter').map(([k]) => k);
export const CAN_IGNORE_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.canIgnore).map(([k]) => k);
export const AUTO_SUPPRESS_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.autoSuppress).map(([k]) => k);
export const PERSISTS_IGNORE_CATEGORIES: readonly string[] = _entries
    .filter(([, v]) => v.persistsIgnore).map(([k]) => k);

/**
 * Append ``category`` to ``seg.ignored_categories`` when the registry entry
 * has ``autoSuppress=true`` and ``scope='per_segment'``.
 *
 * Per-verse and per-chapter categories are no-ops here: the next validation
 * pass is the source of truth for whether their issues resolved. Categories
 * with ``autoSuppress=false`` (e.g. ``muqattaat``, ``missing_words``) are
 * also no-ops.
 *
 * Returns the same ``seg`` (mutated in place) for fluent chaining.
 */
export function applyAutoSuppress<T extends { ignored_categories?: string[] }>(
    seg: T,
    category: string,
    _editOrigin: 'card' | 'main_list' | string,
): T {
    const defn = IssueRegistry[category];
    if (!defn) return seg;
    if (!defn.autoSuppress) return seg;
    if (defn.scope !== 'per_segment') return seg;
    if (!seg.ignored_categories) seg.ignored_categories = [];
    if (!seg.ignored_categories.includes(category)) {
        seg.ignored_categories.push(category);
    }
    return seg;
}

/**
 * Drop categories whose registry entry has ``persistsIgnore=false``.
 * The legacy ``"_all"`` marker passes through unchanged.
 */
export function filterPersistentIgnores(categories: readonly string[] | undefined | null): string[] {
    if (!categories) return [];
    const out: string[] = [];
    for (const cat of categories) {
        if (cat === '_all') {
            out.push(cat);
            continue;
        }
        const defn = IssueRegistry[cat];
        if (!defn || defn.persistsIgnore) out.push(cat);
    }
    return out;
}

/** Display titles indexed by category — derived for UI labels. */
export const ERROR_CAT_LABELS: Readonly<Record<string, string>> = Object.freeze(
    Object.fromEntries(_entries.map(([k, v]) => [k, v.displayTitle])),
);
