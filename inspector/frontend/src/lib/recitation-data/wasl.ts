/**
 * Cross-verse waṣl reconstruction — pure, shard-level helpers shared by the
 * dashboard surfaces (filmstrip / teleprompter) and the timestamps tab (analysis
 * + waveform). The pipeline stores a per-occurrence `wasl` flag on each take
 * (schema v10); `occasions.ts` already lifts it onto `ChapterOccasion.bridgesOutTo`.
 * This module turns that into junctions and group spans, per the contract in
 * `WASL_FE.md`.
 *
 * Naming guard: "bridge" is reserved for cross-word idgham elsewhere in the FE
 * (`PhonemeInterval.bridge`, `RenderedBridge`, `.pause-bridge`, …). Everything
 * here is `wasl*` to keep the two concepts distinct.
 */

import type { SegmentEntry } from '../types/ts-client';
import type { ChapterOccasion } from './occasions';

/** "surah:ayah" of a segment. */
export const verseOf = (s: SegmentEntry): string => s.ref;

/** A take bridges (cross-verse waṣl) iff its `wasl` flag is set and the next
 *  segment is a different verse. Per WASL_FE.md §reconstruction. */
export const isWaslBridge = (s: SegmentEntry, next?: SegmentEntry | null): boolean =>
    !!s.wasl && next != null && verseOf(next) !== verseOf(s);

/** Inclusive 1-based word range `[lo, hi]` of a take, from its first/last word
 *  rows. Empty take → `[0, 0]`. */
export function takeWordRange(seg: SegmentEntry): [number, number] {
    const ws = seg.words;
    if (!ws.length) return [0, 0];
    return [ws[0]![0], ws[ws.length - 1]![0]];
}

/** Partiality per WASL_FE.md §2: a take is partial when it starts mid-verse
 *  (`lo > 1`, trailing) or ends before the verse's last word (`hi < count`,
 *  leading). `verseWordCount` from `quranRefs.verse_word_counts`; 0/unknown ⇒
 *  only the trailing test applies. */
export function isPartialTake(words: readonly [number, number], verseWordCount: number): boolean {
    return words[0] > 1 || (verseWordCount > 0 && words[1] < verseWordCount);
}

/** One reconstructed cross-verse continuation (per take). */
export interface WaslJunction {
    fromRef: string;
    toRef: string;
    /** 1-based inclusive word range of the leaving take in `fromRef`. */
    fromWords: [number, number];
    /** 1-based inclusive word range of the entering take in `toRef`. */
    toWords: [number, number];
    /** Chapter-absolute ms: end of the leaving take, start of the entering take
     *  (≈equal for a true waṣl). */
    leaveMs: number;
    enterMs: number;
}

/**
 * Emit one junction per bridging occasion, in recitation order. Reuses the
 * back-stamped `bridgesOutTo` (the next occasion is always the bridge target,
 * since occasions split on ref change).
 */
export function chapterWaslJunctions(occasions: ChapterOccasion[]): WaslJunction[] {
    const out: WaslJunction[] = [];
    for (let i = 0; i < occasions.length - 1; i++) {
        const occ = occasions[i]!;
        if (!occ.bridgesOutTo) continue;
        const next = occasions[i + 1]!;
        const lastSeg = occ.segments[occ.segments.length - 1]!;
        const firstSeg = next.segments[0]!;
        out.push({
            fromRef: occ.ref,
            toRef: next.ref,
            fromWords: takeWordRange(lastSeg),
            toWords: takeWordRange(firstSeg),
            leaveMs: lastSeg.t[1],
            enterMs: firstSeg.t[0],
        });
    }
    return out;
}

/** The maximal run of occasions chained by `bridgesOutTo` that contains the
 *  focus occasion (by index), with its chapter-absolute span. A non-bridged
 *  focus returns just itself. */
export interface WaslGroup {
    /** Occasion indices [fromIdx, toIdx] inclusive (recitation order). */
    fromIdx: number;
    toIdx: number;
    /** Member verse refs in recitation order (e.g. ["20:25","20:26","20:27"]). */
    refs: string[];
    /** Chapter-absolute span covering every member occasion's segments. */
    startMs: number;
    endMs: number;
}

export function waslGroupOf(occasions: ChapterOccasion[], focusIdx: number): WaslGroup {
    let from = focusIdx;
    let to = focusIdx;
    // Expand left while the previous occasion bridges INTO this one.
    while (from > 0 && occasions[from - 1]!.bridgesOutTo === occasions[from]!.ref) from--;
    // Expand right while this occasion bridges OUT to the next.
    while (to < occasions.length - 1 && occasions[to]!.bridgesOutTo === occasions[to + 1]!.ref) to++;
    const refs: string[] = [];
    let startMs = Infinity;
    let endMs = -Infinity;
    for (let i = from; i <= to; i++) {
        const occ = occasions[i]!;
        refs.push(occ.ref);
        for (const seg of occ.segments) {
            if (seg.t[0] < startMs) startMs = seg.t[0];
            if (seg.t[1] > endMs) endMs = seg.t[1];
        }
    }
    return { fromIdx: from, toIdx: to, refs, startMs, endMs };
}

/** Whether the focus occasion participates in a cross-verse waṣl group (so the
 *  timestamps tab should context-merge + auto-span the waveform). */
export function isInWaslGroup(occasions: ChapterOccasion[], focusIdx: number): boolean {
    const occ = occasions[focusIdx];
    if (!occ) return false;
    if (occ.bridgesOutTo) return true;
    return focusIdx > 0 && occasions[focusIdx - 1]!.bridgesOutTo === occ.ref;
}
