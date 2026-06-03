/**
 * Mark-ready form copy module.
 *
 * Long-form UI text for the Mark Ready modal + the admin Reviews drawer
 * lives in three sibling .md files. This module imports them via Vite's
 * ?raw modifier and parses a tiny `### key`/paragraph format into a
 * typed object. Edit the .md files to change wording — never edit text
 * inline in the Svelte components.
 *
 * The checklist key set MUST stay in lockstep with the backend Pydantic
 * `MarkReadyChecklist` model in qua_shared/schemas/mark_ready.py. A
 * parity test under __tests__ asserts both sides match.
 */
import type { MarkReadyChecklist } from '../../../../lib/types/generated/schemas';
import checklistMd from './checklist.md?raw';
import commentsMd from './comments.md?raw';
import formMd from './form.md?raw';

/** Literal union of checklist keys — single source of truth for the FE.
 *  Mirrors `ChecklistKey` on the backend. Adding a key requires updating
 *  the .md file, the backend Pydantic model, and the parity test. */
export type ChecklistKey = keyof MarkReadyChecklist;

export const CHECKLIST_ORDER: readonly ChecklistKey[] = [
    'failed_alignments',
    'missing_words',
    'low_confidence',
    'repetitions',
    'splits_wasl_waqf',
    'basmala_amin_intros',
] as const;

/** Six validation `category_counts` keys that BLOCK submission. Mirrors
 *  `BLOCKING_COUNT_KEYS` on the backend. The reviewer must resolve or
 *  ignore each non-zero category before they can mark ready. */
export const BLOCKING_COUNT_KEYS = [
    'low_confidence',
    'low_confidence_v2',
    'boundary_adj',
    'cross_verse',
    'basmala_amin',
    'repetitions',
] as const;

export type BlockingCountKey = (typeof BLOCKING_COUNT_KEYS)[number];

/** Human label per blocking-count key — what the reviewer sees in the
 *  inline "you can't submit yet" panel. */
export const BLOCKING_LABELS: Record<BlockingCountKey, string> = {
    low_confidence: 'Low confidence',
    low_confidence_v2: 'Low confidence v2',
    boundary_adj: 'May require boundary adjustment',
    cross_verse: 'Cross-verse',
    basmala_amin: 'Basmala + amin',
    repetitions: 'Repetitions',
};

export interface MarkReadyCopy {
    form: {
        title: string;
        warning: string;
        blockingLede: string;
        submit: string;
        cancel: string;
        submitting: string;
    };
    checklist: Array<{ key: ChecklistKey; label: string }>;
    comments: {
        checks: { label: string; placeholder: string };
        issues: { label: string; placeholder: string };
    };
}

/** Parse a sibling .md file into a `{ key: paragraph }` map.
 *  Format: each section begins with `### <key>` on its own line, followed
 *  by one or more body lines until the next `### ` or end-of-file. Blank
 *  lines around bodies are trimmed. Anything before the first `### ` is
 *  ignored (lets the .md files start with a comment block if needed). */
function parseSections(md: string): Record<string, string> {
    const out: Record<string, string> = {};
    const lines = md.split(/\r?\n/);
    let key: string | null = null;
    let buf: string[] = [];
    const flush = () => {
        if (key !== null) out[key] = buf.join('\n').trim();
        buf = [];
    };
    for (const line of lines) {
        const m = line.match(/^###\s+([\w-]+)\s*$/);
        if (m && m[1]) {
            flush();
            key = m[1];
            continue;
        }
        if (key !== null) buf.push(line);
    }
    flush();
    return out;
}

function expect(map: Record<string, string>, key: string, file: string): string {
    const v = map[key];
    if (!v) throw new Error(`mark-ready copy: missing "### ${key}" in ${file}`);
    return v;
}

const formSections = parseSections(formMd);
const checklistSections = parseSections(checklistMd);
const commentsSections = parseSections(commentsMd);

export const markReadyCopy: MarkReadyCopy = {
    form: {
        title: expect(formSections, 'title', 'form.md'),
        warning: expect(formSections, 'warning', 'form.md'),
        blockingLede: expect(formSections, 'blocking_lede', 'form.md'),
        submit: expect(formSections, 'submit', 'form.md'),
        cancel: expect(formSections, 'cancel', 'form.md'),
        submitting: expect(formSections, 'submitting', 'form.md'),
    },
    checklist: CHECKLIST_ORDER.map((key) => ({
        key,
        label: expect(checklistSections, key, 'checklist.md'),
    })),
    comments: {
        checks: {
            label: expect(commentsSections, 'checks_label', 'comments.md'),
            placeholder: expect(commentsSections, 'checks_placeholder', 'comments.md'),
        },
        issues: {
            label: expect(commentsSections, 'issues_label', 'comments.md'),
            placeholder: expect(commentsSections, 'issues_placeholder', 'comments.md'),
        },
    },
};

export function emptyChecklist(): MarkReadyChecklist {
    return {
        failed_alignments: false,
        missing_words: false,
        low_confidence: false,
        repetitions: false,
        splits_wasl_waqf: false,
        basmala_amin_intros: false,
    };
}

export function isAllChecked(checklist: MarkReadyChecklist): boolean {
    return CHECKLIST_ORDER.every((k) => checklist[k]);
}
