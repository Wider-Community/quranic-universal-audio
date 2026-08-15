/**
 * Pure data-derivation for the Timestamps analysis view — the cell/group model.
 *
 * Turns a word's positional cells (+ verse intervals + cross-word share/idgham
 * context) into `RenderedGroup[]`: per-grapheme full cells, their small diacritic
 * cells, timing, tajweed badges and silent-rule names. State-free and DOM-free —
 * `UnifiedDisplay.svelte` owns only the reactive glue, imperative highlight and
 * template; the unit tests exercise this module's output through that component.
 */

import { ALEF_MAKSURA, DAGGER, FATHA, MEEM_HI, MEEM_LO, OPEN_TANWEEN, OPEN_TANWEEN_TAGS, SUKUN, cellGlyph, cellSlot, firstMark, implicitMaddGlyph } from './tajweed-script';
import { badgesForTags, silentTooltip, tagsForLegend } from './tajweed-rules';
import type { TjBadge } from './tajweed-rules';
import { foldRidingMarks, iqlabMiniMeem, iqlabNoonSilentBase, iqlabTanweenVowel, isIqlabCell } from './cell-special-cases';
import { harakaRenderStyle } from './haraka-render';
import type { PhonemeInterval, TsCell, TsWord } from '../../../lib/types/ts-client';


export interface RenderedFull {
    glyph: string;
    silent: boolean;
    status: string;
    /** The cell's own producer rules, in producer order. */
    rules: string[];
    /** Implicit madd (chars==='') — rendered with the inserted/replaced glow. */
    implicit: boolean;
    /** A written-but-"added" full cell (the madd-ʿiwaḍ alef substituted for the
     *  fatḥatan at waqf) — carries the muted dashed inserted border, like the
     *  implicit madd, without being implicit. */
    inserted: boolean;
    /** True for a `base` cell (the interactive letter target). */
    isBase: boolean;
    /** Highlight interval from the cell's own phoneme indices (+share union). */
    cellStart: number | null;
    cellEnd: number | null;
    /** The LETTER's full [start,end] for click/dblclick/hover/loop. */
    letterStart: number | null;
    letterEnd: number | null;
    /** Untimed letter (no per-letter timing) → never highlighted, inert. */
    isNull: boolean;
    /** Rendered-letter index this base cell maps to (loop-highlight identity). */
    letterIndex: number;
    /** Index into the raw `word.cells[]` (the report target's `cell_index`);
     *  -1 for synthesized cells with no raw source. */
    cellIndex: number;
    /** Internal tajweed tag id(s) on the cell — the report rule-picker's options,
     *  keyed by the data-model tag not a label. */
    ruleTags: string[];
    shareGroup: number | null;
    /** Flat interval indices this cell sounds — placed under its own column. */
    phoneIdx: number[];
    /** Ordered tajweed underline badges (bottom→top, tafkheem on top) — composed
     *  into a box-shadow at render, filtered by the live enable set. */
    tjBadges: TjBadge[];
    /** Silent-rule hover names (no underline) shown in the cell tooltip. */
    silentRules: string[];
}

/** A SMALL diacritic cell — haraka / tanween / an iqlab tanwīn's own mini-meem
 *  cell / inserted graphemeless vowels. Pins top or bottom of the group's
 *  letter row. Sukūn cells are filtered out upstream and never become one. */
export interface RenderedSmall {
    /** The combining mark to render — a single haraka/tanwīn or mini-meem. */
    glyph: string;
    slot: 'top' | 'bottom';
    status: string;
    /** The cell's own producer rules, in producer order. */
    rules: string[];
    cellStart: number | null;
    cellEnd: number | null;
    shareGroup: number | null;
    /** Index into the raw `word.cells[]` (the report target's `cell_index`);
     *  -1 for synthesized cells with no raw source. */
    cellIndex: number;
    /** Internal tajweed tag id(s) on the cell — the report rule-picker's options. */
    ruleTags: string[];
    /** Per-glyph centring style string (`--haraka-*`). */
    renderStyle: string;
    /** A `status==='inserted'` vowel not in the rasm (hamza-waṣl / iltiqaa
     *  connecting kasra, or the started-on ٱئْتُونِى helping kasra) — draws the
     *  muted dashed "added, not written" border regardless of glyph. */
    inserted: boolean;
    /** Flat interval indices this cell sounds — placed under its own column. */
    phoneIdx: number[];
    /** Ordered tajweed underline badges (bottom→top, tafkheem on top). */
    tjBadges: TjBadge[];
    /** Silent-rule hover names (no underline) shown in the cell tooltip. */
    silentRules: string[];
}

