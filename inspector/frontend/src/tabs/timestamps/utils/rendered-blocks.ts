/**
 * Pure verse assembly for the Timestamps analysis view — `buildRendered` walks a
 * verse's words into `RenderedBlock[]` (per-grapheme cell groups via `cell-model`,
 * phoneme columns via `phoneme-columns`, cross-word idgham/iltiqāʾ bridges and
 * inter-word pause bridges), and `groupUnits` bundles blocks into unbreakable
 * word-units around bridges. State-free; the component reacts on its output.
 */

import { cellGlyph } from './tajweed-script';
import { badgesForTags, bridgeCellTag, isBridgeTag, silentTooltip } from './tajweed-rules';
import type { TjBadge } from './tajweed-rules';
import { harakaRenderStyle } from './haraka-render';
import { splitWaqf } from '../../../lib/utils/waqf';
import type { PhonemeInterval, TsCell, TsWord } from '../../../lib/types/ts-client';
import { QALQALA_TAGS, _nasalUnions, _shareUnions, cellGroupsFor } from './cell-model';
import type { RenderedGroup, RenderedPhoneme } from './cell-model';
import { _buildColumns, _heavyIkhfaaDisplay, _isHeavyIkhfaa } from './phoneme-columns';

/** Rub-el-hizb (U+06DE) and place-of-sajdah (U+06E9) — section markers, not
 *  recited; stripped from the analysis word box so the cell shows only the
 *  recited text. */
const NON_RECITED_SIGNS = /[۞۩]/g;

/** The cross-word idgham rule a cell fires, or null — a cell carries an ordered
 *  rule list and at most one member of it is a bridge. */
function bridgeRuleOf(c: TsCell): string | null {
    return c.rules.find((t) => isBridgeTag(t)) ?? null;
}


export interface RenderedBridge {
    phonemes: RenderedPhoneme[];
    /** iltiqaa connecting-kasra letter cell — the kasra char lifted onto the
     *  letter row of a borderless bridge; null for an idgham merger (which
     *  bridges only the phoneme row). */
    letter: {
        glyph: string;
        style: string;
        cellStart: number | null;
        cellEnd: number | null;
        wordIndex: number;
        /** Silent-rule hover names (the iltiqaa-sākinayn connecting kasra). */
        silentRules: string[];
    } | null;
}

/** A detected silence between this block and the previous one. Sits as a small
 *  cell between the two words; carries the previous word's lifted-out waqf
 *  (stop) mark, or null → the neutral pause icon. Lights while its silence
 *  plays; dims the rest of the row to 70%. */
export interface RenderedPauseBridge {
    mark: string | null;
    startSec: number;
    endSec: number;
    /** The word before this gap (= the silence report's `gap` target word_index). */
    fromWordIndex: number;
}

export interface RenderedBlock {
    word: TsWord;
    wordIndex: number;
    /** Word text to render — the previous-word's waqf mark is stripped here
     *  when a following pause surfaces it into the pause bridge. */
    displayText: string;
    /** Ordered cell-groups (base + its trailing diacritics) — the single
     *  source for the analysis letter row. */
    groups: RenderedGroup[];
    phonemes: RenderedPhoneme[];
    /** Optional cross-word (idgham) bridge to render before this block. */
    bridge: RenderedBridge | null;
    /** Optional pause bridge to render before this block. */
    pauseBridge: RenderedPauseBridge | null;
}

/** A justification line-unit: an unbreakable run of word block(s) — bridge-
 *  linked words stay together — plus an optional trailing pause cell, all
 *  rendered inside one `.word-unit`. The whole unit is the atom the row
 *  justifies between, so a bridged pair never splits across rows and a
 *  word+stop-cell stays glued with the stop cell as the flush anchor. */
export type RenderedUnitPart =
    | { kind: 'block'; block: RenderedBlock }
    | { kind: 'bridge'; bridge: RenderedBridge; wordIndex: number }
    | { kind: 'pause'; pause: RenderedPauseBridge };
export interface RenderedUnit {
    /** First block's wordIndex — the keyed-each identity. */
    key: number;
    parts: RenderedUnitPart[];
    /** Array index of the unit's last block (for bridge-join adjacency). */
    lastBlockIndex: number;
    /** A plain contiguous boundary (no existing pause / bridge) precedes this unit
     *  — the word before it, where a "missed pause" could be flagged. `null` for
     *  the first unit and for a unit that opens with a connector. */
    gapWordIndex: number | null;
    /** The preceding word's lifted-out waqf (stop) sign for that missed-pause slot,
     *  or `null` → the neutral `||` pause symbol. */
    missedMark: string | null;
}

