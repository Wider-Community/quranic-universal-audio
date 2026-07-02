/**
 * Report-target keying — the one place DOM-derived and wire-derived cell keys
 * are computed, so a persisted report maps onto the exact grid cell.
 *
 * A `CellKey` identifies a flaggable target within a verse: a whole word
 * (`w<wi>`), a cell (`w<wi>:c<cellIndex>`, falling back to `w<wi>:l<letter>`
 * for synthesized cells with no raw `word.cells[]` index), or a phoneme
 * (`w<wi>:p<flat>`, keyed on the word-local indexable-phone index).
 * `UnifiedDisplay` stamps the matching `data-*` on each span; this module reads
 * them back and also derives the key from a `TsReportTarget` so public flags
 * line up.
 */

import * as m from '$lib/paraglide/messages';
import type { TsReportTarget } from '../../../lib/types/generated/schemas';

export type CellKey = string;

/** A timing boundary's error direction. A timing report flags the onset (start)
 *  and/or offset (end); `null` on an axis means that boundary is fine. */
export type TimingDir = 'early' | 'late';

/** Human label for a timing report's onset/offset axes — the report matrix.
 *  Mirrors `qua_shared/schemas/wire/ts_reports.py::timing_label`. */
export function timingLabel(onset: TimingDir | null, offset: TimingDir | null): string {
    const key = `${onset ?? ''}|${offset ?? ''}`;
    const both: Record<string, () => string> = {
        'early|late': m.ts_report_timing_label_too_long,
        'late|early': m.ts_report_timing_label_too_short,
        'early|early': m.ts_report_timing_label_shifted_earlier,
        'late|late': m.ts_report_timing_label_shifted_later,
    };
    const hit = both[key];
    if (hit) return hit();
    if (onset && !offset) return onset === 'early' ? m.ts_report_timing_label_starts_early() : m.ts_report_timing_label_starts_late();
    if (offset && !onset) return offset === 'early' ? m.ts_report_timing_label_finishes_early() : m.ts_report_timing_label_finishes_late();
    return m.ts_report_timing_label_default();
}

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

/** Key for a phoneme target — keyed on the word-local indexable-phone index. */
export function phonemeKey(wordIndex: number, phonemeFlatIndex: number): CellKey {
    return `w${wordIndex}:p${phonemeFlatIndex}`;
}

/** Key for a co-highlight group — every cell sharing the group collapses to this
 *  one key, so a shared rule (idgham, madd carrier + vowel, …) stages as ONE
 *  report and all its cells flag/select together. */
export function groupKey(shareGroup: number): CellKey {
    return `g${shareGroup}`;
}

/** Key for a word-boundary gap target (silence reports) — the boundary between
 *  word `i` and `i+1`, keyed on the preceding word `i`. Both the existing pause
 *  bridge and an inserted missed-pause slot at that boundary resolve here. */
export function gapKey(wordIndex: number): CellKey {
    return `gap${wordIndex}`;
}

/** The key a stored report maps to (must agree with the DOM keys above). */
export function targetCellKey(t: TsReportTarget): CellKey {
    if (t.kind === 'verse') return 'verse';
    if (t.kind === 'gap') return gapKey(t.word_index ?? -1);
    if (t.kind === 'word') return wordKey(t.word_index ?? -1);
    if (t.kind === 'cell_group' && t.share_group != null) return groupKey(t.share_group);
    if (t.kind === 'phoneme') return phonemeKey(t.word_index ?? -1, t.phoneme_flat_index ?? -1);
    return cellKey(t.word_index ?? -1, t.cell_index ?? null, t.source_letter_index ?? null);
}

/** Read a flaggable element's key (word block, cell span, phoneme, or gap), or null. */
export function elCellKey(el: Element): CellKey | null {
    // A gap tile (pause bridge / missed-pause slot) keys on its boundary word.
    const gw = intAttr(el, 'data-gap-word-index');
    if (gw != null) return gapKey(gw);
    const wi = intAttr(el, 'data-word-index');
    if (wi == null) return null;
    // A cell in a co-highlight group collapses to the group key, so all its cells
    // share one staged report + flag together.
    const sg = intAttr(el, 'data-share-group');
    if (sg != null && el.hasAttribute('data-cell-index')) return groupKey(sg);
    const ci = intAttr(el, 'data-cell-index');
    const sli = intAttr(el, 'data-source-letter-index');
    const pfi = intAttr(el, 'data-phoneme-flat-index');
    if (ci == null && sli == null) {
        if (pfi != null) return phonemeKey(wi, pfi); // phoneme span
        return wordKey(wi); // word block
    }
    return cellKey(wi, ci, sli);
}

/** Build a `TsReportTarget` from a clicked cell or phoneme span (not a word
 *  block). A phoneme span carries `data-phoneme-flat-index` but no cell index. */
export function cellTargetFromEl(el: Element): TsReportTarget | null {
    const gw = intAttr(el, 'data-gap-word-index');
    if (gw != null) {
        return {
            kind: 'gap',
            word_index: gw,
            source_letter_index: null,
            cell_index: null,
            phoneme_flat_index: null,
            share_group: null,
        };
    }
    const wi = intAttr(el, 'data-word-index');
    if (wi == null) return null;
    const ci = intAttr(el, 'data-cell-index');
    const sli = intAttr(el, 'data-source-letter-index');
    if (ci == null && sli == null) {
        const pfi = intAttr(el, 'data-phoneme-flat-index');
        if (pfi == null) return null; // not a cell or phoneme
        return {
            kind: 'phoneme',
            word_index: wi,
            source_letter_index: null,
            cell_index: null,
            phoneme_flat_index: pfi,
            share_group: null,
        };
    }
    const sg = intAttr(el, 'data-share-group');
    return {
        // A grouped cell targets the whole co-highlight group; a lone cell targets itself.
        kind: sg != null ? 'cell_group' : 'cell',
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
