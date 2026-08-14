/**
 * The single tajweed-rule registry for the Timestamps analysis row — the "locked
 * table" in code. Maps each producer cell rule (and the few FE-synthesized tags)
 * to its colour, legend grouping, tooltip name, default-on state and stack
 * layer. Everything downstream derives from here so nothing can drift:
 *
 *  - `badgeForTag` / `badgesForTags` — resolve a cell's rule list into ordered
 *    underline badges (bottom→top; tafkheem always the top bar).
 *  - `tjShadow` — compose the per-cell `box-shadow` underline from its badges,
 *    filtered by the live enable set (qalqala kubra draws a taller fill).
 *  - `LEGEND` / `DEFAULT_ENABLED` — drive the settings panel + its first-load state.
 *  - `silentTooltip` — name-only hover text for the silent rules (no colour/legend).
 *  - `tajweedColorVar` / `isBridgeTag` / `CROSS_WORD_IDGHAM_TAGS` — the legacy
 *    colour-map surface, kept derived from the registry.
 *  - `bridgeCellTag` — the cell-tag name of a merger phone's bridge rule.
 *
 * Cells carry the canonical rule ids (producer-owned); the *renderer* owns the
 * palette + visual treatment, mirroring `tajweed-script.ts`. The actual hues live
 * as `--tj-*` CSS custom properties in `styles/base.css` (overridable per-rule at
 * runtime by the settings store).
 */

import * as m from '$lib/paraglide/messages';
import type { TajweedRule } from '../../../lib/types/generated/schemas';

/** Which channel of the cell's `box-shadow` a rule draws in. The three bar
 *  layers stack bottom→top; `border` is a full inset ring that leaves the bar
 *  offsets alone, so a bordered rule composes with any of them. */
export type StackLayer = 'base' | 'merge' | 'top' | 'border';
export type RuleCategory = 'noon_meem' | 'madd' | 'other';

/** Tags the FE synthesizes itself — NOT producer `TajweedRule` members, so the
 *  registry allows them alongside the producer vocabulary. Each is documented at
 *  its synthesis site: `iqlab_silent_noon` (`cell-special-cases.ts`),
 *  `allah_dagger_alef` (an annotated shard's implicit Allah madd). */
export type FeSynthesizedTag = 'iqlab_silent_noon' | 'allah_dagger_alef';

/** Any tag a cell can carry: the phonemizer producer vocabulary (`TajweedRule`,
 *  codegen'd from `qua_shared`) plus the FE-owned synthesized tags. */
export type TajweedTag = TajweedRule | FeSynthesizedTag;

interface RuleDef {
    /** groups tags into one legend row / enable toggle / colour (e.g. both qalqala
     *  subtypes share `qalqala`; both ghunnah letters share `ghunnah`). */
    legendKey: string;
    /** the `--tj-*` custom property backing this rule's colour. */
    colorVar: string;
    /** hover tooltip name — may differ between tags sharing a legendKey
     *  (qalqala ṣughrā vs kubrā, mutajānisayn kāmil vs nāqiṣ). Message-function
     *  reference, called at the render site so a locale switch re-evaluates it. */
    tooltip: () => string;
    /** which underline bar this rule occupies when stacked (bottom→top):
     *  `base` (the cell's own rule, e.g. ghunnah) < `merge` (a cross-word idgham
     *  riding ON the target, e.g. mutajānisayn over a ghunnah) < `top` (tafkheem). */
    stack: StackLayer;
}

/** Every tag that draws a coloured underline → its rule definition. Tags sharing a
 *  `legendKey` share colour + toggle but keep their own tooltip. `satisfies`
 *  constrains keys to known tags (a phonemizer rename/typo is a compile error)
 *  while preserving the literal key set for the completeness check below. */
