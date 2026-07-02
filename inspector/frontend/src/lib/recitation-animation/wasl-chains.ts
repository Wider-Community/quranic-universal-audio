/**
 * Cross-verse waṣl chains over reading-order units — the teleprompter's static
 * map of which verses recite into the next without a stop.
 *
 * A waṣl boundary bridges in any take ⇒ permanently chained (static; the rare
 * dynamic boundary is folded in). The flag rides the bridging take's last-word
 * occurrence as `TimeSpan.waslTo` (the target ayahKey). This precomputes, per
 * chapter, the chain each ayah belongs to so `LineAnimation` can extend a page
 * past a verse end instead of clearing — verse N+1's words flow onto the same
 * line as N's. A verse in no chain maps to itself ⇒ identical to non-waṣl
 * paging (v9 shards no-op).
 */

import { ayahUnitRanges } from './chapter-words';
import type { AnimUnit } from './types';

export interface WaslChains {
    /** ayahKey → the ayahKey that STARTS its chain (itself when not chained). */
    chainStartOf: Map<string, string>;
    /** chain-start ayahKey → exclusive end unit index of the whole chain. */
    chainEndIdxOf: Map<string, number>;
    /** ayahKeys that waṣl-bridge into the next reading-order verse. */
    bridgesNext: Set<string>;
}

/**
 * Build the chapter's waṣl chains from its reading-order units. A verse K
 * bridges into the next reading-order verse when K's last unit carries
 * `waslTo` pointing at it; a chain is a maximal run of such links.
 */
export function buildWaslChains(units: AnimUnit[]): WaslChains {
    const chainStartOf = new Map<string, string>();
    const chainEndIdxOf = new Map<string, number>();
    const bridgesNext = new Set<string>();

    const ranges = ayahUnitRanges(units); // reading-order Map<ayahKey,[start,end)>
    const keys = [...ranges.keys()];

    for (let i = 0; i < keys.length - 1; i++) {
        const k = keys[i]!;
        const next = keys[i + 1]!;
        const end = ranges.get(k)![1];
        const last = units[end - 1];
        if (last && last.intervals.some((iv) => iv.waslTo === next)) bridgesNext.add(k);
    }

    let i = 0;
    while (i < keys.length) {
        const start = keys[i]!;
        let j = i;
        while (j < keys.length - 1 && bridgesNext.has(keys[j]!)) j++;
        for (let m = i; m <= j; m++) chainStartOf.set(keys[m]!, start);
        chainEndIdxOf.set(start, ranges.get(keys[j]!)![1]);
        i = j + 1;
    }

    return { chainStartOf, chainEndIdxOf, bridgesNext };
}
