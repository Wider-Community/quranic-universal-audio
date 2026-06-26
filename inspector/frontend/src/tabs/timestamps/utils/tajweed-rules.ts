/**
 * The single tajweed-rule registry for the Timestamps analysis row — the "locked
 * table" in code. Maps each phonemizer cell `tag` (and the FE-synthesized iẓhar
 * tags) to its colour, legend grouping, tooltip name, default-on state and stack
 * layer. Everything downstream derives from here so nothing can drift:
 *
 *  - `badgeForTag` / `badgesForTags` — resolve a cell's tag(s) into ordered
 *    underline badges (bottom→top; tafkheem always the top bar).
 *  - `tjShadow` — compose the per-cell `box-shadow` underline from its badges,
 *    filtered by the live enable set (qalqala kubra draws a taller fill).
 *  - `LEGEND` / `DEFAULT_ENABLED` — drive the settings panel + its first-load state.
 *  - `silentTooltip` — name-only hover text for the silent rules (no colour/legend).
 *  - `tajweedColorVar` / `isBridgeTag` / `CROSS_WORD_IDGHAM_TAGS` — the legacy
 *    colour-map surface, kept derived from the registry.
 *
 * Cells carry the canonical tag (phonemizer-owned); the *renderer* owns the
 * palette + visual treatment, mirroring `tajweed-script.ts`. The actual hues live
 * as `--tj-*` CSS custom properties in `styles/base.css` (overridable per-rule at
 * runtime by the settings store).
 */

export type StackLayer = 'base' | 'merge' | 'top';
export type RuleCategory = 'ghunnah' | 'madd' | 'heaviness' | 'idgham';

interface RuleDef {
    /** groups tags into one legend row / enable toggle / colour (e.g. both qalqala
     *  subtypes share `qalqala`; both ghunnah letters share `ghunnah`). */
    legendKey: string;
    /** the `--tj-*` custom property backing this rule's colour. */
    colorVar: string;
    /** hover tooltip name — may differ between tags sharing a legendKey
     *  (qalqala ṣughrā vs kubrā, mutajānisayn kāmil vs nāqiṣ). */
    tooltip: string;
    /** which underline bar this rule occupies when stacked (bottom→top):
     *  `base` (the cell's own rule, e.g. ghunnah) < `merge` (a cross-word idgham
     *  riding ON the target, e.g. mutajānisayn over a ghunnah) < `top` (tafkheem). */
    stack: StackLayer;
}

/** Every tag that draws a coloured underline → its rule definition. Tags sharing a
 *  `legendKey` share colour + toggle but keep their own tooltip. */
