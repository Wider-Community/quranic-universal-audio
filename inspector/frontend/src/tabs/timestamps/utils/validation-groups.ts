import type { TsValidationDoc, TsValidationVerse } from '../../../lib/types/generated/schemas';

export interface TsValidationBeamGroup {
    beam: number;
    refs: string[];
}

function isFiniteBeam(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

/** Numeric surah:ayah[:word...] compare so 2:7 sorts before 2:10. */
export function cmpVerseRef(a: string, b: string): number {
    const pa = a.split(/[:-]/).map((n) => parseInt(n, 10) || 0);
    const pb = b.split(/[:-]/).map((n) => parseInt(n, 10) || 0);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
        const d = (pa[i] ?? 0) - (pb[i] ?? 0);
        if (d) return d;
    }
    return 0;
}

function failedBeams(flag: TsValidationVerse | undefined): number[] {
    return (flag?.failed_beams ?? []).filter(isFiniteBeam);
}

function uniqueDesc(values: number[]): number[] {
    return [...new Set(values)].sort((a, b) => b - a);
}

export function groupTsValidationVerses(doc: TsValidationDoc | null): TsValidationBeamGroup[] {
    const verses = doc?.verses ?? {};
    const allFailed = Object.values(verses).flatMap((flag) => failedBeams(flag));
    const metaBeams = uniqueDesc((doc?._meta?.beams ?? []).filter(isFiniteBeam));
    const orderedBeams = uniqueDesc([...metaBeams, ...allFailed]);
    const groups = new Map(orderedBeams.map((beam) => [beam, [] as string[]]));

    for (const [ref, flag] of Object.entries(verses).sort(([a], [b]) => cmpVerseRef(a, b))) {
        const failed = failedBeams(flag);
        if (failed.length === 0) continue;
        const highestFailed = Math.max(...failed);
        const refs = groups.get(highestFailed);
        if (refs) refs.push(ref);
    }

    return orderedBeams
        .map((beam) => ({ beam, refs: groups.get(beam) ?? [] }))
        .filter((group) => group.refs.length > 0);
}