/** A rendered cell-group. `kind` drives the in-row order:
 *  - `base`  : a consonant (+ its short haraka/tanwīn) → full THEN small.
 *  - `vowel` : a long-vowel unit [diacritic + carrier] (base lives in its own
 *    separate group) or a standalone/implicit madd → small THEN full, so the
 *    diacritic precedes the vowel grapheme it pairs with.
 *  Gap 0 within a group, non-zero between groups. */
/** One grapheme's column within a group: the row-1 cell (a full letter OR a
 *  small diacritic) whose phonemes render directly beneath it in row 2. */
export interface GraphemeColumn {
    full: RenderedFull | null;
    small: RenderedSmall | null;
}

/** A row-2 phoneme placement: the phonemes sounding under column `colStart`,
 *  spanning `span` columns when adjacent graphemes share one sound. */
export interface PhonemeSpan {
    phonemes: RenderedPhoneme[];
    colStart: number;
    span: number;
}

export interface RenderedGroup {
    kind: 'base' | 'vowel';
    full: RenderedFull[];
    small: RenderedSmall[];
    shareGroup: number | null;
    /** Ordered grapheme columns (reading order) — the group's row-1 cells. */
    cols: GraphemeColumn[];
    /** Row-2 phoneme placements, each aligned under its source grapheme so a
     *  silent grapheme leaves an empty slot and a vowel sits under its mark. */
    phonemeSpans: PhonemeSpan[];
}

/** The folded letter view of `word.letters` — one entry per rendered letter
 *  (the ىٰ fold collapses two source letters into one), each carrying the
 *  glyph + per-letter timing + silent flag a `base` cell reads from. */
export interface FoldedLetter {
    glyph: string;
    silent: boolean;
    start: number | null;
    end: number | null;
    isNull: boolean;
    srcIndices: number[];
}

export interface RenderedPhoneme {
    interval: PhonemeInterval;
    /** Flat interval index (for highlight matching + click seek). */
    index: number;
    /** Word-local indexable-phone index (render-only Q + geminate_end skipped) —
     *  the `phoneme_flat_index` a report target keys on. */
    wordLocalIndex: number;
    /** Ordered tajweed underline badges (bottom→top, tafkheem on top). */
    tjBadges: TjBadge[];
}


// Alef-maksura (ى U+0649) + dagger alef (ٰ U+0670) is one long-vowel unit
// (علىٰ, موسىٰ, إلىٰ). The aligner splits the dagger into its own shard letter,
// but the two render as a single cell. Folding by char is safe — an alef-
// maksura never carries an independent dagger. Every other grapheme stays its
// own cell: a carrier waw keeps its (silent) waw + dagger split, a consonant's
// dagger stays independent.
/** A sukūn cell — never rendered (cell exists with empty phonemeIndices). */
export function _isSukunCell(c: TsCell): boolean {
    return c.role === 'haraka' && firstMark(c.chars) === SUKUN;
}

export function _cellTiming(
    indices: number[],
    intervals: PhonemeInterval[],
    shareIv: [number, number] | null,
): { start: number | null; end: number | null } {
    let s = Infinity;
    let e = -Infinity;
    for (const i of indices) {
        const iv = intervals[i];
        if (!iv) continue;
        s = Math.min(s, iv.start);
        e = Math.max(e, iv.end);
    }
    if (shareIv) {
        // A sounded share-group member extends to (and a silent one borrows)
        // the group's interval union so co-lit cells light together.
        s = Math.min(s, shareIv[0]);
        e = Math.max(e, shareIv[1]);
    }
    return s === Infinity ? { start: null, end: null } : { start: s, end: e };
}

/** Qalqala cell tags (ṣughrā mid-word, kubrā at a stop) — derived from the
 *  registry so the tag keys live in one place. */
export const QALQALA_TAGS = tagsForLegend('qalqala');