const COLOR_RULES: Record<string, RuleDef> = {
    // ── Ghunnah / nasalization ────────────────────────────────────────────────
    noon_ghunnah: { legendKey: 'ghunnah', colorVar: '--tj-ghunnah', tooltip: 'Ghunnah', stack: 'base' },
    meem_ghunnah: { legendKey: 'ghunnah', colorVar: '--tj-ghunnah', tooltip: 'Ghunnah', stack: 'base' },
    ikhfaa_noon: { legendKey: 'ikhfaa', colorVar: '--tj-ikhfaa', tooltip: 'Ikhfaa', stack: 'base' },
    ikhfaa_tanween: { legendKey: 'ikhfaa', colorVar: '--tj-ikhfaa', tooltip: 'Ikhfaa', stack: 'base' },
    ikhfaa_shafawi: { legendKey: 'ikhfaa_shafawi', colorVar: '--tj-ikhfaa-shafawi', tooltip: 'Ikhfaa Shafawi', stack: 'base' },
    iqlab_noon: { legendKey: 'iqlab', colorVar: '--tj-iqlab', tooltip: 'Iqlab', stack: 'base' },
    iqlab_tanween: { legendKey: 'iqlab', colorVar: '--tj-iqlab', tooltip: 'Iqlab', stack: 'base' },
    idgham_ghunnah_noon: { legendKey: 'idgham_ghunnah', colorVar: '--tj-idgham-ghunnah', tooltip: 'Idgham Ghunnah', stack: 'base' },
    idgham_ghunnah_tanween: { legendKey: 'idgham_ghunnah', colorVar: '--tj-idgham-ghunnah', tooltip: 'Idgham Ghunnah', stack: 'base' },
    idgham_shafawi: { legendKey: 'idgham_shafawi', colorVar: '--tj-idgham-shafawi', tooltip: 'Idgham Shafawi', stack: 'base' },
    // ── Madd ──────────────────────────────────────────────────────────────────
    madd_lazim: { legendKey: 'madd_lazim', colorVar: '--tj-madd-lazim', tooltip: 'Madd Lazim', stack: 'base' },
    madd_wajib_muttasil: { legendKey: 'madd_wajib', colorVar: '--tj-madd-wajib', tooltip: 'Madd Wajib Muttasil', stack: 'base' },
    madd_jaiz_munfasil: { legendKey: 'madd_jaiz', colorVar: '--tj-madd-jaiz', tooltip: "Madd Ja'iz Munfassil", stack: 'base' },
    madd_arid_lissukun: { legendKey: 'madd_arid', colorVar: '--tj-madd-arid', tooltip: "Madd 'Arid-lissukun", stack: 'base' },
    madd_leen: { legendKey: 'madd_leen', colorVar: '--tj-madd-leen', tooltip: 'Madd Leen', stack: 'base' },
    // ṭabīʿī + its structural aliases (the dagger-alef of Allah, the ʿiwaḍ alef)
    madd_tabii: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: "Madd Tabi'i", stack: 'base' },
    allah_dagger_alef: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: "Madd Tabi'i", stack: 'base' },
    madd_iwad: { legendKey: 'madd_tabii', colorVar: '--tj-madd-tabii', tooltip: "Madd 'Iwad", stack: 'base' },
    // ── Heaviness ─────────────────────────────────────────────────────────────
    tafkheem: { legendKey: 'tafkheem', colorVar: '--tj-tafkheem', tooltip: 'Tafkheem', stack: 'top' },
    qalqala_sughra: { legendKey: 'qalqala', colorVar: '--tj-qalqala', tooltip: 'Qalqala Sughra', stack: 'base' },
    qalqala_kubra: { legendKey: 'qalqala', colorVar: '--tj-qalqala', tooltip: 'Qalqala Kubra', stack: 'base' },
    // ── Idgham (silent merges) ────────────────────────────────────────────────
    idgham_bila_ghunnah_noon: { legendKey: 'idgham_bila', colorVar: '--tj-idgham-bila', tooltip: 'Idgham bila Ghunnah', stack: 'base' },
    idgham_bila_ghunnah_tanween: { legendKey: 'idgham_bila', colorVar: '--tj-idgham-bila', tooltip: 'Idgham bila Ghunnah', stack: 'base' },
    // The consonant idghams ride the `merge` layer — they sit ABOVE the target's own
    // base rule (e.g. a ghunnah on the receiving mīm of ٱرْكَب مَّعَنَا) and below tafkheem.
    idgham_mutamathilayn: { legendKey: 'mutamathilayn', colorVar: '--tj-mutamathilayn', tooltip: 'Idgham Mutamathilayn', stack: 'merge' },
    idgham_mutaqaribayn: { legendKey: 'mutaqaribayn', colorVar: '--tj-mutaqaribayn', tooltip: 'Idgham Mutaqaribayn', stack: 'merge' },
    idgham_mutajanisayn_kamil: { legendKey: 'mutajanisayn', colorVar: '--tj-mutajanisayn', tooltip: 'Idgham Mutajanisayn Kamil', stack: 'merge' },
    idgham_mutajanisayn_naqis: { legendKey: 'mutajanisayn', colorVar: '--tj-mutajanisayn', tooltip: 'Idgham Mutajanisayn Naqis', stack: 'merge' },
    // ── Iẓhar (FE-synthesized fallback for a sounding sākin noon/meem/tanwīn) ──
    izhar_halqi: { legendKey: 'izhar', colorVar: '--tj-izhar-halqi', tooltip: 'Izhar Halqi', stack: 'base' },
    izhar_shafawi: { legendKey: 'izhar_shafawi', colorVar: '--tj-izhar-shafawi', tooltip: 'Izhar Shafawi', stack: 'base' },
};

/** Silent rules — hover tooltip only, no colour and no legend row. */
const SILENT_TOOLTIPS: Record<string, string> = {
    vowel_silent: 'Silent vowel',
    hamza_wasl_silent: 'Hamzat-al-wasl (silent)',
    lam_shamsiyah: 'Lam Shamsiyyah',
    silent_iltiqaa_sakinayn: "Iltiqa' 'as-sakinayn",
    iltiqaa_kasra: "Iltiqa' 'as-sakinayn",
    iltiqaa: "Iltiqa' 'as-sakinayn",
    // The ن of an iqlab noon falls silent (the synthesized mini-meem owns the
    // nasal + the lone underline) — name it on hover, draw no bar.
    iqlab_silent_noon: 'Iqlab',
};

