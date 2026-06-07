import { describe, expect, it } from 'vitest';

import {
    buildChapterRecitation,
    type AssembledVerse,
} from '../../recitation-animation/chapter-words';
import { buildSortedIntervals, findActiveAt } from '../../recitation-animation/recitation-active';
import type { AnimUnit } from '../../recitation-animation/types';
import type { SegmentEntry, TsShardResponse } from '../../types/api';
import {
    assembleVerseFromShard,
    chapterOccasionIntervals,
    chapterVerseRefs,
    type TsReciterAudio,
} from '../ts-source';

import shard101 from './fixtures/nasser_al_qatami_mp3quran_101.shard.json';
import shard102 from './fixtures/nasser_al_qatami_mp3quran_102.shard.json';

/**
 * Real-data regression for the #143 freeze: the dashboard / Timestamps recited
 * filmstrip + line froze while audio played a DISCARDED re-take, because the
 * chapter units carried only each verse's canonical occasion. The full-chapter
 * audio plays EVERY take, so `findActiveAt` returned null across the dropped
 * spans → permanent-feeling freeze.
 *
 * These fixtures are the actual published prod shards for nasser_al_qatami
 * chapters 101 + 102 (every verse re-recited 2-3×). The assertions drive the
 * REAL assembly pipeline (`assembleVerseFromShard` + `chapterOccasionIntervals`
 * + `buildChapterRecitation`) — synthetic units passed before yet shipped broken.
 */

const RECITER = 'nasser_al_qatami_mp3quran';
const RECITER_AUDIO: TsReciterAudio = { audio_category: 'by_surah' };
// qpc/dk only supply display text; timing + intervals come from the shard, so
// empty maps are sufficient for a coverage test.
const EMPTY_TEXT: Record<string, { text?: string }> = {};

interface Built {
    units: AnimUnit[];
    contentEndMs: number;
}

/** Run the real pipeline. `withOccasions=false` reproduces the OLD canonical-
 *  only build (the regression) by withholding the occasion intervals. */
function build(shard: TsShardResponse, chapter: number, withOccasions: boolean): Built {
    const verses: AssembledVerse[] = [];
    for (const ref of chapterVerseRefs(shard)) {
        const data = assembleVerseFromShard(RECITER, shard, ref, EMPTY_TEXT, EMPTY_TEXT, RECITER_AUDIO, '');
        if (data) verses.push({ verseRef: ref, data });
    }
    const occ = withOccasions ? chapterOccasionIntervals(shard) : [];
    const r = buildChapterRecitation(RECITER, chapter, verses, occ);
    return { units: r.units, contentEndMs: r.contentEndMs };
}

/** Real inter-segment silence gaps (chapter-absolute seconds) from the shard —
 *  the only places the recited highlight is SUPPOSED to go null. Computed off
 *  the raw segment `t` spans, independent of the build under test. */
function silenceGaps(shard: TsShardResponse): Array<[number, number]> {
    const segs = [...shard.segments].sort((a: SegmentEntry, b: SegmentEntry) => a.t[0] - b.t[0]);
    const gaps: Array<[number, number]> = [];
    let prevEnd = -1;
    for (const s of segs) {
        const [a, b] = s.t;
        if (prevEnd >= 0 && a > prevEnd) gaps.push([prevEnd / 1000, a / 1000]);
        prevEnd = Math.max(prevEnd, b);
    }
    return gaps;
}

/** True when `tSec` lies at least `tol` INSIDE some word span — i.e. the audio
 *  is unambiguously reciting a word (not at a sub-frame interval boundary). The
 *  complement is real silence (segment lead-in / trailing tails + inter-word
 *  micro-gaps), where the highlight is meant to be null (the assembler plays
 *  through silence with nothing highlighted). The inset avoids flagging exact
 *  word-end points, which are null under the half-open `[start,end)` match. */
function deepInsideWord(tSec: number, wordSpans: Array<[number, number]>, tol: number): boolean {
    for (const [a, b] of wordSpans) {
        if (b - a > 2 * tol && tSec >= a + tol && tSec <= b - tol) return true;
    }
    return false;
}

/** Every word span (seconds) across ALL occasions — ground truth for "is the
 *  audio reciting a word here", independent of the build under test. */
function allWordSpans(shard: TsShardResponse): Array<[number, number]> {
    const out: Array<[number, number]> = [];
    for (const s of shard.segments) {
        for (const w of s.words) out.push([w[1] / 1000, w[2] / 1000]);
    }
    return out;
}

const CASES: Array<[string, TsShardResponse, number]> = [
    ['101', shard101 as unknown as TsShardResponse, 101],
    ['102', shard102 as unknown as TsShardResponse, 102],
];