/** A qalqala consonant's render-only echo `Q` immediately follows its phoneme
 *  in `intervals[]` but is in NO cell's indexable `phonemeIndices` (excluded by
 *  design — making it indexable would shift the indexable/bridge index space and
 *  break shard byte-parity). For a qalqala cell, return the `[start,end]` of the
 *  `Q` directly after the cell's last own phoneme so its cell duration can include
 *  the echo; null when there's no such echo. */
export function _qalqalaEchoIv(
    indices: number[],
    intervals: PhonemeInterval[],
): [number, number] | null {
    if (!indices.length) return null;
    const after = Math.max(...indices) + 1;
    const iv = intervals[after];
    return iv && iv.phone === 'Q' ? [iv.start, iv.end] : null;
}

/** Per-word share-group interval unions: cells sharing one non-null shareGroup
 *  co-highlight, so each resolves its span to the union of all members. */
export function _shareUnions(
    cells: TsCell[],
    intervals: PhonemeInterval[],
): Map<number, [number, number]> {
    const unions = new Map<number, [number, number]>();
    for (const c of cells) {
        if (c.shareGroup == null) continue;
        for (const i of c.phonemeIndices) {
            const iv = intervals[i];
            if (!iv) continue;
            const cur = unions.get(c.shareGroup);
            if (!cur) unions.set(c.shareGroup, [iv.start, iv.end]);
            else {
                cur[0] = Math.min(cur[0], iv.start);
                cur[1] = Math.max(cur[1], iv.end);
            }
        }
    }
    return unions;
}

/** Per-group interval of a cross-word merger's ghunnah nasal phone (m̃ ñ j̃ w̃).
 *  Only groups whose merged sound is a nasal appear. A receiving carrier in such
 *  a group sounds only that ghunnah, not the source tanwīn's haraka — so its OWN
 *  click/loop/tooltip span is THIS interval, while the highlight span keeps the
 *  full haraka+ghunnah union. Nasals are the only tilde-bearing phones. */
export function _nasalUnions(
    cells: TsCell[],
    intervals: PhonemeInterval[],
): Map<number, [number, number]> {
    const unions = new Map<number, [number, number]>();
    for (const c of cells) {
        if (c.shareGroup == null) continue;
        for (const i of c.phonemeIndices) {
            const iv = intervals[i];
            // U+0303 combining tilde marks every ghunnah nasal (m̃ ñ j̃ w̃).
            if (!iv || !iv.phone.normalize('NFD').includes('̃')) continue;
            const cur = unions.get(c.shareGroup);
            if (!cur) unions.set(c.shareGroup, [iv.start, iv.end]);
            else {
                cur[0] = Math.min(cur[0], iv.start);
                cur[1] = Math.max(cur[1], iv.end);
            }
        }
    }
    return unions;
}

/** The folded letter view of `word.letters` (the ىٰ fold collapses two source
 *  letters into one). Used both for the synthetic-base fallback and to resolve
 *  a `base` cell's glyph / letter-timing by its `sourceLetterIndex`. */
export function foldedLettersFor(word: TsWord): {
    folded: FoldedLetter[];
    srcToFold: Map<number, number>;
} {
    const folded: FoldedLetter[] = [];
    const srcToFold = new Map<number, number>();
    let origIdx = 0;
    for (const letter of word.letters || []) {
        const prev = folded[folded.length - 1];
        if (prev && letter.char.startsWith(DAGGER) && prev.glyph.endsWith(ALEF_MAKSURA)) {
            // Fold the dagger onto the maksura cell: one combined unit spanning
            // both timings, sounding unless both graphemes are silent.
            prev.glyph += letter.char;
            if (letter.end != null) prev.end = letter.end;
            prev.silent = prev.silent && letter.silent === true;
            prev.isNull = prev.isNull || letter.start == null || letter.end == null;
            prev.srcIndices.push(origIdx);
            srcToFold.set(origIdx, folded.length - 1);
            origIdx++;
            continue;
        }
        folded.push({
            glyph: letter.char,
            silent: letter.silent === true,
            start: letter.start,
            end: letter.end,
            isNull: letter.start == null || letter.end == null,
            srcIndices: [origIdx],
        });
        srcToFold.set(origIdx, folded.length - 1);
        origIdx++;
    }
    return { folded, srcToFold };
}