const COLOR_RULES = {
    // ── Ghunnah / nasalization ────────────────────────────────────────────────
    ghunnah: { legendKey: 'ghunnah', colorVar: '--tj-ghunnah', tooltip: m.ts_tajweed_rule_ghunnah, stack: 'base' },
    ikhfaa: { legendKey: 'ikhfaa', colorVar: '--tj-ikhfaa', tooltip: m.ts_tajweed_rule_ikhfaa, stack: 'base' },
    ikhfaa_shafawi: { legendKey: 'ikhfaa_shafawi', colorVar: '--tj-ikhfaa-shafawi', tooltip: m.ts_tajweed_rule_ikhfaa_shafawi, stack: 'base' },
    iqlab: { legendKey: 'iqlab', colorVar: '--tj-iqlab', tooltip: m.ts_tajweed_rule_iqlab, stack: 'base' },
    idgham_bi_ghunnah: { legendKey: 'idgham_ghunnah', colorVar: '--tj-idgham-ghunnah', tooltip: m.ts_tajweed_rule_idgham_ghunnah, stack: 'base' },
    idgham_shafawi: { legendKey: 'idgham_shafawi', colorVar: '--tj-idgham-shafawi', tooltip: m.ts_tajweed_rule_idgham_shafawi, stack: 'base' },
    // ── Madd ──────────────────────────────────────────────────────────────────
    madd_lazim: { legendKey: 'madd_lazim', colorVar: '--tj-madd-lazim', tooltip: m.ts_tajweed_rule_madd_lazim, stack: 'base' },
    madd_wajib_muttasil: { legendKey: 'madd_wajib', colorVar: '--tj-madd-wajib', tooltip: m.ts_tajweed_rule_madd_wajib, stack: 'base' },
    madd_jaiz_munfasil: { legendKey: 'madd_jaiz', colorVar: '--tj-madd-jaiz', tooltip: m.ts_tajweed_rule_madd_jaiz, stack: 'base' },
    madd_arid_lil_sukun: { legendKey: 'madd_arid', colorVar: '--tj-madd-arid', tooltip: m.ts_tajweed_rule_madd_arid, stack: 'base' },
    madd_leen: { legendKey: 'madd_leen', colorVar: '--tj-madd-leen', tooltip: m.ts_tajweed_rule_madd_leen, stack: 'base' },
    // ṭabīʿī + its structural aliases (the dagger-alef of Allah, the ʿiwaḍ alef)
    madd_tabii: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: m.ts_tajweed_rule_madd_tabii, stack: 'base' },
    allah_dagger_alef: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: m.ts_tajweed_rule_madd_tabii, stack: 'base' },
    madd_iwad: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: m.ts_tajweed_rule_madd_iwad, stack: 'base' },
    // ── Heaviness ─────────────────────────────────────────────────────────────
    tafkheem: { legendKey: 'tafkheem', colorVar: '--tj-tafkheem', tooltip: m.ts_tajweed_rule_tafkheem, stack: 'top' },
    qalqala_sughra: { legendKey: 'qalqala', colorVar: '--tj-qalqala', tooltip: m.ts_tajweed_rule_qalqala_sughra, stack: 'base' },
    qalqala_kubra: { legendKey: 'qalqala', colorVar: '--tj-qalqala', tooltip: m.ts_tajweed_rule_qalqala_kubra, stack: 'base' },
    // ── Idgham (silent merges) ────────────────────────────────────────────────
    idgham_bila_ghunnah: { legendKey: 'idgham_bila', colorVar: '--tj-idgham-bila', tooltip: m.ts_tajweed_rule_idgham_bila_ghunnah, stack: 'base' },
    // The consonant idghams ride the `merge` layer — they sit ABOVE the target's own
    // base rule (e.g. a ghunnah on the receiving mīm of ٱرْكَب مَّعَنَا) and below tafkheem.
    idgham_mutamathilayn: { legendKey: 'mutamathilayn', colorVar: '--tj-mutamathilayn', tooltip: m.ts_tajweed_rule_idgham_mutamathilayn, stack: 'merge' },
    idgham_mutaqaribayn: { legendKey: 'mutaqaribayn', colorVar: '--tj-mutaqaribayn', tooltip: m.ts_tajweed_rule_idgham_mutaqaribayn, stack: 'merge' },
    idgham_mutajanisayn_kamil: { legendKey: 'mutajanisayn', colorVar: '--tj-mutajanisayn', tooltip: m.ts_tajweed_rule_idgham_mutajanisayn_kamil, stack: 'merge' },
    idgham_mutajanisayn_naqis: { legendKey: 'mutajanisayn', colorVar: '--tj-mutajanisayn', tooltip: m.ts_tajweed_rule_idgham_mutajanisayn_naqis, stack: 'merge' },
    // ── Iẓhar ─────────────────────────────────────────────────────────────────
    izhar: { legendKey: 'izhar', colorVar: '--tj-izhar-halqi', tooltip: m.ts_tajweed_rule_izhar_halqi, stack: 'base' },
    izhar_shafawi: { legendKey: 'izhar_shafawi', colorVar: '--tj-izhar-shafawi', tooltip: m.ts_tajweed_rule_izhar_shafawi, stack: 'base' },
    // ── Special rules ─────────────────────────────────────────────────────────
    // Rare readings that colour a whole grapheme rather than one edge of it, so
    // they take the border channel and share one legend row + toggle.
    imala: { legendKey: 'special', colorVar: '--tj-special', tooltip: m.ts_tajweed_rule_imala, stack: 'border' },
    ishmam: { legendKey: 'special', colorVar: '--tj-special', tooltip: m.ts_tajweed_rule_ishmam, stack: 'border' },
    tashil: { legendKey: 'special', colorVar: '--tj-special', tooltip: m.ts_tajweed_rule_tashil, stack: 'border' },
    ibdal_hamza: { legendKey: 'special', colorVar: '--tj-special', tooltip: m.ts_tajweed_rule_ibdal_hamza, stack: 'border' },
} satisfies Partial<Record<TajweedTag, RuleDef>>;

