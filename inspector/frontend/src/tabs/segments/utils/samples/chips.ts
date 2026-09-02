/**
 * Inline row chips for sample mode — the three signals a sample reviewer
 * needs without the validation accordion: low confidence, a detected
 * repetition, and a verse with missing words. The word-realign status chip
 * is driven separately by `auto-realign.ts`.
 */

import type { Segment } from '../../../../lib/types/view-models';
import { getConfClass } from '../validation/conf-class';

export type RowChip = 'low_conf' | 'repetition' | 'missing_words';

/** `"<chapter>:<index>"` — the key `missingWordsSegKeys` is built on. */
export function segKey(chapter: number, index: number): string {
    return `${chapter}:${index}`;
}

export function deriveRowChips(
    seg: Pick<Segment, 'matched_ref' | 'confidence' | 'wrap_word_ranges' | 'index'>,
    missingKeys: ReadonlySet<string>,
    chapter: number,
): RowChip[] {
    const chips: RowChip[] = [];
    const conf = getConfClass(seg);
    if (conf === 'conf-low' || conf === 'conf-fail') chips.push('low_conf');
    if (seg.wrap_word_ranges) chips.push('repetition');
    if (missingKeys.has(segKey(chapter, seg.index))) chips.push('missing_words');
    return chips;
}
