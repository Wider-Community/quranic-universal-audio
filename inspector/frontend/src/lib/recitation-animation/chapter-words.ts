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

import type { TsVerseData } from '../types/domain';
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
 * @param reciter slug
 * @param chapter 1-based surah number
 * @param verses  assembled verses (any order; sorted internally by abs start)
 */
export function buildChapterRecitation(
    reciter: string,
    chapter: number,
    verses: AssembledVerse[],
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
                letters: w.letters.map((lt) => ({
                    char: lt.char,
                    start: lt.start === null ? null : lt.start + offsetSec,
                    end: lt.end === null ? null : lt.end + offsetSec,
                })),
            });
        }
    }

    // Chapter-absolute order. Stable on (start, then location word index).
    units.sort((a, b) => (a.start - b.start) || (a.word - b.word));

    // Per-ayah boundaries, in playback order.
    const ayahs: AyahBoundary[] = [];
    const byKey = new Map<string, AyahBoundary>();
    for (const u of units) {
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

    const contentEndMs = units.length
        ? Math.round(Math.max(...units.map((u) => u.end)) * 1000)
        : 0;

    return { reciter, chapter, units, ayahs, contentEndMs };
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