describe('occasion coverage (real nasser_al_qatami shards)', () => {
    for (const [label, shard, chapter] of CASES) {
        describe(`chapter ${label}`, () => {
            it('the canonical-only build (old behaviour) leaves the audio uncovered across re-takes', () => {
                const { units, contentEndMs } = build(shard, chapter, false);
                const sorted = buildSortedIntervals(units);
                const wordSpans = allWordSpans(shard);

                // Sample over a re-take span (audio is reciting a word) and count
                // how many sampled points the OLD build fails to resolve.
                let recitingPoints = 0;
                let nullPoints = 0;
                for (let ms = 0; ms <= contentEndMs; ms += 50) {
                    const tSec = ms / 1000;
                    const reciting = wordSpans.some(([a, b]) => tSec >= a && tSec < b);
                    if (!reciting) continue;
                    recitingPoints++;
                    if (!findActiveAt(units, sorted, tSec, -1)) nullPoints++;
                }
                // Many actively-recited points are uncovered — the freeze.
                expect(recitingPoints).toBeGreaterThan(0);
                expect(nullPoints).toBeGreaterThan(20);
            });

            it('the full-occasion build covers every actively-recited point (no freeze)', () => {
                const { units, contentEndMs } = build(shard, chapter, true);
                const sorted = buildSortedIntervals(units);
                const wordSpans = allWordSpans(shard);

                const uncovered: number[] = [];
                for (let ms = 0; ms <= contentEndMs; ms += 50) {
                    const tSec = ms / 1000;
                    const reciting = wordSpans.some(([a, b]) => tSec >= a && tSec < b);
                    if (!reciting) continue;
                    if (!findActiveAt(units, sorted, tSec, -1)) uncovered.push(ms);
                }
                // EVERY point where the audio is reciting a word now resolves a
                // unit — the highlight travels into the re-take instead of freezing.
                expect(uncovered).toEqual([]);
            });

            it('every null point is a genuine silence (no word is being recited there)', () => {
                const { units, contentEndMs } = build(shard, chapter, true);
                const sorted = buildSortedIntervals(units);
                const wordSpans = allWordSpans(shard);
                const tol = 0.04; // 40ms — a sub-frame boundary slop

                // A REAL inter-take silence (the dataset's lead-in / trailing
                // tails) must still freeze: every null point must fall where no
                // word of any occasion is playing.
                const unexpectedNulls: number[] = [];
                for (let ms = 0; ms <= contentEndMs; ms += 25) {
                    const tSec = ms / 1000;
                    if (findActiveAt(units, sorted, tSec, -1)) continue; // covered
                    if (deepInsideWord(tSec, wordSpans, tol)) unexpectedNulls.push(ms);
                }
                expect(unexpectedNulls).toEqual([]);

                // And at least one genuine silence span exists + correctly freezes
                // (so the test isn't vacuously green on a fully-covered timeline).
                const gaps = silenceGaps(shard);
                expect(gaps.length).toBeGreaterThan(0);
                const [gA, gB] = gaps[0]!;
                const midGap = (gA + gB) / 2;
                if (gB - gA > 2 * tol) {
                    expect(findActiveAt(units, sorted, midGap, -1)).toBeNull();
                }
            });

            it('the active unit travels back into a re-recited verse during a dropped take', () => {
                const { units } = build(shard, chapter, true);
                const sorted = buildSortedIntervals(units);

                // For each verse with >1 occasion, sample inside a NON-canonical
                // occasion and assert the resolved unit belongs to that verse —
                // i.e. the highlight is on the re-take, not frozen elsewhere.
                const occByRef = new Map<string, Array<[number, number]>>();
                for (const s of shard.segments) {
                    const list = occByRef.get(s.ref) ?? [];
                    list.push([s.t[0], s.t[1]]);
                    occByRef.set(s.ref, list);
                }

                let checked = 0;
                for (const [ref, spans] of occByRef) {
                    if (spans.length < 2) continue;
                    spans.sort((a, b) => a[0] - b[0]);
                    // A later occasion (the re-take) — sample its temporal middle.
                    const [a, b] = spans[spans.length - 1]!;
                    const midSec = (a + b) / 2 / 1000;
                    const hit = findActiveAt(units, sorted, midSec, -1);
                    expect(hit, `${ref} re-take @${midSec}s must resolve a unit`).not.toBeNull();
                    const u = units[hit!.unitIdx]!;
                    expect(u.ayahKey).toBe(ref);
                    checked++;
                }
                expect(checked).toBeGreaterThan(0);
            });

            it('canonical geometry is preserved: intervals[0] is the earliest (canonical) span', () => {
                const { units } = build(shard, chapter, true);
                for (const u of units) {
                    // intervals are sorted ascending; the first is the canonical
                    // first-occurrence the cell geometry + letter timelines anchor on.
                    for (let i = 1; i < u.intervals.length; i++) {
                        expect(u.intervals[i]!.start).toBeGreaterThanOrEqual(u.intervals[i - 1]!.start);
                    }
                    // A repeated word carries >1 interval (full coverage), a
                    // once-said word exactly 1.
                    expect(u.intervals.length).toBeGreaterThanOrEqual(1);
                }
            });
        });
    }
});