/** Silent rules — hover tooltip only, no colour and no legend row. Message-function
 *  references, called at the render site so a locale switch re-evaluates them.
 *  `madd_iwad` is here AND in `COLOR_RULES`: its bar is gated by the madd-ṭabīʿī
 *  toggle but the name stays on hover either way (`tjRuleNames` dedups). */
const SILENT_TOOLTIPS = {
    hamza_wasl_elision: m.ts_tajweed_rule_silent_hamza_wasl,
    lam_shamsiyyah: m.ts_tajweed_rule_silent_lam_shamsiyah,
    iltiqaa_kasra: m.ts_tajweed_rule_silent_iltiqaa,
    iltiqaa: m.ts_tajweed_rule_silent_iltiqaa,
    pausal_sukun: m.ts_tajweed_rule_silent_waqf,
    pausal_alif: m.ts_tajweed_rule_pausal_alif,
    taa_marbuta_pausal: m.ts_tajweed_rule_taa_marbuta_pausal,
    orthographic_silence: m.ts_tajweed_rule_silent_orthographic,
    madd_iwad: m.ts_tajweed_rule_madd_iwad,
    // The ن of an iqlab noon falls silent (the synthesized mini-meem owns the
    // nasal + the lone underline) — name it on hover, draw no bar.
    iqlab_silent_noon: m.ts_tajweed_rule_iqlab,
} satisfies Partial<Record<TajweedTag, () => string>>;

// Compile-time completeness: every producer rule must be classified — either
// rendered (a COLOR_RULES / SILENT_TOOLTIPS entry) or explicitly pipeline-only
// (carried in the shard but intentionally drawn with no badge/tooltip: the
// hamzat-waṣl ibtidāʾ vowels, whose three qualities the shard splits so the
// pipeline can tell them apart). A new producer rule lands in `TajweedRule` via
// codegen and breaks this assertion until classified — never a silently-dropped
// underline.
const _PIPELINE_ONLY_TAGS = [
    'hamza_wasl_fatha',
    'hamza_wasl_kasra',
    'hamza_wasl_damma',
] as const satisfies readonly TajweedRule[];