/** One resolved underline badge a cell carries (settings-independent). */
export interface TjBadge {
    legendKey: string;
    colorVar: string; // bare custom-property name, e.g. '--tj-tafkheem'
    tooltip: string;
    stack: StackLayer;
    /** qalqala kubrā — draws a taller (≈30% cell-height) fill instead of a thin bar. */
    kubra: boolean;
}

/** Resolve one tag into its badge, or null if the tag draws no underline. */
export function badgeForTag(tag: string | null | undefined): TjBadge | null {
    if (!tag) return null;
    const def = COLOR_RULES[tag];
    if (!def) return null;
    return { ...def, kubra: tag === 'qalqala_kubra' };
}

/** Resolve a cell's candidate tags into its ordered underline stack (bottom→top):
 *  at most one `base` bar (the first colourable base rule in tag order — a cell's
 *  own tag wins over a propagated one), one `merge` bar (a cross-word idgham riding
 *  on the target), and tafkheem on top. Empty when no tag is colourable. */
export function badgesForTags(tags: (string | null | undefined)[]): TjBadge[] {
    let base: TjBadge | null = null;
    let merge: TjBadge | null = null;
    let top: TjBadge | null = null;
    for (const t of tags) {
        const b = badgeForTag(t);
        if (!b) continue;
        if (b.stack === 'top') top ??= b;
        else if (b.stack === 'merge') merge ??= b;
        else base ??= b;
    }
    const out: TjBadge[] = [];
    if (base) out.push(base);
    if (merge) out.push(merge);
    if (top) out.push(top);
    return out;
}

/** The silent-rule hover name for a tag (the named silent rules + the iltiqaa
 *  kasra), or null. Independent of the colour/legend set. */
export function silentTooltip(tag: string | null | undefined): string | null {
    return tag ? (SILENT_TOOLTIPS[tag] ?? null) : null;
}

// ── Underline geometry ────────────────────────────────────────────────────────

/** Thin bar thickness (px) for a normal underline / each stacked layer. */
const BAR_PX = 2;

/**
 * Compose the per-cell underline `box-shadow` from its badges, keeping only the
 * rules whose legend toggle is enabled. Stacked inset bottom-shadows accumulate
 * from the cell's bottom edge upward — the base rule is the lowest bar, tafkheem
 * the bar above it. A qalqala-**kubrā** bar draws its bottom edge here exactly like
 * ṣughrā (same inset bottom-shadow, hugging the cell's rounded corners); only its
 * short side-wraps are added separately via the `::after` (see `tjKubraColor`).
 * Empty string when no enabled badge draws an inset bar. Uses the inset-box-shadow
 * channel so bars survive the `.active` fill.
 */
export function tjShadow(badges: TjBadge[], isEnabled: (legendKey: string) => boolean): string {
    let offset = 0;
    const shadows: string[] = [];
    for (const b of badges) {
        if (!isEnabled(b.legendKey)) continue;
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
        ...badges.filter((b) => isEnabled(b.legendKey)).map((b) => b.tooltip),
        ...silent,
    ])];
    return names.join('\n');
}

// ── Legend / settings model ───────────────────────────────────────────────────

export interface LegendRow {
    legendKey: string;
    label: string;
    colorVar: string;
    /** length in ḥarakāt (e.g. '2', '4/5'); omitted for rules with no count. */
    duration?: string;
    /** the qalqala row renders two demo cells (ṣughrā bar vs kubrā fill). */
    demo?: 'qalqala';
}

export interface LegendGroup {
    category: RuleCategory;
    title: string;
    rows: LegendRow[];
}

/** The legend / settings panel structure — one row per legendKey, grouped by
 *  category. Order is the display order. */
