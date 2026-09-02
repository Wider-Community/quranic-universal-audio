/**
 * Inline row chips for sample mode — the signals a sample reviewer needs
 * without the validation accordion: low confidence, a detected repetition,
 * a verse with missing words, and — on samples that carry word timings — a
 * segment whose timings no longer cover its ref (a realign fixes it).
 */

import type { Segment } from '../../../../lib/types/view-models';
import type { VerseWordCounts } from '../data/references';
import { getConfClass } from '../validation/conf-class';
import { needsRealign } from './word-timings';

export type RowChip = 'low_conf' | 'repetition' | 'missing_words' | 'realign';

/** `"<chapter>:<index>"` — the key `missingWordsSegKeys` is built on. */
export function segKey(chapter: number, index: number): string {
    return `${chapter}:${index}`;
}

export function deriveRowChips(
    seg: Pick<Segment, 'matched_ref' | 'confidence' | 'wrap_word_ranges' | 'index' | 'word_timings'>,
    missingKeys: ReadonlySet<string>,
    chapter: number,
    vwc?: VerseWordCounts,
    sampleHasTimings = false,
): RowChip[] {
    const chips: RowChip[] = [];
    const conf = getConfClass(seg);
    if (conf === 'conf-low' || conf === 'conf-fail') chips.push('low_conf');
    if (seg.wrap_word_ranges) chips.push('repetition');
    if (missingKeys.has(segKey(chapter, seg.index))) chips.push('missing_words');
    if (sampleHasTimings && !seg.wrap_word_ranges && needsRealign(seg.matched_ref, seg.word_timings, vwc)) {
        chips.push('realign');
    }
    return chips;
}
