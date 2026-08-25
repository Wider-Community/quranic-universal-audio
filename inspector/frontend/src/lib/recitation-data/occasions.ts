/** Occasion splitting over native v12 readings and their original parts. */

import type { TsShardPart, TsShardReading } from '../types/ts-client';

export interface OccasionReading {
    reading: TsShardReading;
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
    reading: TsShardReading;
    part: TsShardPart;
    readingIndex: number;
}

function orderedParts(readings: TsShardReading[]): IndexedPart[] {
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

export function chapterOccasions(readings: TsShardReading[]): ChapterOccasion[] {
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
