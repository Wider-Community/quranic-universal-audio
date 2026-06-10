/**
 * Chapter-level word assembly for the full-chapter player.
 *
 * The timestamps tab plays per-verse clips, so `assembleVerseFromShard()`
 * zeroes each verse's words against its own start (`time_start_ms`). The
 * dashboard plays the WHOLE chapter file, so the animation needs
 * chapter-absolute times. We recover them by adding each verse's
 * `time_start_ms` back onto its words — i.e. this is the inverse of the
 * per-verse offset the assembler applied.
 *
 * Pure transform: takes already-assembled `TsVerseData` (one per verse ref)
 * and emits flat `AnimUnit[]` + per-ayah boundaries. No data-fetch / tab
 * imports — the caller (playground, dashboard) owns the shard fetch.
 *
 * Time-base caveat: this is correct for `by_surah` reciters (one chapter file
 * shared by every verse). `by_ayah` reciters have per-verse audio files whose
 * concatenation offset isn't known here, so the dashboard guards them out
 * before calling this. See the plan's scope guard.
 */

import type { OccasionInterval } from '../recitation-data/ts-source';
import type { TsVerseData } from '../types/ts-client';
import type { AnimUnit, AyahBoundary, ChapterRecitation } from './types';

export interface AssembledVerse {
    verseRef: string;
    data: TsVerseData;
}

function parseLocation(location: string): { surah: number; ayah: number; word: number } {
    const [s, a, w] = location.split(':');
    return {
        surah: parseInt(s ?? '0', 10),
        ayah: parseInt(a ?? '0', 10),
        word: parseInt(w ?? '0', 10),
    };
}

/**
 * Build chapter-absolute recitation data from assembled verses.
 *
 * Geometry + text come from each verse's CANONICAL occasion (the assembled
 * `verses`). `occasionIntervals` supplies the recited span of EVERY occasion
 * (canonical + loopbacks / re-dos) keyed by location, chapter-absolute; those
 * spans are folded onto each word's `intervals` so the recitation locator
 * covers the whole audio timeline (the highlight travels back into a re-recited
 * verse instead of freezing on the canonical-only span). The canonical occasion
 * is the earliest pass, so `intervals[0]` stays the canonical span after the
 * ascending sort — preserving cell geometry + letter-timeline anchoring.
 *
 * @param reciter          slug
 * @param chapter          1-based surah number
 * @param verses           assembled verses (any order; sorted internally by abs start)
 * @param occasionIntervals every occasion's word spans (chapter-absolute, seconds);
 *                          empty array = canonical-only (geometry unchanged either way)
 */
export function buildChapterRecitation(
    reciter: string,
    chapter: number,
    verses: AssembledVerse[],
    occasionIntervals: OccasionInterval[] = [],
): ChapterRecitation {
    const units: AnimUnit[] = [];

    for (const { data } of verses) {
        // The per-verse offset the assembler subtracted (0 for by_ayah).
        const offsetSec = data.time_start_ms / 1000;
        for (const w of data.words) {
            const { surah, ayah, word } = parseLocation(w.location);
            const start = w.start + offsetSec;
            const end = w.end + offsetSec;
            units.push({
                location: w.location,
                ayahKey: `${surah}:${ayah}`,
                surah,
                ayah,
                word,
                text: w.display_text || w.text,
                start,
                end,
                intervals: [{ start, end }],
                letters: w.letters.map((lt) => ({
                    char: lt.char,
                    start: lt.start === null ? null : lt.start + offsetSec,
                    end: lt.end === null ? null : lt.end + offsetSec,
                })),
            });
        }
    }

    // Collapse repeats by INDEX (location = "surah:ayah:word"), not by text — a
    // reciter who repeats / goes back re-emits the same word index in the TS
    // file with a new time span. Each canonical word is rendered once (reading
    // order); every occurrence's span is kept on `intervals` so the highlight
    // can travel back and re-light it instead of duplicating the text.
    const byLoc = new Map<string, AnimUnit>();
    for (const u of units) {
        const existing = byLoc.get(u.location);
        if (existing) {
            existing.intervals.push({ start: u.start, end: u.end });
            if (u.start < existing.start) existing.start = u.start;
            if (u.end > existing.end) existing.end = u.end;
        } else {
            byLoc.set(u.location, u);
        }
    }

    // Fold every occasion's recited span onto its word so the recitation locator
    // covers the dropped re-takes the canonical occasion discarded. Only words
    // that already have a canonical unit get extra spans (a re-take never adds a
    // new word index). Near-identical spans (the canonical occasion is also in
    // `occasionIntervals`) are deduped so the canonical interval isn't doubled.
    const SPAN_EPS = 0.0005; // 0.5ms — sub-frame; collapses the canonical dupe
    for (const oi of occasionIntervals) {
        const unit = byLoc.get(oi.location);
        if (!unit) continue;
        const dup = unit.intervals.some(
            (iv) => Math.abs(iv.start - oi.start) < SPAN_EPS && Math.abs(iv.end - oi.end) < SPAN_EPS,
        );
        if (dup) continue;
        unit.intervals.push({ start: oi.start, end: oi.end });
        if (oi.start < unit.start) unit.start = oi.start;
        if (oi.end > unit.end) unit.end = oi.end;
    }

    const deduped = [...byLoc.values()].sort(
        (a, b) => a.surah - b.surah || a.ayah - b.ayah || a.word - b.word,
    );
    for (const u of deduped) u.intervals.sort((a, b) => a.start - b.start);

    // Per-ayah boundaries, in reading order.
    const ayahs: AyahBoundary[] = [];
    const byKey = new Map<string, AyahBoundary>();
    for (const u of deduped) {
        const startMs = Math.round(u.start * 1000);
        const endMs = Math.round(u.end * 1000);
        const existing = byKey.get(u.ayahKey);
        if (!existing) {
            const b: AyahBoundary = {
                ayahKey: u.ayahKey,
                surah: u.surah,
                ayah: u.ayah,
                startMs,
                endMs,
            };
            byKey.set(u.ayahKey, b);
            ayahs.push(b);
        } else {
            if (startMs < existing.startMs) existing.startMs = startMs;
            if (endMs > existing.endMs) existing.endMs = endMs;
        }
    }
    ayahs.sort((a, b) => a.startMs - b.startMs);

    const contentEndMs = deduped.length
        ? Math.round(Math.max(...deduped.map((u) => u.end)) * 1000)
        : 0;

    return { reciter, chapter, units: deduped, ayahs, contentEndMs };
}

/** Inclusive [start, end) unit index range for each ayah, keyed by ayahKey.
 *  Assumes `units` is in playback order (as produced above) and each ayah's
 *  units are contiguous — true for sequential recitation. */
export function ayahUnitRanges(units: AnimUnit[]): Map<string, [number, number]> {
    const ranges = new Map<string, [number, number]>();
    for (let i = 0; i < units.length; i++) {
        const key = units[i]!.ayahKey;
        const r = ranges.get(key);
        if (!r) ranges.set(key, [i, i + 1]);
        else r[1] = i + 1;
    }
    return ranges;
}
