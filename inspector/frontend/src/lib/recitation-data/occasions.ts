/**
 * Occasion splitting over shard readings and their original parts.
 *
 * Profile-independent: this only reads `reading.parts` and uses the reading as
 * an identity key, so a word-profile reading splits into occasions exactly like
 * a native one. Surfaces that need cells narrow with `isWordShard` first.
 */

import type { TsShardPart, TsShardReading, TsWordShardReading } from '../types/ts-client';

/** Either profile's reading — occasion splitting does not care which. */
export type AnyShardReading = TsShardReading | TsWordShardReading;

export interface OccasionReading {
    reading: AnyShardReading;
    parts: TsShardPart[];
}

export interface ChapterOccasion {
    ref: string;
    readings: OccasionReading[];
    parts: TsShardPart[];
    firstStartMs: number;
    waslOutTo: string | null;
}

interface IndexedPart {
    reading: AnyShardReading;
    part: TsShardPart;
    readingIndex: number;
}

function orderedParts(readings: AnyShardReading[]): IndexedPart[] {
    return readings.flatMap((reading, readingIndex) =>
        reading.parts.map((part) => ({ reading, part, readingIndex })),
    ).sort((a, b) => a.part.t[0] - b.part.t[0] || a.readingIndex - b.readingIndex);
}

function append(occasion: ChapterOccasion, entry: IndexedPart): void {
    occasion.parts.push(entry.part);
    const current = occasion.readings.at(-1);
    if (current?.reading === entry.reading) current.parts.push(entry.part);
    else occasion.readings.push({ reading: entry.reading, parts: [entry.part] });
}

export function chapterOccasions(readings: AnyShardReading[]): ChapterOccasion[] {
    const occasions: ChapterOccasion[] = [];
    let previous: IndexedPart | null = null;
    for (const entry of orderedParts(readings)) {
        const current = occasions.at(-1);
        if (current?.ref === entry.part.ref) {
            append(current, entry);
        } else {
            if (current && previous?.reading === entry.reading) {
                current.waslOutTo = entry.part.ref;
            }
            const next: ChapterOccasion = {
                ref: entry.part.ref,
                readings: [],
                parts: [],
                firstStartMs: entry.part.t[0],
                waslOutTo: null,
            };
            append(next, entry);
            occasions.push(next);
        }
        previous = entry;
    }
    return occasions;
}
