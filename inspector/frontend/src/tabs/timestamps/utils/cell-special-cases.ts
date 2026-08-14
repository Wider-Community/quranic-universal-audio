/**
 * One-off per-rule cell-alignment special cases for the Timestamps analysis row.
 *
 * `UnifiedDisplay.cellGroupsFor` builds the letter/phoneme cell groups from the
 * canonical shard cells under the general grammar (base → group, ḥaraka → pinned
 * small, madd → carrier). A few tajweed phenomena need a one-off adjustment that
 * doesn't fit that grammar — they live here as pure cell/glyph transforms so the
 * grouping loop stays readable and each case is independently testable.
 *
 * Add a NEW special case here rather than threading another branch through
 * `cellGroupsFor`.
 *
 *  - Riding marks: the producer gives the maddah a cell of its own while the
 *    letter row writes it on the letter it stretches, so the FE folds it back.
 *  - Iqlab: the shard carries one cell for the converted noon / tanwīn; the FE
 *    splits it into the muted source grapheme and the mini-meem that sounds.
 */
import type { TsCell } from '../../../lib/types/ts-client';
import {
    DAMMA,
    DAMMATAN,
    FATHA,
    FATHATAN,
    KASRA,
    KASRATAN,
    MADDAH,
    MEEM_HI,
    MEEM_LO,
    firstMark,
} from './tajweed-script';

// ── Riding marks (the maddah) ─────────────────────────────────────────────────

/** Marks that open a cell of their own but are written on the letter before them
 *  — the maddah of آ, of a muqaṭṭaʿah letter name, of a ṣilah carrier (هۦٓ). */
const RIDING_MARKS = new Set([MADDAH]);

/** One folded cell plus the raw `word.cells[]` index it came from (a riding mark
 *  takes its host's, so a report target still resolves). */
export interface FoldedCell {
    cell: TsCell;
    rawIndex: number;
}

/** Fold every riding mark onto the cell before it — its chars, phonemes and rules
 *  all join the host, mirroring the letter row that writes the mark on that same
 *  letter. A leading riding mark (no host yet) stays a cell of its own. */
export function foldRidingMarks(cells: TsCell[]): FoldedCell[] {
    const out: FoldedCell[] = [];
    cells.forEach((c, i) => {
        const host = out[out.length - 1];
        if (host && c.chars !== '' && [...c.chars].every((ch) => RIDING_MARKS.has(ch))) {
            out[out.length - 1] = {
                rawIndex: host.rawIndex,
                cell: {
                    ...host.cell,
                    chars: host.cell.chars + c.chars,
                    phonemeIndices: [...new Set([...host.cell.phonemeIndices, ...c.phonemeIndices])],
                    rules: [...new Set([...host.cell.rules, ...c.rules])],
                },
            };
            return;
        }
        out.push({ cell: c, rawIndex: i });
    });
    return out;
}

// ── Iqlab (نْ / tanwīn before ب) ──────────────────────────────────────────────

/** Single haraka per tanwīn mark, and the mini-meem slot its vowel quality takes:
 *  fatḥa/ḍamma stack the meem ABOVE, kasra BELOW. */
const TANWEEN_IQLAB: Record<string, { haraka: string; meem: string }> = {
    [FATHATAN]: { haraka: FATHA, meem: MEEM_HI },
    [DAMMATAN]: { haraka: DAMMA, meem: MEEM_HI },
    [KASRATAN]: { haraka: KASRA, meem: MEEM_LO },
};

/** True for a cell the FE renders as an iqlab pair — a sākin noon or a tanwīn the
 *  producer converted. Both arrive as one cell; neither ships a mini-meem. */
export function isIqlabCell(c: TsCell): boolean {
    if (!c.rules.includes('iqlab')) return false;
    if (c.role === 'base') return true;
    return c.role === 'tanween' && !!TANWEEN_IQLAB[firstMark(c.chars)] && c.phonemeIndices.length >= 2;
}

/** The ن of an iqlab-noon cell rendered silent — it surrenders its nasal phone
 *  and the lone underline to the synthesized mini-meem below, but keeps a
 *  silent-only `iqlab_silent_noon` rule so it still names "Iqlab" on hover
 *  (registered in `tajweed-rules.ts` SILENT_TOOLTIPS; draws no badge). */
export function iqlabNoonSilentBase(c: TsCell): TsCell {
    return { ...c, phonemeIndices: [], rules: ['iqlab_silent_noon'], shareGroup: null };
}

/** The tanwīn of an iqlab cell reduced to the single haraka the mushaf writes —
 *  it keeps only the vowel phone; the mini-meem takes the nasal and the underline. */
export function iqlabTanweenVowel(c: TsCell): TsCell {
    const pair = TANWEEN_IQLAB[firstMark(c.chars)];
    return {
        ...c,
        chars: pair ? pair.haraka : c.chars,
        role: 'haraka',
        phonemeIndices: c.phonemeIndices.slice(0, -1),
        rules: [],
        shareGroup: null,
    };
}

/** The mini-meem stacked on an iqlab source: it owns the nasal phone (the
 *  click/loop + tooltip target) and the lone iqlab underline. A noon has no vowel
 *  of its own, so the meem takes all its phones and the high glyph; a tanwīn hands
 *  over its last phone and picks the glyph from its vowel quality. */
export function iqlabMiniMeem(c: TsCell): TsCell {
    const pair = c.role === 'tanween' ? TANWEEN_IQLAB[firstMark(c.chars)] : undefined;
    return {
        chars: pair ? pair.meem : MEEM_HI,
        role: 'tanween',
        status: 'inserted',
        phonemeIndices: pair ? c.phonemeIndices.slice(-1) : c.phonemeIndices,
        sourceLetterIndex: c.sourceLetterIndex,
        rules: ['iqlab'],
        shareGroup: null,
    };
}