/** Re-link the share-group across each cross-verse waṣl junction, in place.
 *  The idgham source (verse A's tanwīn) and its receiving nasalised head (verse B)
 *  come from ONE phonemizer share-group, but live in different segments — so they
 *  were renumbered into separate groups (per-segment stamp + per-segment `sgOffset`)
 *  and stop co-lighting. Give the receiver's group the source's id so the verse-wide
 *  `_shareUnions` unions [haraka, ghunnah] and the tanwīn highlights through the
 *  merger like every intra-verse one. Pure timing/highlight — no cell content moves. */
function _unifyWaslShareGroups(words: TsWord[], intervals: PhonemeInterval[]): void {
    const verseOf = (loc: string) => loc.split(':').slice(0, 2).join(':');
    for (let wi = 0; wi < words.length - 1; wi++) {
        const cur = words[wi];
        const next = words[wi + 1];
        if (!cur || !next || verseOf(cur.location) === verseOf(next.location)) continue;
        const source = (cur.cells ?? []).slice(-2).reverse().find((c) => bridgeRuleOf(c));
        const headPi = next.phoneme_indices?.[0];
        if (!source || source.shareGroup == null || headPi == null || !intervals[headPi]) continue;
        const recv = (next.cells ?? []).find((c) => c.phonemeIndices.includes(headPi));
        if (!recv) continue;
        const sgA = source.shareGroup;
        const sgB = recv.shareGroup;
        if (sgB === sgA) continue;
        for (const c of next.cells ?? []) {
            if (c === recv || (sgB != null && c.shareGroup === sgB)) c.shareGroup = sgA;
        }
    }
}

/** Build the per-word `RenderedBlock[]` for the analysis view: cross-word
 *  idgham / iltiqaa bridges lifted to between-word tiles, cell-groups whose
 *  phonemes are aligned per-grapheme to their source columns, and detected
 *  inter-word pause bridges. */