type RenderedTag = keyof typeof COLOR_RULES | keyof typeof SILENT_TOOLTIPS;
type UnclassifiedRule = Exclude<TajweedRule, RenderedTag | (typeof _PIPELINE_ONLY_TAGS)[number]>;
const _assertAllRulesClassified: UnclassifiedRule extends never ? true : UnclassifiedRule = true;
void _assertAllRulesClassified;

/** One resolved underline badge a cell carries (settings-independent). */
export interface TjBadge {
    legendKey: string;
    colorVar: string; // bare custom-property name, e.g. '--tj-tafkheem'
    /** Message-function reference — call at the render site so a locale switch re-evaluates it. */
    tooltip: () => string;
    stack: StackLayer;
    /** qalqala kubrā — draws a taller (≈30% cell-height) fill instead of a thin bar. */
    kubra: boolean;
}

/** Resolve one tag into its badge, or null if the tag draws no underline. */
export function badgeForTag(tag: string | null | undefined): TjBadge | null {
    if (!tag) return null;
    const def = (COLOR_RULES as Partial<Record<string, RuleDef>>)[tag];
    if (!def) return null;
    return { ...def, kubra: tag === 'qalqala_kubra' };
}

/** Resolve a cell's candidate tags into its ordered underline stack (bottom→top):
 *  at most one `base` bar (the first colourable base rule in tag order — a cell's
 *  own tag wins over a propagated one), one `merge` bar (a cross-word idgham riding
 *  on the target), tafkheem on top, and the full-cell border last so its ring paints
 *  under the bars. Empty when no tag is colourable. */
export function badgesForTags(tags: (string | null | undefined)[]): TjBadge[] {
    let base: TjBadge | null = null;
    let merge: TjBadge | null = null;
    let top: TjBadge | null = null;
    let border: TjBadge | null = null;
    for (const t of tags) {
        const b = badgeForTag(t);
        if (!b) continue;
        if (b.stack === 'top') top ??= b;
        else if (b.stack === 'merge') merge ??= b;
        else if (b.stack === 'border') border ??= b;
        else base ??= b;
    }
    const out: TjBadge[] = [];
    if (base) out.push(base);
    if (merge) out.push(merge);
    if (top) out.push(top);
    if (border) out.push(border);
    return out;
}

/** The silent-rule hover name for a tag (the named silent rules + the iltiqaa
 *  kasra), or null. Independent of the colour/legend set. */
export function silentTooltip(tag: string | null | undefined): string | null {
    const fn = tag ? (SILENT_TOOLTIPS as Partial<Record<string, () => string>>)[tag] : undefined;
    return fn ? fn() : null;
}

/** A tag the report rule-picker can present — it has a human label (coloured
 *  badge or named silent rule). Sentinels like `silent_unclassified` have no
 *  label and are not a "rule" you can call wrong, so the picker omits them. */
export function ruleHasLabel(tag: string | null | undefined): boolean {
    return !!(badgeForTag(tag) || silentTooltip(tag));
}

/** All tags sharing a legend toggle/colour (e.g. both qalqala subtypes) — derived
 *  from the registry so callers never re-list tag keys. */
export function tagsForLegend(legendKey: string): Set<string> {
    return new Set(
        Object.entries(COLOR_RULES)
            .filter(([, def]) => def.legendKey === legendKey)
            .map(([tag]) => tag),
    );
}

// ── Underline geometry ────────────────────────────────────────────────────────

/** Thin bar thickness (px) for a normal underline / each stacked layer. */
const BAR_PX = 2;
/** Ring thickness (px) for a `border`-layer rule — a full outline of the cell. */
const BORDER_PX = 2;

