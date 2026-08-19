/**
 * Pure phoneme-row layout for the Timestamps analysis view — splits phones into
 * base + IPA-modifier and assigns each phoneme span to its source grapheme
 * columns (`_buildColumns`).
 * Consumed by `rendered-blocks.ts`; see `cell-model.ts` for the group model.
 */

import type { PhonemeSpan, RenderedGroup, RenderedPhoneme } from './cell-model';


/** Split a phone string into base character(s) and trailing IPA modifiers
 *  (length ː, emphatic ˤ, ghunnah tilde ̃). The modifier is rendered as a
 *  superscript so the base stays visually centred in the cell. */
// Only length marks (ː / ASCII :) are detached modifiers; ˤ is integral to
// the consonant symbol (rˤ, dˤ, sˤ, tˤ, ðˤ) and must stay in the base.
export const PHONE_MOD_RE = /([ː:]+)$/u;
export function splitPhone(phone: string | undefined): { base: string; mod: string } {
    if (!phone || phone === 'sil' || phone === 'sp') return { base: phone ?? '', mod: '' };
    const m = PHONE_MOD_RE.exec(phone);
    return m ? { base: phone.slice(0, -m[0].length), mod: m[0] } : { base: phone, mod: '' };
}

/** Assign each rendered phoneme to the grapheme COLUMN(s) that sound it, then
 *  pack the phonemes into row-2 clusters that SPAN those columns. So a phoneme
 *  sits beneath the grapheme(s) it belongs to:
 *   - 1 grapheme : 1 sound  → its own column (the cluster fills it; edges shared);
 *   - many graphemes : 1 sound (long vowel, share-group) → the cluster spans the
 *     unit's columns and centres across them (not pinned under one sub-column);
 *   - 1 grapheme : many sounds → the cluster stays in the single column, which
 *     widens to fit.
 *  A silent grapheme indexes nothing → empty slot. A render-only phone no cell
 *  indexes (qalqala echo `Q`) rides the preceding phoneme's columns. */
export function _buildColumns(groups: RenderedGroup[], phonemes: RenderedPhoneme[]): void {
    if (!groups.length) return;
    // phoneme index → owning group + the COLUMN SET that sounds it (a cell's own
    // columns, widened to every column sharing that cell's share-group so a long
    // vowel's lone phone spans both [diacritic, carrier] columns).
    const owner = new Map<number, { g: RenderedGroup; cols: Set<number> }>();
    for (const g of groups) {
        // Vowel group order: [live diacritic(s), carrier, …trailing silent drop].
        // A و/ى waqf carrier's OWN dropped fatḥa renders AFTER the carrier (its
        // glyph order in the word), outside the vowel sound — every other diacritic
        // precedes the carrier as usual. A FULLY-silent vowel group (dropped ṣilah at
        // waqf: ḍamma/kasra + mini-waw/yaa, both silent) is the exception: its
        // ḥaraka leads its carrier (orthographic هُ + ۥ), so the dropped diacritic
        // does NOT trail.
        const liveSmalls = g.small.filter((s) => s.status !== 'dropped');
        const droppedSmalls = g.small.filter((s) => s.status === 'dropped');
        const silentVowel = g.kind === 'vowel' && g.full.length > 0 && g.full.every((f) => f.silent);
        g.cols = g.kind !== 'vowel'
            ? [...g.full.map((f) => ({ full: f, small: null })), ...g.small.map((s) => ({ full: null, small: s }))]
            : silentVowel
              ? [
                    ...g.small.map((s) => ({ full: null, small: s })),
                    ...g.full.map((f) => ({ full: f, small: null })),
                ]
              : [
                    ...liveSmalls.map((s) => ({ full: null, small: s })),
                    ...g.full.map((f) => ({ full: f, small: null })),
                    ...droppedSmalls.map((s) => ({ full: null, small: s })),
                ];
        g.phonemeSpans = [];
        const sgCols = new Map<number, Set<number>>();
        g.cols.forEach((col, ci) => {
            const sg = col.full?.shareGroup ?? col.small?.shareGroup ?? null;
            if (sg == null) return;
            let s = sgCols.get(sg);
            if (!s) { s = new Set(); sgCols.set(sg, s); }
            s.add(ci);
        });
        g.cols.forEach((col, ci) => {
            const sg = col.full?.shareGroup ?? col.small?.shareGroup ?? null;
            const cols = sg != null ? sgCols.get(sg)! : new Set([ci]);
            for (const idx of col.full?.phoneIdx ?? col.small?.phoneIdx ?? []) {
                if (!owner.has(idx)) owner.set(idx, { g, cols });
            }
        });
    }
    // Walk phonemes in reading order, merging into a cluster while the column
    // range overlaps the open one (1:many stays one cluster in one column; an
    // unowned phone rides the open cluster). A range change opens a new cluster.
    const acc = new Map<RenderedGroup, PhonemeSpan[]>();
    let cur: { g: RenderedGroup; lo: number; hi: number; span: PhonemeSpan } | null = null;
    for (const p of phonemes) {
        const found = owner.get(p.index);
        const g: RenderedGroup = found?.g ?? cur?.g ?? groups[0]!;
        const lo: number = found ? Math.min(...found.cols) : (cur?.lo ?? 0);
        const hi: number = found ? Math.max(...found.cols) : (cur?.hi ?? 0);
        if (cur && cur.g === g && lo <= cur.hi && hi >= cur.lo) {
            cur.span.phonemes.push(p);
            cur.lo = Math.min(cur.lo, lo);
            cur.hi = Math.max(cur.hi, hi);
            cur.span.colStart = cur.lo;
            cur.span.span = cur.hi - cur.lo + 1;
        } else {
            const span: PhonemeSpan = { phonemes: [p], colStart: lo, span: hi - lo + 1 };
            let spans = acc.get(g);
            if (!spans) acc.set(g, (spans = []));
            spans.push(span);
            cur = { g, lo, hi, span };
        }
    }
    for (const [g, spans] of acc) g.phonemeSpans = spans;

    // A vowel unit is one co-lit sound across its whole group ([diacritic,
    // carrier], implicit/ʿiwaḍ madd, dagger-Allah). Collapse its per-column
    // clusters into ONE cluster spanning every column, centred — so a normal
    // madd, madd-ʿiwaḍ, the Allah dagger-alef and the inserted ʿiwaḍ alef all
    // share the group's full width identically (same sound → same width),
    // regardless of whether they co-light via share-group or interval.
    for (const g of groups) {
        if (g.kind !== 'vowel' || g.phonemeSpans.length === 0) continue;
        const phonemes = g.phonemeSpans.flatMap((s) => s.phonemes);
        // The sound spans [diacritic, carrier] only; a trailing silent drop (a
        // و/ى waqf carrier's dropped fatḥa) sits past the carrier, outside the span.
        const silentTail = g.cols.filter((c) => c.small?.status === 'dropped').length;
        g.phonemeSpans = [{ phonemes, colStart: 0, span: g.cols.length - silentTail }];
    }
}