export function buildRendered(
    words: TsWord[],
    intervals: PhonemeInterval[],
): RenderedBlock[] {
    if (!words.length) return [];
    // Cross-verse waṣl junctions split the idgham source + receiver into separate
    // segments → separate share-groups. Re-link before the verse-wide union below.
    _unifyWaslShareGroups(words, intervals);

    // Cross-word bridges are baked into the shard at generation: a phoneme
    // carrying a ``bridge`` rule is the idgham merger that fuses two words.
    // Lift it out of its inline row into the gold tile at the boundary — no
    // scanning, no side inference. A merger at a word's head renders before
    // that block; one in a word's tail (idgham shafawi) bridges into the
    // next block. The generator placed the tag on the exact merger interval,
    // so there's nothing to disambiguate here.
    // Share-group interval unions computed VERSE-WIDE (across all words' cells):
    // a cross-word idgham tanwīn shares a group with the receiving word's base,
    // so its highlight must span the haraka + the ghunnah/merger in the next
    // word — a per-word union would miss the other side.
    const allCells = words.flatMap((w) => w.cells ?? []);
    const shareUnions = _shareUnions(allCells, intervals);
    const nasalUnions = _nasalUnions(allCells, intervals);

    // Cross-word idgham SOURCE tag by share group, so a merger RECEIVER inherits
    // the idgham underline from its (silent) source across the group.
    const idghamGroupTags = new Map<number, string>();
    for (const c of allCells) {
        const bridge = bridgeRuleOf(c);
        if (bridge && c.shareGroup != null) idghamGroupTags.set(c.shareGroup, bridge);
    }

    // Every rule tag present ANYWHERE in a share group → so a co-lit partner that
    // owns no rule (a vowel co-lit with its madd letter, an idgham receiver) is
    // still reportable as that shared rule. Drives `cellRuleTags` (report
    // targetability), not the visual badge.
    const shareGroupRuleTags = new Map<number, string[]>();
    for (const c of allCells) {
        if (c.shareGroup == null || !c.rules.length) continue;
        const cur = shareGroupRuleTags.get(c.shareGroup) ?? [];
        for (const t of c.rules) if (!cur.includes(t)) cur.push(t);
        shareGroupRuleTags.set(c.shareGroup, cur);
    }

    // Per-flat-index underline badges, built verse-wide — the single source for
    // BOTH inline phoneme boxes and the cross-word bridge tile (a merger phone is
    // the receiver's). A cell contributes its own rules + the propagated idgham
    // (group) tag, resolved to the badge stack; a tanwīn rule underlines only its
    // nasal (the last phone).
    // Cross-verse waṣl junctions (merged group only). The offline tagger
    // phonemizes each verse-segment alone, so at a verse boundary the merger
    // phone — realized on the NEXT verse's head — carries no `bridge` tag even
    // though the SOURCE cell (the last word's trailing tanwīn / noon / meem)
    // does. In a merged waṣl group the two verses share one `words` list, so
    // synthesize the junction bridge from that source tag, mirroring the
    // within-verse path. A standalone single-verse render has no verse change,
    // so this never fires.
    const _verseOf = (loc: string): string => {
        const p = loc.split(':');
        return `${p[0]}:${p[1]}`;
    };
    interface WaslJunction { target: number; headPi: number; tag: string; source: TsCell }
    const waslJunctions: WaslJunction[] = [];
    for (let wi = 0; wi < words.length - 1; wi++) {
        const cur = words[wi];
        const next = words[wi + 1];
        if (!cur || !next || _verseOf(cur.location) === _verseOf(next.location)) continue;
        // The merger source is the verse-final tanwīn (last cell, or 2nd-last
        // behind a silent fatḥatan alif) — not a deeper within-word idgham.
        const source = (cur.cells ?? []).slice(-2).reverse().find((c) => bridgeRuleOf(c));
        const tag = source ? bridgeRuleOf(source) : null;
        const headPi = next.phoneme_indices?.[0];
        if (source && tag && headPi != null && intervals[headPi]) {
            waslJunctions.push({ target: wi + 1, headPi, tag, source });
        }
    }
    // The junction source cell is suppressed like any bridge source: its leftover
    // vowel renders inline without a badge (the merger shows in the tile).
    const waslJunctionSources = new Set(waslJunctions.map((j) => j.source));

    // Cell tags whose merger is realized as a separate bridge phone (every
    // cross-word merger). A source carrying one of these has its merger shown in the
    // bridge tile, so its OWN inline phonemes (a leftover tanwīn vowel, or the lifted
    // nasal) carry no badge. A within-word merger (mutajānisayn nāqiṣ) emits no bridge
    // phone, so its sounding source badges its own phoneme.
    const bridgeRules = new Set(
        intervals.map((iv) => bridgeCellTag(iv.bridge)).filter((r): r is string => !!r),
    );
    const phonemeBadges = new Map<number, TjBadge[]>();
    for (const c of allCells) {
        // A cross-word idgham source renders its merger as the bridge tile (and
        // colours its own letter via cellBadges) — its own inline phonemes carry no
        // badge: either it's dropped (no phoneme) or its merger is a separate bridge
        // phone. A within-word source (mutajānisayn nāqiṣ ط) has no bridge phone, so
        // it falls through and badges its own sounding phoneme (idgham + its tafkheem).
        if (waslJunctionSources.has(c)) continue;
        const bridge = bridgeRuleOf(c);
        if (bridge && (!c.phonemeIndices.length || bridgeRules.has(bridge))) continue;
        const groupTag = c.shareGroup != null ? idghamGroupTags.get(c.shareGroup) : undefined;
        // Qalqala underlines the render-only echo `Q` (the bounce), NOT the
        // consonant phoneme — its consonant keeps only its other rules (tafkheem).
        const qalqala = c.rules.find((t) => QALQALA_TAGS.has(t));
        if (qalqala && c.phonemeIndices.length) {
            const echo = Math.max(...c.phonemeIndices) + 1;
            if (intervals[echo]?.phone === 'Q') {
                const qb = badgesForTags([qalqala]);
                if (qb.length) phonemeBadges.set(echo, qb);
            }
            const rest = badgesForTags([...c.rules.filter((t) => t !== qalqala), groupTag]);
            if (rest.length) for (const fi of c.phonemeIndices) phonemeBadges.set(fi, rest);
            continue;
        }
        const baseTags = [...c.rules, groupTag];
        const badges = badgesForTags(baseTags);
        if (!badges.length) continue;
        const idxs = c.role === 'tanween' && c.phonemeIndices.length > 1
            ? c.phonemeIndices.slice(-1)
            : c.phonemeIndices;
        // A heavy ikhfaa nasal (ŋ before an istiʿlāʾ letter, shown ŋˤ) stacks a
        // tafkheem bar above its ikhfaa underline.
        for (const fi of idxs) {
            const heavy = _isHeavyIkhfaa(intervals[fi]?.phone, intervals[fi + 1]?.phone);
            phonemeBadges.set(fi, heavy ? badgesForTags([...baseTags, 'tafkheem']) : badges);
        }
    }

    // Cross-word bridges baked into the shard: a phoneme carrying a `bridge` rule
    // is the idgham merger fusing two words. Lift it into the gold tile at the
    // boundary — a merger at a word's head renders before that block; one in a
    // word's tail (idgham shafawi) bridges into the next block. The tile reuses the
    // merger phone's badges (the receiver's own stack — idgham + its tafkheem),
    // falling back to the raw bridge rule.
    const bridgeBeforeBlock = new Map<number, RenderedBridge>();
    const excluded = new Set<number>();
    // Words whose inserted iltiqaa-kasra cell was lifted into a bridge — its
    // small cell is then suppressed in the word's own letter row.
    const liftedIltiqaa = new Set<number>();
    for (let wi = 0; wi < words.length; wi++) {
        const word = words[wi];
        const indices = word?.phoneme_indices ?? [];
        for (let k = 0; k < indices.length; k++) {
            const pi = indices[k]!;
            if (!intervals[pi]?.bridge) continue;
            const target = k === 0 ? wi : wi + 1;
            if (target < words.length) {
                bridgeBeforeBlock.set(target, {
                    phonemes: [{
                        interval: intervals[pi]!, index: pi, wordLocalIndex: -1,
                        tjBadges: phonemeBadges.get(pi)
                            ?? badgesForTags([bridgeCellTag(intervals[pi]!.bridge)]),
                    }],
                    letter: null,
                });
                excluded.add(pi);
            }
        }
        // iltiqaa kasra: tanwīn meeting the next word's hamza-waṣl inserts a
        // connecting kasra (i). Lift its cell out of word N into a borderless
        // bridge before word N+1 — the kasra char on the letter row + the i
        // phoneme on the phoneme row, between the two words. The silent alef of
        // a fatḥatan+alef word (خَيْرًا) stays in word N, so the bridge naturally
        // sits after it; the lifted i is the word's last phoneme.
        const kasra = (word?.cells ?? []).find((c) => c.rules.includes('iltiqaa_kasra'));
        const kpi = kasra?.phonemeIndices[0];
        if (kasra && kpi != null && intervals[kpi] && wi + 1 < words.length
            && !bridgeBeforeBlock.has(wi + 1)) {
            const iv = intervals[kpi];
            const glyph = cellGlyph(kasra.chars, kasra.rules, iv.phone);
            bridgeBeforeBlock.set(wi + 1, {
                phonemes: [{ interval: iv, index: kpi, wordLocalIndex: -1, tjBadges: [] }],
                letter: {
                    glyph,
                    style: harakaRenderStyle(glyph),
                    cellStart: iv.start,
                    cellEnd: iv.end,
                    wordIndex: wi,
                    silentRules: kasra.rules
                        .map(silentTooltip)
                        .filter((n): n is string => !!n),
                },
            });
            excluded.add(kpi);
            liftedIltiqaa.add(wi);
        }
    }

    // Lift each cross-verse waṣl junction into a bridge tile before the receiving
    // word: the merger phone (the next verse's nasalized head) carries the source
    // idgham badge. Skipped if a real shard bridge already claimed the boundary.
    for (const j of waslJunctions) {
        if (bridgeBeforeBlock.has(j.target)) continue;
        bridgeBeforeBlock.set(j.target, {
            phonemes: [{
                interval: intervals[j.headPi]!, index: j.headPi, wordLocalIndex: -1,
                tjBadges: phonemeBadges.get(j.headPi) ?? badgesForTags([j.tag]),
            }],
            letter: null,
        });
        excluded.add(j.headPi);
    }

    const blocks: RenderedBlock[] = [];
    for (let wi = 0; wi < words.length; wi++) {
        const word = words[wi];
        if (!word) continue;

        const bridge: RenderedBridge | null = bridgeBeforeBlock.get(wi) ?? null;

        const phonemes: RenderedPhoneme[] = [];
        // Word-local indexable-phone counter — matches the shard's indexable space
        // (render-only Q + geminate_end excluded), so a phoneme's `wordLocalIndex`
        // is the `phoneme_flat_index` a report target keys on.
        let wli = 0;
        for (const pi of word.phoneme_indices ?? []) {
            const iv = intervals[pi];
            if (!iv) continue;
            const indexable = iv.phone !== 'Q' && !iv.geminate_end;
            if (!excluded.has(pi) && !iv.geminate_end) {
                phonemes.push({
                    interval: iv,
                    index: pi,
                    wordLocalIndex: indexable ? wli : -1,
                    tjBadges: phonemeBadges.get(pi) ?? [],
                    displayPhone: _heavyIkhfaaDisplay(iv.phone, intervals[pi + 1]?.phone),
                });
            }
            if (indexable) wli++;
        }

        const groups = cellGroupsFor(word, intervals, shareUnions, nasalUnions, idghamGroupTags, shareGroupRuleTags, liftedIltiqaa.has(wi));
        _buildColumns(groups, phonemes);

        blocks.push({
            word,
            wordIndex: wi,
            displayText: (word.display_text || word.text).replace(NON_RECITED_SIGNS, ''),
            groups,
            phonemes,
            bridge,
            pauseBridge: null,
        });
    }

    // Detected inter-word silences: a positive gap between consecutive words
    // (their end/start are ms-quantized, so contiguous words share a boundary
    // and only a real pause leaves a gap). Each gap gets a pause bridge before
    // the later block; a surfaced waqf mark on the earlier word is lifted out
    // of its box into the bridge.
    for (let bi = 0; bi < blocks.length - 1; bi++) {
        const a = blocks[bi]!;
        const b = blocks[bi + 1]!;
        const startSec = a.word.end;
        const endSec = b.word.start;
        if (endSec <= startSec) continue;
        const { clean, mark } = splitWaqf(a.displayText);
        if (mark) a.displayText = clean;
        b.pauseBridge = { mark, startSec, endSec, fromWordIndex: a.wordIndex };
    }
    return blocks;
}