/**
 * Compose the per-cell underline `box-shadow` from its badges, keeping only the
 * rules whose legend toggle is enabled. Stacked inset bottom-shadows accumulate
 * from the cell's bottom edge upward — the base rule is the lowest bar, tafkheem
 * the bar above it. A `border` badge draws a full inset ring instead and does NOT
 * advance the bar offset, so a special rule never shifts the bars beside it.
 * A qalqala-**kubrā** bar draws its bottom edge here exactly like ṣughrā (same
 * inset bottom-shadow, hugging the cell's rounded corners); only its short
 * side-wraps are added separately via the `::after` (see `tjKubraColor`).
 * Empty string when no enabled badge draws an inset bar. Uses the inset-box-shadow
 * channel so bars survive the `.active` fill.
 */
export function tjShadow(badges: TjBadge[], isEnabled: (legendKey: string) => boolean): string {
    let offset = 0;
    const shadows: string[] = [];
    for (const b of badges) {
        if (!isEnabled(b.legendKey)) continue;
        if (b.stack === 'border') {
            shadows.push(`inset 0 0 0 ${BORDER_PX}px var(${b.colorVar})`);
            continue;
        }
        offset += BAR_PX;
        shadows.push(`inset 0 -${offset}px 0 var(${b.colorVar})`);
    }
    return shadows.join(', ');
}

/** The colour of an enabled qalqala-kubrā badge on this cell (for the side-wrap
 *  `::after`), or '' if none — kubrā's bottom bar is identical to ṣughrā (drawn by
 *  `tjShadow`); the `::after` only curls the bar a little way up the side edges. */
export function tjKubraColor(badges: TjBadge[], isEnabled: (legendKey: string) => boolean): string {
    const b = badges.find((x) => x.kubra && isEnabled(x.legendKey));
    return b ? `var(${b.colorVar})` : '';
}

/** Tooltip rule names for a cell: the enabled coloured badges plus the always-on
 *  silent-rule names, newline-joined for the hover tip (empty string → no rule
 *  line). `silent` is the cell's silent-rule names (from `silentTooltip`). */
export function tjRuleNames(
    badges: TjBadge[],
    silent: string[],
    isEnabled: (legendKey: string) => boolean,
): string {
    // Dedup so a name carried by BOTH a (toggle-gated) badge and an always-on silent
    // name — the madd-ʿiwaḍ alef — collapses to one line.
    const names = [...new Set([
        ...badges.filter((b) => isEnabled(b.legendKey)).map((b) => b.tooltip()),
        ...silent,
    ])];
    return names.join('\n');
}

// ── Legend / settings model ───────────────────────────────────────────────────

export interface LegendRow {
    legendKey: string;
    /** Message-function reference — call at the render site so a locale switch re-evaluates it. */
    label: () => string;
    colorVar: string;
    /** length in ḥarakāt (e.g. '2', '4/5'); omitted for rules with no count. */
    duration?: string;
    /** the qalqala kubrā row — its swatch previews the side-wrap geometry. Couples
     *  to the ṣughrā row via the shared `qalqala` legendKey (one colour + one toggle
     *  drive both rows). */
    kubra?: boolean;
    /** a `border`-layer row — its swatch previews the full ring, not a bottom bar. */
    border?: boolean;
}

/** A labelled sub-section within a column (the Noon / Meem split). */
export interface LegendSubgroup {
    title: () => string;
    rows: LegendRow[];
}

export interface LegendGroup {
    category: RuleCategory;
    title: () => string;
    /** Flat row list (Madd, Other). Mutually exclusive with `subgroups`. */
    rows?: LegendRow[];
    /** Labelled sub-sections (Noon / Meem) stacked within one column. */
    subgroups?: LegendSubgroup[];
}

/** Every row of a group, flat — whether it carries `rows` or `subgroups`. */
export function legendRows(group: LegendGroup): LegendRow[] {
    return group.rows ?? group.subgroups?.flatMap((s) => s.rows) ?? [];
}