export const LEGEND: LegendGroup[] = [
    { category: 'ghunnah', title: 'Ghunnah', rows: [
        { legendKey: 'ghunnah', label: 'Ghunnah', colorVar: '--tj-ghunnah', duration: '2' },
        { legendKey: 'ikhfaa', label: 'Ikhfaa', colorVar: '--tj-ikhfaa', duration: '2' },
        { legendKey: 'ikhfaa_shafawi', label: 'Ikhfaa Shafawi', colorVar: '--tj-ikhfaa-shafawi', duration: '2' },
        { legendKey: 'iqlab', label: 'Iqlab', colorVar: '--tj-iqlab', duration: '2' },
        { legendKey: 'idgham_ghunnah', label: 'Idgham Ghunnah', colorVar: '--tj-idgham-ghunnah', duration: '2' },
        { legendKey: 'idgham_shafawi', label: 'Idgham Shafawi', colorVar: '--tj-idgham-shafawi', duration: '2' },
        { legendKey: 'izhar', label: 'Izhar Halqi', colorVar: '--tj-izhar-halqi', duration: '1' },
        { legendKey: 'izhar_shafawi', label: 'Izhar Shafawi', colorVar: '--tj-izhar-shafawi', duration: '1' },
    ] },
    { category: 'madd', title: 'Madd', rows: [
        { legendKey: 'madd_lazim', label: 'Madd Lazim', colorVar: '--tj-madd-lazim', duration: '6' },
        { legendKey: 'madd_wajib', label: 'Madd Wajib Muttasil', colorVar: '--tj-madd-wajib', duration: '4/5' },
        { legendKey: 'madd_jaiz', label: "Madd Ja'iz Munfassil", colorVar: '--tj-madd-jaiz', duration: '2/4/5' },
        { legendKey: 'madd_arid', label: "'Arid-lissukun", colorVar: '--tj-madd-arid', duration: '2/4/6' },
        { legendKey: 'madd_leen', label: 'Madd Leen', colorVar: '--tj-madd-leen', duration: '2/4/6' },
        { legendKey: 'madd_tabii', label: "Madd Tabi'i", colorVar: '--tj-madd-tabii', duration: '2' },
    ] },
    { category: 'heaviness', title: 'Heaviness', rows: [
        { legendKey: 'tafkheem', label: 'Tafkheem', colorVar: '--tj-tafkheem' },
        { legendKey: 'qalqala', label: 'Qalqala', colorVar: '--tj-qalqala', demo: 'qalqala' },
    ] },
    { category: 'idgham', title: 'Idgham', rows: [
        { legendKey: 'idgham_bila', label: 'Bila Ghunnah', colorVar: '--tj-idgham-bila' },
        { legendKey: 'mutamathilayn', label: 'Mutamathilayn', colorVar: '--tj-mutamathilayn' },
        { legendKey: 'mutaqaribayn', label: 'Mutaqaribayn', colorVar: '--tj-mutaqaribayn' },
        { legendKey: 'mutajanisayn', label: 'Mutajanisayn', colorVar: '--tj-mutajanisayn' },
    ] },
];

/** Every legendKey in display order. */
export const LEGEND_KEYS: string[] = LEGEND.flatMap((g) => g.rows.map((r) => r.legendKey));

/** First-load enabled state: everything on EXCEPT iẓhar (both) and madd ṭabīʿī. */
const DEFAULT_OFF = new Set(['izhar', 'izhar_shafawi', 'madd_tabii']);
export const DEFAULT_ENABLED: Record<string, boolean> = Object.fromEntries(
    LEGEND_KEYS.map((k) => [k, !DEFAULT_OFF.has(k)]),
);

// ── Legacy colour-map surface (kept derived so it can't drift) ────────────────

/** The `var(--tj-*)` badge colour for a tag, or null if the rule is uncoloured. */
export function tajweedColorVar(tag: string | null | undefined): string | null {
    const def = tag ? COLOR_RULES[tag] : undefined;
    return def ? `var(${def.colorVar})` : null;
}

/** Cross-word idgham tags — their phoneme renders as a single bridge tile between
 *  two words; the letter row colours both involved letters (source holds the tag,
 *  receiver gets it by `share_group` propagation). */
export const CROSS_WORD_IDGHAM_TAGS: ReadonlySet<string> = new Set([
    'idgham_ghunnah_noon',
    'idgham_ghunnah_tanween',
    'idgham_bila_ghunnah_noon',
    'idgham_bila_ghunnah_tanween',
    'idgham_shafawi',
    'idgham_mutamathilayn',
    'idgham_mutaqaribayn',
    'idgham_mutajanisayn_kamil',
    'idgham_mutajanisayn_naqis',
]);

/** True for a tag whose phoneme renders as a cross-word bridge (not an inline box). */
export function isBridgeTag(tag: string | null | undefined): boolean {
    return !!tag && CROSS_WORD_IDGHAM_TAGS.has(tag);
}
