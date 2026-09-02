/**
 * How per-word timings follow segment edits. Timings are audio-absolute ms,
 * so a boundary move never rescales them: an edit only decides which words
 * still belong to which segment.
 *
 * - trim: keep the words fully inside the new span.
 * - split: each piece keeps the words fully inside it; a word straddling a
 *   cursor belongs to neither (it needs a realign).
 * - merge: concatenate in time order.
 * - reference edit / auto-fix: keep the words whose location is still inside
 *   the new ref; a Quran ref becoming a special (or vice versa) keeps none.
 *
 * `coverage` tells the row whether a realign is warranted: the ref's word
 * count versus the distinct ref locations the timings cover.
 */

import type { SegWordTiming } from '../../../../lib/types/generated/schemas';
import type { Ref } from '../../../../lib/types/view-models';
import { countSegWords, parseSegRef, type VerseWordCounts } from '../data/references';

export type WordTimings = SegWordTiming[] | null | undefined;

function _inside(w: SegWordTiming, startMs: number, endMs: number): boolean {
    return w.start_ms >= startMs && w.end_ms <= endMs;
}

/** Words fully inside `[startMs, endMs]`; `null` when none remain. */
export function clipWordTimings(words: WordTimings, startMs: number, endMs: number): SegWordTiming[] | null {
    if (!words?.length) return null;
    const kept = words.filter((w) => _inside(w, startMs, endMs));
    return kept.length ? kept : null;
}

/** One list per piece for the spans `[start, c0], [c0, c1], …, [cN-1, end]`. */
export function partitionWordTimings(
    words: WordTimings,
    startMs: number,
    endMs: number,
    cursors: readonly number[],
): (SegWordTiming[] | null)[] {
    const bounds = [startMs, ...cursors, endMs];
    const out: (SegWordTiming[] | null)[] = [];
    for (let i = 0; i + 1 < bounds.length; i++) {
        out.push(clipWordTimings(words, bounds[i]!, bounds[i + 1]!));
    }
    return out;
}

export function concatWordTimings(a: WordTimings, b: WordTimings): SegWordTiming[] | null {
    const all = [...(a ?? []), ...(b ?? [])];
    if (!all.length) return null;
    return all.sort((x, y) => x.start_ms - y.start_ms);
}

function _locationKey(location: string): [number, number, number] | null {
    const p = location.split(':').map(Number);
    if (p.length !== 3 || !p.every(Number.isFinite)) return null;
    return [p[0]!, p[1]!, p[2]!];
}

function _cmp(a: [number, number, number], b: [number, number, number]): number {
    return a[0] - b[0] || a[1] - b[1] || a[2] - b[2];
}

/** Words whose `location` falls inside `ref`; `null` when none (or when
 *  `ref` is not a Quran span). */
export function filterWordTimingsToRef(words: WordTimings, ref: Ref | null | undefined): SegWordTiming[] | null {
    if (!words?.length) return null;
    const p = parseSegRef(ref);
    if (!p) return null;
    const from: [number, number, number] = [p.surah, p.ayah_from, p.word_from];
    const to: [number, number, number] = [p.surah, p.ayah_to, p.word_to];
    const kept = words.filter((w) => {
        const key = _locationKey(w.location);
        return !!key && _cmp(key, from) >= 0 && _cmp(key, to) <= 0;
    });
    return kept.length ? kept : null;
}

export interface WordCoverage {
    expected: number;
    covered: number;
}

/** Ref word count vs distinct ref locations the timings cover. `expected`
 *  is 0 for non-Quran refs, so such segments never ask for a realign. */
export function wordCoverage(ref: Ref | null | undefined, words: WordTimings, vwc: VerseWordCounts | undefined): WordCoverage {
    const expected = countSegWords(ref, vwc);
    if (!expected) return { expected: 0, covered: 0 };
    const inRef = filterWordTimingsToRef(words, ref) ?? [];
    return { expected, covered: new Set(inRef.map((w) => w.location)).size };
}

export function needsRealign(ref: Ref | null | undefined, words: WordTimings, vwc: VerseWordCounts | undefined): boolean {
    const c = wordCoverage(ref, words, vwc);
    return c.expected > 0 && c.covered < c.expected;
}