/** The legend / settings panel structure — one row per legendKey, grouped by
 *  category. Order is the display order. Noon / Meem splits into two stacked
 *  sub-sections: noon (+ ghunnah) rules, then the mīm rules led by the shared
 *  ghunnah (ghunnah governs a sākin noon AND a sākin mīm, so it heads both
 *  sub-sections; the two rows couple colour + toggle via the shared `ghunnah`
 *  legendKey, exactly like qalqala ṣughrā / kubrā). */
export const LEGEND: LegendGroup[] = [
    { category: 'noon_meem', title: m.ts_tajweed_panel_group_title_noon_meem, subgroups: [
        { title: m.ts_tajweed_panel_group_title_noon, rows: [
            { legendKey: 'ghunnah', label: m.ts_tajweed_rule_ghunnah, colorVar: '--tj-ghunnah', duration: '2' },
            { legendKey: 'ikhfaa', label: m.ts_tajweed_rule_ikhfaa, colorVar: '--tj-ikhfaa', duration: '2' },
            { legendKey: 'iqlab', label: m.ts_tajweed_rule_iqlab, colorVar: '--tj-iqlab', duration: '2' },
            { legendKey: 'idgham_ghunnah', label: m.ts_tajweed_rule_idgham_ghunnah, colorVar: '--tj-idgham-ghunnah', duration: '2' },
            { legendKey: 'idgham_bila', label: m.ts_tajweed_rule_idgham_bila_ghunnah, colorVar: '--tj-idgham-bila', duration: '1' },
            { legendKey: 'izhar', label: m.ts_tajweed_rule_izhar_halqi, colorVar: '--tj-izhar-halqi', duration: '1' },
        ] },
        { title: m.ts_tajweed_panel_group_title_meem, rows: [
            { legendKey: 'ghunnah', label: m.ts_tajweed_rule_ghunnah, colorVar: '--tj-ghunnah', duration: '2' },
            { legendKey: 'ikhfaa_shafawi', label: m.ts_tajweed_rule_ikhfaa_shafawi, colorVar: '--tj-ikhfaa-shafawi', duration: '2' },
            { legendKey: 'idgham_shafawi', label: m.ts_tajweed_rule_idgham_shafawi, colorVar: '--tj-idgham-shafawi', duration: '2' },
            { legendKey: 'izhar_shafawi', label: m.ts_tajweed_rule_izhar_shafawi, colorVar: '--tj-izhar-shafawi', duration: '1' },
        ] },
    ] },
    { category: 'madd', title: m.ts_tajweed_panel_group_title_madd, rows: [
        { legendKey: 'madd_lazim', label: m.ts_tajweed_rule_madd_lazim, colorVar: '--tj-madd-lazim', duration: '6' },
        { legendKey: 'madd_wajib', label: m.ts_tajweed_rule_madd_wajib, colorVar: '--tj-madd-wajib', duration: '4/5' },
        { legendKey: 'madd_jaiz', label: m.ts_tajweed_rule_madd_jaiz, colorVar: '--tj-madd-jaiz', duration: '2/4/5' },
        { legendKey: 'madd_arid', label: m.ts_tajweed_rule_madd_arid, colorVar: '--tj-madd-arid', duration: '2/4/6' },
        { legendKey: 'madd_leen', label: m.ts_tajweed_rule_madd_leen, colorVar: '--tj-madd-leen', duration: '2/4/6' },
        { legendKey: 'madd_tabii', label: m.ts_tajweed_rule_madd_tabii, colorVar: '--tj-madd-tabii', duration: '2' },
    ] },
    // Qalqala is two rows (ṣughrā / kubrā) coupled by the shared `qalqala` legendKey —
    // one colour + one toggle drive both; the kubrā row's swatch previews the wrap.
    { category: 'other', title: m.ts_tajweed_panel_group_title_other, rows: [
        { legendKey: 'tafkheem', label: m.ts_tajweed_rule_tafkheem, colorVar: '--tj-tafkheem' },
        { legendKey: 'qalqala', label: m.ts_tajweed_rule_qalqala_sughra, colorVar: '--tj-qalqala' },
        { legendKey: 'qalqala', label: m.ts_tajweed_rule_qalqala_kubra, colorVar: '--tj-qalqala', kubra: true },
        { legendKey: 'mutamathilayn', label: m.ts_tajweed_rule_idgham_mutamathilayn, colorVar: '--tj-mutamathilayn' },
        { legendKey: 'mutaqaribayn', label: m.ts_tajweed_rule_idgham_mutaqaribayn, colorVar: '--tj-mutaqaribayn' },
        { legendKey: 'mutajanisayn', label: m.ts_tajweed_rule_idgham_mutajanisayn, colorVar: '--tj-mutajanisayn' },
        // imāla / ishmām / tashīl / ibdāl al-hamzah share one row: each is rare and
        // each marks the whole grapheme, so one border colour + one toggle serve all.
        { legendKey: 'special', label: m.ts_tajweed_rule_special, colorVar: '--tj-special', border: true },
    ] },
];

