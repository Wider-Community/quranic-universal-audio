import type { SelectOption } from '../types/ui';

/** Minimum reciter shape required by this helper. */
export interface ReciterLike {
    slug?: string;
    name: string;
    audio_source?: string;
}

/** One group of reciters sharing an audio_source value. */
export interface GroupedReciters<T extends ReciterLike = ReciterLike> {
    group: string;
    items: T[];
}

/**
 * Build a sorted grouped-reciter list from a flat reciter array.
 *
 * @param reciters - flat list of reciter objects (any shape with audio_source + name)
 * @returns array of groups, sorted by source name; uncategorized appended last
 */
export function buildGroupedReciters<T extends ReciterLike>(reciters: T[]): GroupedReciters<T>[] {
    const grouped: Record<string, T[]> = {};
    const uncategorized: T[] = [];

    for (const r of reciters) {
        const src = r.audio_source || '';
        if (src) {
            if (!grouped[src]) grouped[src] = [];
            grouped[src]!.push(r);
        } else {
            uncategorized.push(r);
        }
    }

    const out: GroupedReciters<T>[] = [];
    for (const src of Object.keys(grouped).sort()) {
        out.push({ group: src, items: grouped[src] ?? [] });
    }
    if (uncategorized.length > 0) {
        out.push({ group: '(uncategorized)', items: uncategorized });
    }
    return out;
}

/** Convert grouped reciter list to flat SelectOption[] for SearchableSelect. */
export function reciterGroupsToOptions<T extends ReciterLike>(
    groups: GroupedReciters<T>[],
): SelectOption[] {
    return groups.flatMap((g) =>
        g.items.map((r) => ({
            value: r.slug ?? r.name,
            label: r.name,
            group: g.group,
        })),
    );
}
