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
 *  - Iqlab noon: the phonemizer stamps a mini-meem cell only for tanwīn iqlab, so
 *    the FE synthesizes one for noon — the ن falls silent and a mini-meem stacked
 *    above it owns the nasal phone + the lone iqlab underline.
 *  - Silah madd: the phonemizer merges the silah maddah onto the bearing letter
 *    (هٓ); it visually belongs on the mini-waw/yaa carrier (هۥٓ), so the base sheds
 *    the maddah glyph and the dropped carrier gains it.
 */
import type { TsCell } from '../../../lib/types/ts-client';
import { MADDAH, MEEM_HI } from './tajweed-script';

// ── Iqlab noon (نْ before ب) ──────────────────────────────────────────────────

/** The ن of an iqlab-noon cell rendered silent — it surrenders its nasal phone
 *  and the lone underline to the synthesized mini-meem below, but keeps a
 *  silent-only `iqlab_silent_noon` tag so it still names "Iqlab" on hover
 *  (registered in `tajweed-rules.ts` SILENT_TOOLTIPS; draws no badge). */
export function iqlabNoonSilentBase(c: TsCell): TsCell {
    return { ...c, phonemeIndices: [], tag: 'iqlab_silent_noon', shareGroup: null };
}

/** The mini-meem stacked above an iqlab-noon ن: owns the nasal phone (the
 *  click/loop + tooltip target) and the lone iqlab underline. Mirrors the meem
 *  cell the phonemizer stamps for tanwīn iqlab, which it does NOT emit for noon. */
export function iqlabNoonMiniMeem(c: TsCell): TsCell {
    return {
        chars: MEEM_HI,
        role: 'tanween',
        status: 'inserted',
        phonemeIndices: c.phonemeIndices,
        sourceLetterIndex: c.sourceLetterIndex,
        tag: 'iqlab_noon',
        shareGroup: null,
    };
}

// ── Silah madd (هُۥٓ / هِۦٓ) ────────────────────────────────────────────────────

/** Source-letter indices whose dropped silah carrier (mini-waw/yaa) bears a madd
 *  the phonemizer merged onto the BEARING letter's grapheme (هٓ); these letters
 *  shed the maddah so it can ride the carrier instead. `droppedSilahSrc` (the set
 *  of source letters with a dropped silah carrier) is passed in — the caller
 *  already computes it for the carrier grouping. */
export function silahMaddahSources(cells: TsCell[], droppedSilahSrc: Set<number>): Set<number> {
    const out = new Set<number>();
    for (const c of cells) {
        if (c.role === 'base' && c.chars.includes(MADDAH) && droppedSilahSrc.has(c.sourceLetterIndex)) {
            out.add(c.sourceLetterIndex);
        }
    }
    return out;
}

/** The bearing letter's glyph with the silah maddah removed (هٓ → ه). */
export const shedSilahMaddah = (chars: string): string => chars.replace(MADDAH, '');

/** The silah carrier's glyph with the relocated maddah (ۥ → ۥٓ). */
export const wearSilahMaddah = (chars: string): string => chars + MADDAH;
