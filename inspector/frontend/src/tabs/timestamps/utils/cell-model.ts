/**
 * Pure data-derivation for the Timestamps analysis view — the cell/group model.
 *
 * Turns a word's positional cells (+ verse intervals + cross-word share/idgham
 * context) into `RenderedGroup[]`: per-grapheme full cells, their small diacritic
 * cells, timing, tajweed badges and silent-rule names. State-free and DOM-free —
 * `UnifiedDisplay.svelte` owns only the reactive glue, imperative highlight and
 * template; the unit tests exercise this module's output through that component.
 */

import { ALEF_MAKSURA, DAGGER, FATHA, MEEM, MEEM_HI, MEEM_LO, NOON, OPEN_TANWEEN, OPEN_TANWEEN_TAGS, SHADDA, SUKUN, cellGlyph, cellSlot, firstMark, implicitMaddGlyph } from './tajweed-script';
import { badgesForTags, silentTooltip, tagsForLegend } from './tajweed-rules';
import type { TjBadge } from './tajweed-rules';
import { applyHamzaWaslMadd, iqlabNoonMiniMeem, iqlabNoonSilentBase, shedSilahMaddah, silahMaddahSources, wearSilahMaddah } from './cell-special-cases';
import { harakaRenderStyle } from './haraka-render';
import { _heavyIkhfaaDisplay } from './phoneme-columns';
import type { PhonemeInterval, TsCell, TsWord } from '../../../lib/types/ts-client';