/**
 * Build the ordered cell-group model — the single source for the letter row.
 *
 * GROUPING (respects allocation): a SHORT vowel stays with its base
 * (`[base, haraka]`, kind `base`); a LONG vowel is its own unit
 * `[diacritic, carrier]` (kind `vowel`) whose base is rendered SEPARATELY in
 * its own base group. A long-vowel unit is a `madd` carrier that shares a
 * phoneme (shareGroup) with a haraka. Implicit / standalone madds get their
 * own `vowel` group too. Full cells (`base` + `madd` carriers, real or
 * implicit) render letter-sized; haraka/tanwīn render as small pinned cells.
 * Sukūn is filtered. A base/carrier glyph comes from
 * `word.letters[sourceLetterIndex]` (folded), with ◌ّ composed on when the
 * consonant is geminated (the aligner's letter char carries no shaddah).
 *
 * When a word carries no `base` cells (lightweight test fixtures), synthesize
 * one base per folded letter so the row matches the letters.
 */
export function cellGroupsFor(
    word: TsWord,
    intervals: PhonemeInterval[],
    shareUnions: Map<number, [number, number]>,
    nasalUnions: Map<number, [number, number]>,
    idghamGroupTags: Map<number, string>,
    shareGroupRuleTags: Map<number, string[]>,
    liftIltiqaa = false,
): RenderedGroup[] {
    const { folded, srcToFold } = foldedLettersFor(word);
    // Raw `word.cells[]` index per cell (the report target's `cell_index`),
    // carried through the riding-mark fold so a host keeps its own index.
    // Synthesized special-case cells (iqlab mini-meem, …) miss → -1.
    const foldedCells = foldRidingMarks(word.cells ?? []);
    const rawIndexOf = new Map<TsCell, number>(
        foldedCells.map(({ cell, rawIndex }) => [cell, rawIndex]),
    );
    const cellIndexOf = (c: TsCell): number => rawIndexOf.get(c) ?? -1;
    // The iltiqaa-kasra cell is lifted into a cross-word bridge — drop it from
    // the word's own letter row so it renders only between the two words.
    const cells = foldedCells
        .map(({ cell }) => cell)
        .filter((c) => !(liftIltiqaa && c.rules.includes('iltiqaa_kasra')));
    // A renderable anchor is a base cell OR a real madd carrier (chars != '').
    // Muqattaat whose letters are all spelled-out names (كٓهيعٓصٓ, عٓسٓقٓ, صٓ, قٓ …)
    // carry no base cell but ARE full graphemes — they render through the main
    // per-cell loop (carriers via pushFullGrapheme → madd underline + columns),
    // exactly like alif-led muqattaat (الٓمٓ). Only a truly anchor-less word
    // (diacritic-only fixtures) drops to the synthetic fallback below.
    const hasAnchor = cells.some(
        (c) => c.role === 'base' || (c.role === 'madd' && c.chars !== ''),
    );
    const groups: RenderedGroup[] = [];

    // A cell's underline stack: its own rules plus the cross-word idgham tag
    // propagated to a merger receiver (its share group's source tag). Resolved
    // to ≤3 bars plus an optional full-cell border.
    const cellBadges = (c: TsCell): TjBadge[] => {
        const groupTag = c.shareGroup != null ? idghamGroupTags.get(c.shareGroup) : undefined;
        return badgesForTags([...c.rules, groupTag]);
    };
    // Internal tajweed tag id(s) on the cell — the report rule-picker's options
    // (its own rules + every rule shared across the cell's co-highlight group, so
    // a rule-less co-lit partner is still reportable as the shared rule), keyed by
    // the data-model id, never a label.
    const cellRuleTags = (c: TsCell): string[] => {
        const grp = c.shareGroup != null ? shareGroupRuleTags.get(c.shareGroup) : undefined;
        return [...new Set([...c.rules, ...(grp ?? [])])];
    };
    // A cell's silent-rule hover names (lām shamsiyyah, hamzat-waṣl, iltiqaa, the
    // waqf sukūn, the ʿiwaḍ madd) — these draw no underline, only a tooltip line.
    const cellSilent = (c: TsCell): string[] =>
        [...new Set(c.rules.map(silentTooltip).filter((n): n is string => !!n))];

    // Share-groups that contain a madd carrier = long-vowel units (the haraka
    // pairs with the carrier after it; its base renders separately).
    const longVowelSG = new Set<number>();
    for (const c of cells) {
        if (c.role === 'madd' && c.shareGroup != null) longVowelSG.add(c.shareGroup);
    }
    // Source letters bearing a dropped ṣilah carrier (mini-waw/yaa at waqf, هُۥ/هِۦ):
    // its preceding ḥaraka folds into a shared SILENT vowel group with it, instead
    // of gluing onto the base — resolved in the haraka branch below.
    const droppedSilahSrc = new Set<number>();
    for (const c of cells) {
        if (c.role === 'madd' && c.status === 'dropped' && c.chars) {
            droppedSilahSrc.add(c.sourceLetterIndex);
        }
    }
    // Folded letters already emitted as a full cell (the ىٰ maksura+dagger fold).
    const consumedFold = new Set<number>();

    // --- Carried-vowel resolution: a haraka/tanwīn the phonemizer marks
    //     `dropped` (empty indices) because its vowel is realized on an
    //     ADJACENT carrier must co-light + group with that carrier, not grey
    //     out. One carrier: (idgham shafawi / noon) the merged base that
    //     absorbed the vowel. ---
    // و/ى waqf carrier → its vowel group, so the carrier's own dropped fatḥa
    // rejoins it silently (a double-sided [haraka, carrier, dropped-fatḥa] unit)
    // instead of landing on the preceding base.
    const carrierGroupBySrc = new Map<number, RenderedGroup>();

    const newGroup = (kind: 'base' | 'vowel'): RenderedGroup => {
        const g: RenderedGroup = { kind, full: [], small: [], shareGroup: null, cols: [], phonemeSpans: [] };
        groups.push(g);
        return g;
    };
    // Carry a cell's share-group onto its group (the synchronized-highlight cue).
    const noteShare = (g: RenderedGroup, c: TsCell): void => {
        if (c.shareGroup != null && g.shareGroup == null) g.shareGroup = c.shareGroup;
    };

    const pushSmall = (
        g: RenderedGroup,
        c: TsCell,
        opts: { coLightIv?: [number, number]; glyphOverride?: string; inserted?: boolean } = {},
    ): void => {
        const phone = c.phonemeIndices.length ? intervals[c.phonemeIndices[0]!]?.phone : undefined;
        const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
        let { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
        if (opts.coLightIv) [start, end] = opts.coLightIv; // co-light on the carrier's interval
        const mark = firstMark(c.chars);
        let glyph: string;
        let slot: 'top' | 'bottom';
        let sizeGlyph: string;
        if (opts.glyphOverride) {
            glyph = opts.glyphOverride;
            slot = cellSlot(glyph);
            sizeGlyph = glyph;
        } else if (c.role === 'tanween' && OPEN_TANWEEN[mark]
            && c.rules.some((t) => OPEN_TANWEEN_TAGS.has(t))) {
            // Assimilated tanwīn (idgham / ikhfaa) renders OPEN (DK encodes it
            // as a distinct codepoint); iẓhar keeps the stacked form.
            // Slot follows the canonical mark (kasratan below, others above).
            glyph = OPEN_TANWEEN[mark]!;
            slot = cellSlot(mark);
            sizeGlyph = glyph;
        } else {
            glyph = cellGlyph(c.chars);
            // Iqlab mini-meem: the displayed GLYPH is always the low-meem
            // (cellGlyph normalises it), but its SLOT + calibration follow the
            // SOURCE mark the synthesizer picked — MEEM_HI (ḍamma/fatḥa) sits
            // ABOVE, MEEM_LO (kasra) below — so a non-kasra iqlab meem is on top.
            const meemSrc = mark === MEEM_HI || mark === MEEM_LO;
            slot = meemSrc ? cellSlot(mark) : cellSlot(glyph);
            sizeGlyph = meemSrc ? mark : glyph;
        }
        g.small.push({
            glyph,
            slot,
            // a carried-vowel cell sounds (co-lit) — render timed, not greyed.
            status: opts.coLightIv ? 'present' : c.status,
            rules: c.rules,
            cellStart: start,
            cellEnd: end,
            shareGroup: c.shareGroup,
            cellIndex: cellIndexOf(c),
            ruleTags: cellRuleTags(c),
            renderStyle: harakaRenderStyle(sizeGlyph, 0),
            inserted: opts.inserted ?? c.status === 'inserted',
            phoneIdx: c.phonemeIndices,
            // Diacritic cells underline from their OWN rules (tanwīn idgham /
            // ikhfaa / iqlab / iẓhar); a madd's haraka has none → no underline.
            tjBadges: cellBadges(c),
            silentRules: cellSilent(c),
        });
        noteShare(g, c);
    };

    // A FULL letter-sized cell from a `base` or real `madd` carrier. The glyph
    // is the cell's OWN canonical char (the phonemizer composes ◌ّ onto a
    // geminated consonant) — NOT looked up in word.letters: the phonemizer's
    // source_letter_index folds a dagger-alef ٰ into its base letter, while the
    // aligner keeps it a separate `word.letters` entry, so the two indexings
    // diverge and a word.letters lookup mis-glyphs / drops carriers. `isBase`
    // marks the interactive letter element.
    const pushFullGrapheme = (
        g: RenderedGroup,
        c: TsCell,
        isBase: boolean,
        opts: { glyphOverride?: string } = {},
    ): void => {
        const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
        const { start: ownStart, end: ownEnd } = _cellTiming(c.phonemeIndices, intervals, shareIv);
        // Qalqala: cover the render-only `Q` echo right after this consonant
        // (the echo is in intervals[] but no cell indexes it). BOTH the highlight
        // span (cellStart/cellEnd) AND the letter's own [start,end] grow to the
        // echo end, so click-seek, tooltip duration and loop all run the
        // consonant + its echo as one unit. Applied to the letter span below.
        let start = ownStart;
        let end = ownEnd;
        const qalqalaEcho =
            c.rules.some((t) => QALQALA_TAGS.has(t)) && ownEnd != null
                ? _qalqalaEchoIv(c.phonemeIndices, intervals)
                : null;
        if (qalqalaEcho) {
            start = start != null ? Math.min(start, qalqalaEcho[0]) : qalqalaEcho[0];
            end = Math.max(end!, qalqalaEcho[1]);
        }
        let glyph: string;
        let silent: boolean;
        let lStart: number | null;
        let lEnd: number | null;
        let isNull: boolean;
        let letterIndex: number;
        if (c.chars) {
            // canonical text (shaddah already composed by the producer).
            glyph = opts.glyphOverride ?? c.chars;
            // Silent = sounds nothing (no own phoneme indices) AND isn't co-lit through
            // a merger (no share group). Keyed on the indices, NOT a specific status, so
            // every soundless carrier greys uniformly — a `dropped` otiose alef, a
            // `shortened` iltiqāʾ carrier, etc. (A merger-receiving idgham-noon source
            // noon has no own phones but a share group, so it stays a normal co-lit cell.)
            silent = c.phonemeIndices.length === 0 && c.shareGroup == null;
            lStart = ownStart;
            lEnd = ownEnd;
            isNull = ownStart == null;
            letterIndex = c.sourceLetterIndex;
        } else {
            // Graphemeless base cell (lightweight test fixtures): fall back to
            // the folded word.letters glyph + timing.
            const foldIdx = srcToFold.get(c.sourceLetterIndex);
            const fl = foldIdx != null ? folded[foldIdx] : undefined;
            glyph = fl?.glyph ?? '';
            silent = (fl?.silent ?? c.status === 'dropped') && c.shareGroup == null;
            lStart = fl?.start ?? null;
            lEnd = fl?.end ?? null;
            isNull = fl?.isNull ?? (start == null);
            letterIndex = foldIdx ?? -1;
            if (foldIdx != null) consumedFold.add(foldIdx);
        }
        // A receiving carrier in a cross-word nasal merger (idgham / shafawi)
        // sounds only the ghunnah, not the source tanwīn's haraka. Point its OWN
        // click/loop/tooltip span at that nasal phone — the highlight span
        // (cellStart/cellEnd) keeps the full co-lit haraka+ghunnah union. Both
        // merged letters (e.g. the two shafawi meems) thus read the same nasal.
        const nasalIv = c.shareGroup != null ? nasalUnions.get(c.shareGroup) : undefined;
        if (nasalIv && lStart != null) {
            lStart = nasalIv[0];
            lEnd = nasalIv[1];
        }
        // Qalqala: the letter's click/loop/tooltip span runs through the echo too.
        if (qalqalaEcho && lEnd != null) {
            lStart = lStart != null ? Math.min(lStart, qalqalaEcho[0]) : qalqalaEcho[0];
            lEnd = Math.max(lEnd, qalqalaEcho[1]);
        }
        // Own rules + the propagated cross-word idgham (the receiving merged
        // letter). Un-greying is driven by co-light (a share group, folded into
        // `silent` above), NOT by merely carrying a badge: a co-lit merge source
        // (mutamāthilayn, noon idgham) reads visible + underlined, while a
        // silent-but-tagged source (mutaqāribayn / mutajānisayn) stays greyed yet
        // still draws its underline + tooltip.
        const badges = cellBadges(c);
        g.full.push({
            glyph,
            silent,
            status: c.status,
            rules: c.rules,
            implicit: false,
            // The muted dashed "transform" border, for a contextual transform
            // seat the producer flags `inserted` (started-on ٱئْتُونِى's ئ→ي madd
            // carrier): altered, not the plain rasm. A written ʿiwaḍ alef is the
            // plain rasm — its fatḥatan is the cell that was transformed.
            inserted: c.status === 'inserted',
            isBase,
            cellStart: start,
            cellEnd: end,
            letterStart: lStart,
            letterEnd: lEnd,
            isNull,
            letterIndex,
            cellIndex: cellIndexOf(c),
            ruleTags: cellRuleTags(c),
            shareGroup: c.shareGroup,
            phoneIdx: c.phonemeIndices,
            tjBadges: badges,
            silentRules: cellSilent(c),
        });
        noteShare(g, c);
    };

    const pushFullImplicit = (g: RenderedGroup, c: TsCell, dashed = false): void => {
        const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
        const { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
        g.full.push({
            glyph: implicitMaddGlyph(c.rules),
            silent: c.status === 'dropped',
            status: c.status,
            rules: c.rules,
            implicit: true,
            inserted: dashed,
            isBase: false,
            cellStart: start,
            cellEnd: end,
            letterStart: null,
            letterEnd: null,
            isNull: true,
            letterIndex: -1,
            cellIndex: cellIndexOf(c),
            ruleTags: cellRuleTags(c),
            shareGroup: c.shareGroup,
            phoneIdx: c.phonemeIndices,
            tjBadges: cellBadges(c),
            silentRules: cellSilent(c),
        });
        noteShare(g, c);
    };

    if (hasAnchor) {
        let curBase: RenderedGroup | null = null;
        const vowelGroups = new Map<number, RenderedGroup>();
        const vowelGroupFor = (sg: number): RenderedGroup => {
            let g = vowelGroups.get(sg);
            if (!g) {
                g = newGroup('vowel');
                vowelGroups.set(sg, g);
            }
            return g;
        };
        for (const c of cells) {
            if (_isSukunCell(c)) continue; // sukūn never rendered
            const foldIdx = srcToFold.get(c.sourceLetterIndex);
            if (c.role === 'base') {
                if (foldIdx != null && consumedFold.has(foldIdx)) continue; // maksura+dagger half
                curBase = newGroup('base');
                if (isIqlabCell(c)) {
                    // Iqlab noon → silent ن + a synthesized stacked mini-meem (see
                    // cell-special-cases): the meem owns the nasal + the iqlab underline.
                    pushFullGrapheme(curBase, iqlabNoonSilentBase(c), false);
                    pushSmall(curBase, iqlabMiniMeem(c));
                } else {
                    pushFullGrapheme(curBase, c, true);
                }
            } else if (c.role === 'madd') {
                if (c.chars !== '' && foldIdx != null && consumedFold.has(foldIdx)) continue; // fold half
                if (c.chars === '') {
                    // A graphemeless madd is a long vowel no letter stretches: the
                    // alef of ٱللَّه, or the one a stop supplies for a tanwīn fatḥ
                    // whose word ends in hamza (مَآءً). Only the ʿiwaḍ one is a
                    // transform of what is written, so only it is dashed.
                    pushFullImplicit(
                        c.shareGroup != null && longVowelSG.has(c.shareGroup)
                            ? vowelGroupFor(c.shareGroup) : newGroup('vowel'),
                        c,
                        c.rules.includes('madd_iwad'),
                    );
                } else {
                    const lv = c.shareGroup != null && longVowelSG.has(c.shareGroup);
                    // A dropped ṣilah carrier reuses the vowel group its own ḥaraka
                    // already opened (the ḥaraka is emitted first); else a fresh one.
                    const cg = carrierGroupBySrc.get(c.sourceLetterIndex)
                        ?? (lv ? vowelGroupFor(c.shareGroup!) : newGroup('vowel'));
                    pushFullGrapheme(cg, c, false);
                    carrierGroupBySrc.set(c.sourceLetterIndex, cg);
                }
            } else {
                // haraka / tanwīn
                const dropped = c.phonemeIndices.length === 0;
                if (isIqlabCell(c)) {
                    // Iqlab tanwīn → the single haraka the mushaf writes + the
                    // synthesized mini-meem that owns the nasal and the underline.
                    const g = curBase ?? (curBase = newGroup('base'));
                    pushSmall(g, iqlabTanweenVowel(c));
                    pushSmall(g, iqlabMiniMeem(c));
                } else if (c.rules.includes('madd_iwad') && c.shareGroup != null) {
                    // The stop reads a fatḥatan as a fatḥa and hands its length to
                    // an alef. The mushaf writes the fatḥatan, so the fatḥa is a
                    // transform: dashed, and grouped with the alef it fed.
                    pushSmall(vowelGroupFor(c.shareGroup), c, {
                        glyphOverride: FATHA, inserted: true,
                    });
                } else if (c.shareGroup != null && longVowelSG.has(c.shareGroup)) {
                    pushSmall(vowelGroupFor(c.shareGroup), c); // long vowel — leaves its base
                } else if (dropped && carrierGroupBySrc.has(c.sourceLetterIndex)) {
                    // و/ى waqf: the carrier stole the haraka before it into a madd;
                    // its own fatḥa drops at the stop. Render it silent in the
                    // carrier's vowel group (after it), not on the preceding base.
                    pushSmall(carrierGroupBySrc.get(c.sourceLetterIndex)!, c);
                } else if (dropped && droppedSilahSrc.has(c.sourceLetterIndex)) {
                    // Dropped ṣilah ḥaraka (هُۥ/هِۦ at waqf): OPEN the shared silent
                    // vowel group here so the ḍamma/kasra pairs with its mini-waw/yaa
                    // as one [ḥaraka, carrier] unit, instead of landing on the haa.
                    const cg = newGroup('vowel');
                    carrierGroupBySrc.set(c.sourceLetterIndex, cg);
                    pushSmall(cg, c);
                } else {
                    // short vowel / true waqf drop — and the idgham-shafawi
                    // receiving meem's vowel, which the producer keeps on the
                    // haraka alone (own interval, no merger group), so it lights here
                    // on its own vowel without smearing across the merger.
                    pushSmall(curBase ?? (curBase = newGroup('base')), c);
                }
            }
        }
        return groups;
    }

    // --- Synthetic-base fallback: no base AND no real carrier cells
    //     (diacritic-only fixtures). One group per folded letter, with the
    //     word's diacritic cells attached. ---
    const groupByFold: RenderedGroup[] = folded.map((fl, i) => {
        const g = newGroup('base');
        g.full.push({
            glyph: fl.glyph,
            silent: fl.silent,
            status: 'present',
            rules: [],
            implicit: false,
            inserted: false,
            isBase: true,
            cellStart: fl.start,
            cellEnd: fl.end,
            letterStart: fl.start,
            letterEnd: fl.end,
            isNull: fl.isNull,
            letterIndex: i,
            cellIndex: -1,
            ruleTags: [],
            shareGroup: null,
            phoneIdx: [],
            tjBadges: [],
            silentRules: [],
        });
        return g;
    });
    for (const c of cells) {
        if (_isSukunCell(c)) continue;
        if (c.role === 'madd' && c.chars !== '') continue; // real carrier — already a folded letter
        const foldIdx = srcToFold.get(c.sourceLetterIndex);
        const g = (foldIdx != null ? groupByFold[foldIdx] : undefined) ?? groupByFold[groupByFold.length - 1];
        if (!g) continue;
        if (c.role === 'madd' && c.chars === '') pushFullImplicit(g, c);
        else pushSmall(g, c);
    }
    return groups;
}
