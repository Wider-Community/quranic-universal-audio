/**
 * Report-target keying — the one place DOM-derived and wire-derived cell keys
 * are computed, so a persisted report maps onto the exact grid cell.
 *
 * A `CellKey` identifies a flaggable target within a verse: a whole word
 * (`w<wi>`) or a cell (`w<wi>:c<cellIndex>`, falling back to `w<wi>:l<letter>`
 * for synthesized cells with no raw `word.cells[]` index). `UnifiedDisplay`
 * stamps the matching `data-*` on each span; this module reads them back and
 * also derives the key from a `TsReportTarget` so public flags line up.
 */

import type { TsReportTarget } from '../../../lib/types/generated/schemas';

export type CellKey = string;

function intAttr(el: Element, name: string): number | null {
    const v = el.getAttribute(name);
    if (v == null || v === '') return null;
    const n = parseInt(v, 10);
    return Number.isNaN(n) ? null : n;
}

/** Key for a word target. */
export function wordKey(wordIndex: number): CellKey {
    return `w${wordIndex}`;
}

/** Key for a cell target — cell_index when known, else the source letter. */
export function cellKey(
    wordIndex: number,
    cellIndex: number | null,
    sourceLetterIndex: number | null,
): CellKey {
    if (cellIndex != null && cellIndex >= 0) return `w${wordIndex}:c${cellIndex}`;
    return `w${wordIndex}:l${sourceLetterIndex ?? -1}`;
}

/** The key a stored report maps to (must agree with the DOM keys above). */
export function targetCellKey(t: TsReportTarget): CellKey {
    if (t.kind === 'verse') return 'verse';
    if (t.kind === 'word') return wordKey(t.word_index ?? -1);
    return cellKey(t.word_index ?? -1, t.cell_index ?? null, t.source_letter_index ?? null);
}

/** Read a flaggable element's key (word block or cell span), or null. */
export function elCellKey(el: Element): CellKey | null {
    const wi = intAttr(el, 'data-word-index');
    if (wi == null) return null;
    const ci = intAttr(el, 'data-cell-index');
    const sli = intAttr(el, 'data-source-letter-index');
    if (ci == null && sli == null) return wordKey(wi); // word block
    return cellKey(wi, ci, sli);
}

/** Build a cell `TsReportTarget` from a clicked cell span (not a word block). */
export function cellTargetFromEl(el: Element): TsReportTarget | null {
    const wi = intAttr(el, 'data-word-index');
    if (wi == null) return null;
    const ci = intAttr(el, 'data-cell-index');
    const sli = intAttr(el, 'data-source-letter-index');
    if (ci == null && sli == null) return null; // not a cell
    const sg = intAttr(el, 'data-share-group');
    return {
        kind: 'cell',
        word_index: wi,
        source_letter_index: sli,
        cell_index: ci != null && ci >= 0 ? ci : null,
        phoneme_flat_index: null,
        share_group: sg,
    };
}

/** Does this element carry a tajweed rule (underline OR tooltip union)? */
export function elHasTajweed(el: Element): boolean {
    return el.getAttribute('data-has-tj') === '1';
}