export interface RenderedFull {
    glyph: string;
    silent: boolean;
    status: string;
    tag: string | null;
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
    /** Internal tajweed tag id(s) on the cell (primary + secondary) — the
     *  report rule-picker's options, keyed by the data-model tag not a label. */
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
    tag: string | null;
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
    /** inserted graphemeless vowel (hamza-waṣl / iltiqaa) — affordance only. */
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
    /** DISPLAY-only phone override (the shard keeps `interval.phone`): a heavy
     *  ikhfaa nasal `ŋ` shown as `ŋˤ` before an istiʿlāʾ letter. Render sites
     *  prefer this over `interval.phone`; null/undefined → use the raw phone. */
    displayPhone?: string;
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

/** Iẓhar — the phonemizer emits NO izhar tag, so it's synthesized here as the
 *  DEFAULT rule for a sounding, untagged, SAKIN noon/meem/tanwīn (the fallback
 *  when no assimilation/conversion rule fired). Two colours: ḥalqī (noon/tanwīn
 *  before a throat letter) vs shafawī (sakin meem). `voweledSrc` is the set of
 *  source-letter indices in the cell's word that carry a real (non-sukūn) vowel,
 *  used to decide a noon/meem is sakin. Returns the synthetic tag or null. */
export function _izharTag(c: TsCell, voweledSrc: Set<number>): 'izhar_halqi' | 'izhar_shafawi' | null {
    if (!c.phonemeIndices.length || c.tag != null || c.shareGroup != null) return null;
    // A tanwīn IS an inherent word-final nūn sound → ḥalqī when untagged.
    if (c.role === 'tanween') return 'izhar_halqi';
    if (c.role !== 'base') return null;
    const head = [...c.chars][0];
    if (c.chars.includes(SHADDA)) return null; // mushaddad → ghunnah, not izhar
    if (voweledSrc.has(c.sourceLetterIndex)) return null; // voweled → not sakin
    if (head === NOON) return 'izhar_halqi';
    if (head === MEEM) return 'izhar_shafawi';
    return null;
}

/** Source-letter indices in a word that carry a real (sounding, non-sukūn)
 *  haraka — a noon/meem on one of these is voweled, not sakin (so not iẓhar). A
 *  tanwīn also vowels its base letter (a meem with ḍammatan is مُ, never sākin), so
 *  count it too — else a tanwīn'd meem/noon falsely reads as a sākin iẓhar source. */
export function _voweledSrcSet(cells: TsCell[]): Set<number> {
    const s = new Set<number>();
    for (const c of cells) {
        if (c.phonemeIndices.length
            && ((c.role === 'haraka' && !_isSukunCell(c)) || c.role === 'tanween')) {
            s.add(c.sourceLetterIndex);
        }
    }
    return s;
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
    izharCellTag: Map<TsCell, string>,
    liftIltiqaa = false,
): RenderedGroup[] {
    const { folded, srcToFold } = foldedLettersFor(word);
    // The iltiqaa-kasra cell is lifted into a cross-word bridge — drop it from
    // the word's own letter row so it renders only between the two words. The
    // hamza-waṣl ibtidaa madd (ٱئْتُونِى) re-pairs its kasra + dropped seat into a
    // shared vowel group — see cell-special-cases (no-op for other words).
    // Raw `word.cells[]` index per cell (the report target's `cell_index`),
    // captured BEFORE the hamza-waṣl transform reorders/replaces objects.
    // Synthesized special-case cells (iqlab mini-meem, …) miss → -1, and fall
    // back to source_letter_index when addressed as a report target.
    const rawIndexOf = new Map<TsCell, number>();
    (word.cells ?? []).forEach((c, i) => rawIndexOf.set(c, i));
    const cellIndexOf = (c: TsCell): number => rawIndexOf.get(c) ?? -1;
    const cells = applyHamzaWaslMadd(
        (word.cells ?? []).filter((c) => !(liftIltiqaa && c.tag === 'iltiqaa_kasra')),
    );
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

    // A cell's underline stack: its own tag + secondary tafkheem + synthesized
    // iẓhar + the cross-word idgham tag propagated to a merger receiver (its
    // share group's source tag) + a heavy-ikhfaa tafkheem (the nasal before an
    // istiʿlāʾ letter, detected display-side). Resolved to ≤2 bars (base + tafkheem).
    const cellBadges = (c: TsCell): TjBadge[] => {
        const groupTag = c.shareGroup != null ? idghamGroupTags.get(c.shareGroup) : undefined;
        // A muqattaat letter's heaviness rides its own `secondaryTags` tafkhīm (set
        // on a heavy istiʿlāʾ / rāʾ name), NOT a buried ikhfaa nasal — so عَيْن's
        // heavy ŋˤ tafkhīm stays on the phoneme row, off the bare ع glyph.
        const isMuq = !!c.phonemeRuleTags?.length;
        const heavyIkhfaa = !isMuq && c.phonemeIndices.some(
            (fi) => _heavyIkhfaaDisplay(intervals[fi]?.phone, intervals[fi + 1]?.phone),
        );
        return badgesForTags([
            c.tag, ...(c.secondaryTags ?? []), izharCellTag.get(c), groupTag,
            heavyIkhfaa ? 'tafkheem' : undefined,
        ]);
    };
    // Internal tajweed tag id(s) on the cell — the report rule-picker's options
    // (primary + secondary + the synthesized iẓhar default + every rule shared
    // across the cell's co-highlight group, so a tag-less co-lit partner is still
    // reportable as the shared rule), keyed by the data-model id, never a label.
    const cellRuleTags = (c: TsCell): string[] => {
        const grp = c.shareGroup != null ? shareGroupRuleTags.get(c.shareGroup) : undefined;
        return [
            ...new Set(
                [c.tag, ...(c.secondaryTags ?? []), izharCellTag.get(c), ...(grp ?? [])].filter(
                    (t): t is string => !!t,
                ),
            ),
        ];
    };
    // Context-derived silent-rule names (need the cell's neighbours): a trailing
    // dropped ḥaraka/tanwīn with nothing sounding after it is the word-final
    // vowel silenced at the stop → "Waqf"; the dropped fatḥatan whose
    // compensating madd moved onto the next ʾalif at waqf → "Madd 'Iwad" (the
    // ʾalif carries the bar); a silent alef/maqṣūra right after a tanwīn is the
    // otiose ʿiwaḍ alef at waṣl → "Madd 'Iwad Wasl".
    const extraSilent = new Map<TsCell, string>();
    {
        let lastSounding = -1;
        cells.forEach((c, i) => { if (c.phonemeIndices.length) lastSounding = i; });
        cells.forEach((c, i) => {
            if ((c.role === 'haraka' || c.role === 'tanween') && c.status === 'dropped'
                && c.phonemeIndices.length === 0 && cells[i + 1]?.tag === 'madd_iwad') {
                extraSilent.set(c, "Madd 'Iwad");
            } else if (c.role === 'madd' && c.tag === 'madd_iwad') {
                // The sounding iwaḍ ʾalif names the rule on hover even when its madd
                // underline (gated by the madd-ṭabīʿī toggle) is off — matching the fatḥa.
                extraSilent.set(c, "Madd 'Iwad");
            } else if ((c.role === 'haraka' || c.role === 'tanween') && c.status === 'dropped'
                && c.phonemeIndices.length === 0 && i > lastSounding) {
                extraSilent.set(c, 'Waqf');
            } else if (c.role === 'base' && c.phonemeIndices.length === 0
                && (c.chars === 'ا' || c.chars === 'ى') && cells[i - 1]?.role === 'tanween') {
                extraSilent.set(c, "Madd 'Iwad Wasl");
            }
        });
    }
    // A cell's silent-rule hover names (lām shamsiyyah, hamzat-waṣl, iltiqaa, the
    // context cases above) — these draw no underline, only a tooltip line.
    const cellSilent = (c: TsCell): string[] => {
        const extra = extraSilent.get(c);
        if (extra) return [extra];
        const n = silentTooltip(c.tag);
        return n ? [n] : [];
    };

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
    // Silah-madd carriers (see cell-special-cases): the maddah the phonemizer
    // merged onto the bearing letter is shed there + re-worn by its carrier.
    const silahMaddahSrc = silahMaddahSources(cells, droppedSilahSrc);
    // Folded letters already emitted as a full cell (the ىٰ maksura+dagger fold).
    const consumedFold = new Set<number>();

    // --- Carried-vowel resolution: a haraka/tanwīn the phonemizer marks
    //     `dropped` (empty indices) because its vowel is realized on an
    //     ADJACENT carrier must co-light + group with that carrier, not grey
    //     out. Three carriers: the madd-ʿiwaḍ alef, the Allah dagger-alef, and
    //     (idgham shafawi / noon) the merged base that absorbed the vowel. ---
    const iwadAlef = cells.find((c) => c.role === 'madd' && c.tag === 'madd_iwad');
    const _iwadIv = iwadAlef
        ? _cellTiming(iwadAlef.phonemeIndices, intervals, null)
        : { start: null, end: null };
    const iwadIv: [number, number] | null = _iwadIv.start != null ? [_iwadIv.start, _iwadIv.end!] : null;
    // The dropped fatḥatan whose compensating madd moved onto the next ʾalif at waqf
    // — detected STRUCTURALLY (its own tag is cleared so it draws no underline; the
    // ʾalif carries the bar). The renderer transforms it into a dashed fatḥa co-lit
    // with the ʾalif (see the iwaḍ branch in the cell loop).
    const iwadFathatan = new Set<TsCell>();
    cells.forEach((c, i) => {
        if ((c.role === 'tanween' || c.role === 'haraka') && c.status === 'dropped'
            && c.phonemeIndices.length === 0 && cells[i + 1]?.tag === 'madd_iwad') {
            iwadFathatan.add(c);
        }
    });
    const daggerBySrc = new Map<number, { group: RenderedGroup; iv: [number, number] }>();
    // و/ى waqf carrier → its vowel group, so the carrier's own dropped fatḥa
    // rejoins it silently (a double-sided [haraka, carrier, dropped-fatḥa] unit)
    // instead of landing on the preceding base.
    const carrierGroupBySrc = new Map<number, RenderedGroup>();
    let iwadGroup: RenderedGroup | null = null;

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
        } else if (c.role === 'tanween' && OPEN_TANWEEN[mark] && OPEN_TANWEEN_TAGS.has(c.tag ?? '')) {
            // Assimilated tanwīn (idgham / ikhfaa) renders OPEN (DK encodes it
            // as a distinct codepoint); iẓhar (tagless) keeps the stacked form.
            // Slot follows the canonical mark (kasratan below, others above).
            glyph = OPEN_TANWEEN[mark]!;
            slot = cellSlot(mark);
            sizeGlyph = glyph;
        } else {
            glyph = cellGlyph(c.chars, c.tag, phone);
            // Iqlab mini-meem: the displayed GLYPH is always the low-meem
            // (cellGlyph normalises it), but its SLOT + calibration follow the
            // SOURCE haraka the phonemizer stamped — MEEM_HI (ḍamma/fatḥa) sits
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
            tag: c.tag,
            cellStart: start,
            cellEnd: end,
            shareGroup: c.shareGroup,
            cellIndex: cellIndexOf(c),
            ruleTags: cellRuleTags(c),
            renderStyle: harakaRenderStyle(sizeGlyph, 0),
            inserted: opts.inserted ?? (c.chars === '' && c.status === 'inserted'),
            phoneIdx: c.phonemeIndices,
            // Diacritic cells underline from their OWN tag (tanwīn idgham/ikhfaa/
            // iqlab) or the synthesized iẓhar rule (an untagged sounding tanwīn);
            // a madd's haraka has no tag → no underline.
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
            QALQALA_TAGS.has(c.tag ?? '') && ownEnd != null
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
            // canonical text (shaddah already composed by the phonemizer);
            // glyphOverride relocates a silah maddah off the bearing letter.
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
        // Own tag + secondary tafkheem + synthesized iẓhar + the propagated
        // cross-word idgham (the receiving merged letter). Un-greying is driven
        // by co-light (a share group, folded into `silent` above), NOT by merely
        // carrying a badge: a co-lit merge source (mutamāthilayn, noon idgham)
        // reads visible + underlined, while a silent-but-tagged source
        // (mutaqāribayn / mutajānisayn) stays greyed yet still draws its
        // underline + tooltip.
        const badges = cellBadges(c);
        g.full.push({
            glyph,
            silent,
            status: c.status,
            tag: c.tag,
            implicit: false,
            // The written madd-ʿiwaḍ alef (substitutes the fatḥatan at waqf) is
            // "added, not in the rasm" → the muted dashed inserted border.
            inserted: c.tag === 'madd_iwad',
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

    const pushFullImplicit = (g: RenderedGroup, c: TsCell): void => {
        const shareIv = c.shareGroup != null ? shareUnions.get(c.shareGroup) ?? null : null;
        const { start, end } = _cellTiming(c.phonemeIndices, intervals, shareIv);
        g.full.push({
            glyph: implicitMaddGlyph(c.tag),
            silent: c.status === 'dropped',
            status: c.status,
            tag: c.tag,
            implicit: true,
            inserted: false,
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
            // Implicit madd (dagger-alef of Allah / ʿiwaḍ alef) — both underline
            // with the madd-ṭabīʿī rule.
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
        const ownIv = (c: TsCell): [number, number] | null => {
            const t = _cellTiming(c.phonemeIndices, intervals, null);
            return t.start != null ? [t.start, t.end!] : null;
        };
        for (const c of cells) {
            if (_isSukunCell(c)) continue; // sukūn never rendered
            const foldIdx = srcToFold.get(c.sourceLetterIndex);
            if (c.role === 'base') {
                if (foldIdx != null && consumedFold.has(foldIdx)) continue; // maksura+dagger half
                curBase = newGroup('base');
                if (c.tag === 'iqlab_noon') {
                    // Iqlab noon → silent ن + a synthesized stacked mini-meem (see
                    // cell-special-cases): the meem owns the nasal + the iqlab underline.
                    pushFullGrapheme(curBase, iqlabNoonSilentBase(c), false);
                    pushSmall(curBase, iqlabNoonMiniMeem(c));
                } else if (silahMaddahSrc.has(c.sourceLetterIndex)) {
                    pushFullGrapheme(curBase, c, true, { glyphOverride: shedSilahMaddah(c.chars) });
                } else {
                    pushFullGrapheme(curBase, c, true);
                }
            } else if (c.role === 'madd') {
                if (c.chars !== '' && foldIdx != null && consumedFold.has(foldIdx)) continue; // fold half
                if (c.tag === 'madd_iwad') {
                    // the substituted (written) or inserted (implicit — word ends in
                    // hamza, مَآءً) iwaḍ alef joins the [fatḥa, alef] vowel group
                    iwadGroup = iwadGroup ?? newGroup('vowel');
                    if (c.chars === '') pushFullImplicit(iwadGroup, c);
                    else pushFullGrapheme(iwadGroup, c, false);
                } else if (c.chars === '') {
                    const g = c.shareGroup != null && longVowelSG.has(c.shareGroup)
                        ? vowelGroupFor(c.shareGroup) : newGroup('vowel');
                    pushFullImplicit(g, c);
                    // An implicit (chars='') non-iwaḍ madd is the Allah dagger-alef —
                    // tagged allah_dagger_alef (ṭabīʿī) or madd_arid_lissukun (ʿāriḍ at
                    // waqf). Co-light its dropped fatḥa with the dagger either way.
                    const iv = ownIv(c);
                    if (iv) daggerBySrc.set(c.sourceLetterIndex, { group: g, iv });
                } else {
                    const lv = c.shareGroup != null && longVowelSG.has(c.shareGroup);
                    // A dropped ṣilah carrier reuses the vowel group its own ḥaraka
                    // already opened (the ḥaraka is emitted first); else a fresh one.
                    const cg = carrierGroupBySrc.get(c.sourceLetterIndex)
                        ?? (lv ? vowelGroupFor(c.shareGroup!) : newGroup('vowel'));
                    // A silah carrier bearing a madd wears the maddah shed by its
                    // bearing letter (هٓ → ه + ۥٓ) — see cell-special-cases.
                    pushFullGrapheme(
                        cg,
                        c,
                        false,
                        silahMaddahSrc.has(c.sourceLetterIndex) ? { glyphOverride: wearSilahMaddah(c.chars) } : {},
                    );
                    carrierGroupBySrc.set(c.sourceLetterIndex, cg);
                }
            } else {
                // haraka / tanwīn
                const dropped = c.phonemeIndices.length === 0;
                if (c.shareGroup != null && longVowelSG.has(c.shareGroup)) {
                    pushSmall(vowelGroupFor(c.shareGroup), c); // long vowel — leaves its base
                } else if (dropped && iwadFathatan.has(c) && iwadIv) {
                    // dropped tanwīn at waqf → a fatḥa grouped + co-lit with the iwaḍ
                    // alef. The fatḥatan→fatḥa transform is "not in the rasm" — flag it
                    // inserted so the small fatḥa cell carries the muted dashed border.
                    // (Detected structurally — its tag is cleared so it draws no bar.)
                    iwadGroup = iwadGroup ?? newGroup('vowel');
                    pushSmall(iwadGroup, c, { coLightIv: iwadIv, glyphOverride: FATHA, inserted: true });
                } else if (dropped && daggerBySrc.has(c.sourceLetterIndex)) {
                    const d = daggerBySrc.get(c.sourceLetterIndex)!;
                    pushSmall(d.group, c, { coLightIv: d.iv }); // Allah: fatḥa joins the dagger ā
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
                    // receiving meem's vowel, which the phonemizer now keeps on the
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
            tag: null,
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
