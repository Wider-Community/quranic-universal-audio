/**
 * Accent Lab — the per-surface toggle catalogue + colour helpers.
 *
 * Dev-only playground (see `AccentLab.svelte`). Each toggle, when on, contributes
 * a block of CSS that recolours one live footer/player/filmstrip/teleprompter
 * surface from the fixed cyan `--accent` theme token to the picked lab colour.
 * Rules are STATIC strings that reference the lab CSS variables the panel sets on
 * the document root, so changing the colour only updates those vars — the
 * stylesheet text is rebuilt solely when toggles flip.
 *
 * Precedence: every rule is prefixed `body.accent-lab` so it beats Svelte's
 * scoped component styles without `!important` (the one exception is the
 * teleprompter `--ra-highlight`, which is set inline on `.ra-line` and so needs
 * `!important` to override). Disabled toggles simply omit their block, so Reset =
 * empty sheet = the real cyan tokens (never repainted, just un-overridden).
 *
 * Pure module — no DOM, no Svelte. Mirrors the `--accent*` ramp in
 * `styles/tokens.css` (tint 14% / tint-soft 7% / strong = lighten).
 */

export interface LabToggle {
    id: string;
    group: string;
    /** Short technical label (rendered in the mono toggle list). */
    label: string;
    /** CSS injected while the toggle is on. */
    css: string;
}

export const LAB_GROUPS = ['Filmstrip', 'Footer', 'Verse marker', 'Teleprompter', 'Global'] as const;

/**
 * Derived lab tints, defined once in the injected sheet so they track `--lab`.
 * `--lab` (the hex) and `--lab-ink` (auto-contrast) are set imperatively by the
 * panel; these three are pure CSS derivations of `--lab`.
 */
export const LAB_DERIVED_VARS =
    ':root{'
    + '--lab-strong:color-mix(in oklab, var(--lab) 85%, white);'
    + '--lab-tint:color-mix(in srgb, var(--lab) 14%, transparent);'
    + '--lab-tint-soft:color-mix(in srgb, var(--lab) 7%, transparent);'
    + '}';

const P = 'body.accent-lab';

export const LAB_TOGGLES: LabToggle[] = [
    // ---- Filmstrip ----
    {
        id: 'fs-cells',
        group: 'Filmstrip',
        label: 'Cells',
        css: `${P} .filmstrip .cell.active{border-color:var(--lab);background:var(--lab-tint-soft);}`
            + `${P} .filmstrip .cell.cursor{border-color:var(--lab);box-shadow:inset 0 0 0 1px var(--lab);}`
            + `${P} .filmstrip .cell.preview{border-color:var(--lab-strong);background:var(--lab-tint);}`,
    },
    {
        id: 'fs-needle',
        group: 'Filmstrip',
        label: 'Needle',
        // `:not(.silent)` so a silence-greyed needle stays muted.
        css: `${P} .filmstrip .needle:not(.silent){background:var(--lab);`
            + 'box-shadow:0 0 8px color-mix(in srgb, var(--lab) 35%, transparent);}',
    },
    {
        id: 'fs-fill',
        group: 'Filmstrip',
        label: 'Fill bar',
        css: `${P} .filmstrip .cell-fill{background:var(--lab-tint);}`
            + `${P} .filmstrip .cell.reached .cell-fill{background:var(--lab-tint-soft);}`,
    },
    {
        id: 'fs-num',
        group: 'Filmstrip',
        label: 'Cell number',
        css: `${P} .filmstrip .cell.active .cell-num{color:var(--lab);}`
            + `${P} .filmstrip .cell.preview .cell-num{color:var(--lab-strong);}`,
    },
    // ---- Footer / transport ----
    {
        id: 'pl-play',
        group: 'Footer',
        label: 'Play button',
        css: `${P} .btn.primary{background:var(--lab);color:var(--lab-ink);}`
            + `${P} .btn.primary:hover{background:var(--lab-strong);color:var(--lab-ink);}`,
    },
    {
        id: 'pl-progress',
        group: 'Footer',
        label: 'Progress bar',
        css: `${P} .progress .fill{background:var(--lab);}`
            + `${P} .progress .thumb{background:var(--lab);}`,
    },
    {
        id: 'ft-toggles',
        group: 'Footer',
        label: 'Toggle on-states',
        css: `${P} .icon-btn.on{color:var(--lab);background:var(--lab-tint);}`
            + `${P} .shuffle-btn.on{color:var(--lab);background:var(--lab-tint);border-color:var(--lab);}`
            + `${P} .tg-btn.on{color:var(--lab);}`
            + `${P} .tg-opt.sel{color:var(--lab);}`,
    },
    {
        id: 'ft-bookmark',
        group: 'Footer',
        label: 'Bookmark',
        css: `${P} .strip-bm-btn.on{color:var(--lab);background:var(--lab-tint);}`,
    },
    // ---- Verse marker (teleprompter ۝ + number) ----
    {
        id: 'vm-glyph',
        group: 'Verse marker',
        label: 'Marker glyph',
        css: `${P} .ra-ayah-marker .ay-glyph{color:var(--lab);}`,
    },
    {
        id: 'vm-num',
        group: 'Verse marker',
        label: 'Marker number',
        css: `${P} .ra-ayah-marker .ay-num{color:var(--lab);}`,
    },
    {
        id: 'vm-border',
        group: 'Verse marker',
        label: 'Marker border',
        css: `${P} .ra-ayah-marker{border:1px solid color-mix(in srgb, var(--lab) 55%, transparent);`
            + 'border-radius:4px;padding:0 4px;}',
    },
    // ---- Teleprompter ----
    {
        id: 'tp-active',
        group: 'Teleprompter',
        label: 'Active word',
        // `--ra-highlight` is set inline on `.ra-line`; only `!important` overrides it.
        css: `${P} .ra-line{--ra-highlight:var(--lab) !important;--ra-glow:0 0 5px var(--lab) !important;}`,
    },
    // ---- Global ----
    {
        id: 'gl-hovers',
        group: 'Global',
        label: 'Picker hovers',
        css: `${P} .opt:hover{background:var(--lab-tint-soft);}`
            + `${P} .opt.active{background:var(--lab-tint);}`,
    },
    {
        id: 'gl-focus',
        group: 'Global',
        label: 'Focus rings',
        css: `${P} :focus-visible{outline-color:var(--lab);}`,
    },
];

export const LAB_TOGGLE_IDS: string[] = LAB_TOGGLES.map((t) => t.id);

/** Build the full injected stylesheet from the set of enabled toggle ids. */
export function buildLabSheet(enabled: Set<string>): string {
    const blocks = LAB_TOGGLES.filter((t) => enabled.has(t.id)).map((t) => t.css);
    if (!blocks.length) return '';
    return LAB_DERIVED_VARS + blocks.join('');
}

// ---- auto-contrast ink (self-hosted; WCAG-2 relative luminance) ----

const DARK_INK = '#15151f';
const LIGHT_INK = '#ffffff';
// Black/white crossover: √0.0525 − 0.05 ≈ 0.17913 (contrast-optimal, not 0.5).
const INK_CROSSOVER = Math.sqrt(0.0525) - 0.05;

function srgbToLinear(c8: number): number {
    const c = c8 / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Pick a legible ink (near-black or white) for text on a fill of `hex`. */
export function inkFor(hex: string): string {
    const h = hex.trim().replace(/^#/, '');
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
    if (full.length !== 6 || /[^0-9a-fA-F]/.test(full)) return DARK_INK;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    const lum = 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
    return lum > INK_CROSSOVER ? DARK_INK : LIGHT_INK;
}