/** Group the rendered blocks into unbreakable `.word-unit`s for centered,
 *  uniform-gap rows. A `block.bridge` (idgham / iltiqaa) and a `block.pauseBridge`
 *  (inter-word silence) are both CONNECTORS linking the block to its
 *  predecessor: each pairs the two words into one unit with the connector tile
 *  between them, so neither a bridged pair/chain nor a word+stop-cell splits
 *  across rows. Bridge and pause are mutually exclusive at a boundary (a merger
 *  is contiguous, a pause is a gap); a bridge wins if both ever appear. */
export function groupUnits(blocks: RenderedBlock[]): RenderedUnit[] {
    const units: RenderedUnit[] = [];
    let cur: RenderedUnit | null = null;
    for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i]!;
        const connector: RenderedUnitPart | null = block.bridge
            ? { kind: 'bridge', bridge: block.bridge, wordIndex: block.wordIndex }
            : block.pauseBridge
              ? { kind: 'pause', pause: block.pauseBridge }
              : null;
        const joins = connector != null && cur != null && cur.lastBlockIndex === i - 1;
        if (joins) {
            cur!.parts.push(connector!, { kind: 'block', block });
            cur!.lastBlockIndex = i;
        } else {
            cur = { key: block.wordIndex, parts: [], lastBlockIndex: i, gapWordIndex: null, missedMark: null };
            if (connector) {
                // Defensive: a connector with no joinable predecessor still renders.
                cur.parts.push(connector);
            } else if (i > 0) {
                // A new unit with NO connector opens a plain contiguous boundary with
                // the previous word — a candidate "missed pause" slot. Lift the
                // previous word's stop sign (if any) into it, else fall back to `||`.
                const prev = blocks[i - 1]!;
                cur.gapWordIndex = prev.wordIndex;
                cur.missedMark = splitWaqf(prev.displayText).mark;
            }
            cur.parts.push({ kind: 'block', block });
            units.push(cur);
        }
    }
    return units;
}