/** Every distinct legendKey in display order (qalqala's two rows collapse to one). */
export const LEGEND_KEYS: string[] = [
    ...new Set(LEGEND.flatMap((g) => legendRows(g).map((r) => r.legendKey))),
];

/** First-load enabled state: everything on EXCEPT iẓhar (both) and madd ṭabīʿī. */
const DEFAULT_OFF = new Set(['izhar', 'izhar_shafawi', 'madd_tabii']);
export const DEFAULT_ENABLED: Record<string, boolean> = Object.fromEntries(
    LEGEND_KEYS.map((k) => [k, !DEFAULT_OFF.has(k)]),
);

// ── Legacy colour-map surface (kept derived so it can't drift) ────────────────

/** The `var(--tj-*)` badge colour for a tag, or null if the rule is uncoloured. */
export function tajweedColorVar(tag: string | null | undefined): string | null {
    const def = tag ? (COLOR_RULES as Partial<Record<string, RuleDef>>)[tag] : undefined;
    return def ? `var(${def.colorVar})` : null;
}

/** Cross-word idgham CELL tags — their phoneme renders as a single bridge tile
 *  between two words; the letter row colours both involved letters (source holds
 *  the tag, receiver gets it by `share_group` propagation). The literal array is
 *  typed against `TajweedRule` so a rename surfaces here too. */
const CROSS_WORD_IDGHAM: readonly TajweedRule[] = [
    'idgham_bi_ghunnah',
    'idgham_bila_ghunnah',
    'idgham_shafawi',
    'idgham_mutamathilayn',
    'idgham_mutaqaribayn',
    'idgham_mutajanisayn_kamil',
    'idgham_mutajanisayn_naqis',
];
export const CROSS_WORD_IDGHAM_TAGS: ReadonlySet<string> = new Set(CROSS_WORD_IDGHAM);

/** True for a tag whose phoneme renders as a cross-word bridge (not an inline box). */
export function isBridgeTag(tag: string | null | undefined): boolean {
    return !!tag && CROSS_WORD_IDGHAM_TAGS.has(tag);
}

/** The BRIDGE vocabulary — the rule names a merger phone carries — still splits a
 *  noon rule from its tanwīn twin; a cell tag does not. Fold the two back onto the
 *  one cell tag so a bridge rule resolves in the same registry as everything else. */
const BRIDGE_CELL_TAG: Record<string, TajweedTag> = {
    idgham_ghunnah_noon: 'idgham_bi_ghunnah',
    idgham_ghunnah_tanween: 'idgham_bi_ghunnah',
    idgham_bila_ghunnah_noon: 'idgham_bila_ghunnah',
    idgham_bila_ghunnah_tanween: 'idgham_bila_ghunnah',
};

/** The cell tag naming a merger phone's `bridge` rule (identity for the six that
 *  are spelt the same in both vocabularies). */
export function bridgeCellTag(bridge: string | null | undefined): string | null {
    if (!bridge) return null;
    return BRIDGE_CELL_TAG[bridge] ?? bridge;
}
