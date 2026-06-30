<script lang="ts">
    /**
     * Tajweed legend + per-rule settings drop-up for the Timestamps footer. A 2×2
     * grid centred under the player's play button — Noon/Meem and Madd on top,
     * Other rules and the Waqf stop-sign key on the bottom. Each rule row is a
     * colour chip (click → native colour picker, live recolour, hover reveals a
     * dropper) with a mini enable toggle, label and ḥarakāt duration. Each group
     * header (Noon / Meem / Madd / Other) carries a switch that quick-disables the
     * whole group and restores the previously-enabled set on re-enable; it reads as
     * on whenever any member rule is on. Ghunnah heads both Noon and Meem (it governs
     * a sākin noon and a sākin mīm) — the two rows couple colour + toggle via the
     * shared `ghunnah` key. Qalqala is two coupled rows (ṣughrā / kubrā) sharing the
     * `qalqala` key, the kubrā chip previewing the side-wrap. The Other quadrant closes with two non-interactive
     * keys explaining the dashed (sounded-but-unwritten) and greyed (written-but-
     * silent) cells; the Waqf quadrant lists the five mushaf pause marks, each in a
     * real analysis cell with the shared per-glyph calibration. All state lives in
     * the `tajweed-settings` store; colours apply via `--tj-*` overrides, toggles
     * drive the per-cell underline.
     */
    import { themeStore } from '../../../lib/stores/theme.svelte';
    import { harakaRenderStyle } from '../utils/haraka-render';
    import { LEGEND, type LegendRow } from '../utils/tajweed-rules';
    import {
        isGroupEnabled,
        resetAllTajweed,
        setGroupEnabled,
        setRuleColor,
        setRuleEnabled,
        tajweedSettings,
    } from '../stores/tajweed-settings';
    import { waqfRenderStyle } from '../utils/waqf-render';

    /** Distinct legendKeys of a row list, in order — the set a group toggle drives
     *  (qalqala's two rows collapse to one key). */
    const keysOf = (rows: LegendRow[]): string[] => [...new Set(rows.map((r) => r.legendKey))];

    // The two dashed-haraka exemplars in the Other-rules key, positioned with the
    // real per-glyph calibration (damma U+064F pinned above, kasra U+0650 below).
    const DAMMA = 'ُ';
    const KASRA = 'ِ';

    // Waqf stop-sign key — the mushaf pause marks, each shown in a real analysis
    // cell via the shared per-glyph calibration (`waqfRenderStyle`). Ordered from
    // the most permissive (stop or continue) to the prohibition, closing with the
    // muʿānaqah pair (`pair` → two marks in one cell) where exactly one of the two
    // is a stop.
    const WAQF_KEYS: { mark: string; label: string; pair?: boolean }[] = [
        { mark: 'ۚ', label: 'Stop or Continue' }, // ۚ jīm (jāʾiz)
        { mark: 'ۗ', label: 'Better to Stop' }, // ۗ qila (al-waqf awlā)
        { mark: 'ۖ', label: 'Better to Continue' }, // ۖ ṣala (al-waṣl awlā)
        { mark: 'ۘ', label: 'Must Stop' }, // ۘ mīm (lāzim)
        { mark: 'ۙ', label: 'Should Not Stop' }, // ۙ lā
        { mark: 'ۛ', label: 'Stop at one only', pair: true }, // ۛ muʿānaqah
    ];

    // 2×2 placement: Noon/Meem + Other rules on top, Madd + Waqf on the bottom.
    // Madd and Waqf both carry six rows, so the bottom row aligns row-for-row.
    const COL_ORDER: Record<string, number> = { noon_meem: 0, other: 1, madd: 2 };
    const orderedGroups = [...LEGEND].sort(
        (a, b) => (COL_ORDER[a.category] ?? 99) - (COL_ORDER[b.category] ?? 99),
    );

    // Hidden native colour inputs, one per row, opened by clicking its chip.
    let inputs: Record<string, HTMLInputElement | undefined> = $state({});

    /** Normalise any CSS colour (oklch / rgb / hex / named) to a `#rrggbb` the native
     *  `<input type=color>` accepts. Paints one pixel and reads its sRGB bytes — the
     *  canvas `fillStyle` *getter* serialises modern `oklch(...)` back as `oklch(...)`,
     *  so a string round-trip would miss; the painted pixel is always sRGB. */
    function cssColorToHex(input: string): string {
        const s = input.trim();
        if (/^#[0-9a-f]{6}$/i.test(s)) return s;
        try {
            const ctx = document.createElement('canvas').getContext('2d');
            if (ctx) {
                ctx.fillStyle = '#000000';
                ctx.fillStyle = s;
                ctx.fillRect(0, 0, 1, 1);
                const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
                return '#' + [r, g, b].map((x) => (x ?? 0).toString(16).padStart(2, '0')).join('');
            }
        } catch {
            /* unsupported parse — fall through */
        }
        return '#888888';
    }

    /** The document root's computed style, re-read only when an override changes
     *  (the sole mutator of the `--tj-*` vars) — hoisted so the chip loop reads it
     *  once per pass instead of calling getComputedStyle per row. */
    const rootStyle = $derived.by(() => {
        void $tajweedSettings;
        void themeStore.current; // re-read the --tj-* vars after a theme flip
        return typeof document !== 'undefined' ? getComputedStyle(document.documentElement) : null;
    });

    /** The rule's current effective colour as hex (override, else the live CSS var). */
    function effectiveHex(row: LegendRow): string {
        const override = $tajweedSettings[row.legendKey]?.color;
        if (override) return override;
        const raw = rootStyle?.getPropertyValue(row.colorVar) ?? '';
        return cssColorToHex(raw || '#888888');
    }
</script>

<div class="tjs">
    <div class="tjs-head">
        <span class="tjs-title"
            >Tajweed rules <span class="tjs-sub">(hover a cell for rule details)</span></span
        >
        <button type="button" class="tjs-reset" onclick={() => resetAllTajweed()}>Reset all</button>
    </div>

    {#snippet ruleRow(row: LegendRow)}
        {@const on = $tajweedSettings[row.legendKey]?.enabled ?? true}
        <div class="tjs-row" class:off={!on}>
            <div class="tjs-control">
                <button
                    type="button"
                    class="tjs-swatch"
                    class:kubra={row.kubra}
                    style:--sw={`var(${row.colorVar})`}
                    title="Change colour"
                    onclick={() => inputs[row.label]?.click()}
                >
                    {#if row.kubra}
                        <span class="kl"></span><span class="kr"></span>
                    {/if}
                    <span class="tjs-dropper" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="8" height="8">
                            <path
                                d="M6 18 L14 10 L16.5 12.5 L8.5 20.5 H6 Z M15 9 L17 7 A1.4 1.4 0 0 1 19 9 L17 11 Z"
                                fill="currentColor"
                            />
                        </svg>
                    </span>
                </button>
                <input
                    bind:this={inputs[row.label]}
                    type="color"
                    class="tjs-color-input"
                    value={effectiveHex(row)}
                    oninput={(e) => setRuleColor(row.legendKey, e.currentTarget.value)}
                    tabindex="-1"
                    aria-hidden="true"
                />
                <button
                    type="button"
                    class="tjs-toggle"
                    class:on
                    role="switch"
                    aria-checked={on}
                    aria-label={`${row.label} ${on ? 'on' : 'off'}`}
                    onclick={() => setRuleEnabled(row.legendKey, !on)}
                ><span class="knob"></span></button>
            </div>
            <span class="tjs-label">{row.label}</span>
            {#if row.duration}<span class="tjs-dur">[{row.duration}]</span>{/if}
        </div>
    {/snippet}

    {#snippet groupHead(title: string, keys: string[])}
        {@const on = isGroupEnabled($tajweedSettings, keys)}
        <h4 class="tjs-h4">
            <span>{title}</span>
            <button
                type="button"
                class="tjs-toggle tjs-grp-toggle"
                class:on
                role="switch"
                aria-checked={on}
                aria-label={`Turn all ${title} rules ${on ? 'off' : 'on'}`}
                title={on ? 'Disable all in group' : 'Enable all in group'}
                onclick={() => setGroupEnabled(title, keys, !on)}
            ><span class="knob"></span></button>
        </h4>
    {/snippet}

    <div class="tjs-cols">
        {#each orderedGroups as group (group.title)}
            <section class="tjs-group fill">
                {#if group.subgroups}
                    <!-- Noon / Meem: two sub-sections, each its own header, distributed to fill height. -->
                    <div class="tjs-body">
                        {#each group.subgroups as sg (sg.title)}
                            <div class="tjs-subsec">
                                {@render groupHead(sg.title, keysOf(sg.rows))}
                                {#each sg.rows as row (row.label)}
                                    {@render ruleRow(row)}
                                {/each}
                            </div>
                        {/each}
                    </div>
                {:else if group.category === 'other'}
                    {@render groupHead(group.title, keysOf(group.rows ?? []))}
                    <div class="tjs-body">
                        {#each group.rows ?? [] as row (row.label)}
                            {@render ruleRow(row)}
                        {/each}
                    </div>
                {:else}
                    {@render groupHead(group.title, keysOf(group.rows ?? []))}
                    <div
                        class="tjs-body"
                        class:rows-6={(group.rows?.length ?? 0) === WAQF_KEYS.length}
                    >
                        {#each group.rows ?? [] as row (row.label)}
                            {@render ruleRow(row)}
                        {/each}
                    </div>
                {/if}

                {#if group.category === 'other'}
                    <div class="tjs-key">
                        <div class="tjs-key-row">
                            <span class="tjs-key-cells">
                                <span class="kcell big dashed">ا</span>
                                <span class="kdia">
                                    <span class="kharaka pin-top dashed">
                                        <span class="kg" style={harakaRenderStyle(DAMMA)}>{DAMMA}</span>
                                    </span>
                                    <span class="kharaka pin-bottom dashed">
                                        <span class="kg" style={harakaRenderStyle(KASRA)}>{KASRA}</span>
                                    </span>
                                </span>
                            </span>
                            <span class="kcap">Pronounced but unwritten/transformed</span>
                        </div>
                        <div class="tjs-key-row">
                            <span class="tjs-key-cells">
                                <span class="kcell big silent">ٱ</span>
                            </span>
                            <span class="kcap">Written but silent</span>
                        </div>
                    </div>
                {/if}
            </section>
        {/each}

        <section class="tjs-group tjs-waqf fill">
            <h4>Waqf · stop signs</h4>
            <div class="waqf-body rows-6">
                {#each WAQF_KEYS as wk (wk.label)}
                    <div class="waqf-row">
                        <span class="waqf-cell" class:pair={wk.pair}>
                            <span class="waqf-mark" style={waqfRenderStyle(wk.mark)}>{wk.mark}</span>
                            {#if wk.pair}
                                <span class="waqf-mark" style={waqfRenderStyle(wk.mark)}>{wk.mark}</span>
                            {/if}
                        </span>
                        <span class="waqf-cap">{wk.label}</span>
                    </div>
                {/each}
            </div>
        </section>
    </div>
</div>

<style>
    .tjs {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        min-width: 600px;
        max-width: 760px;
    }
    .tjs-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        padding-bottom: var(--s-1);
        border-bottom: 1px solid var(--border-quiet);
    }
    .tjs-title {
        font-size: var(--fs-meta);
        font-weight: 600;
        color: var(--text-primary);
        white-space: nowrap;
    }
    .tjs-sub {
        font-weight: 400;
        color: var(--text-muted);
        font-size: 11px;
    }
    .tjs-reset {
        font-size: 10px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 1px 7px;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .tjs-reset:hover {
        color: var(--text-primary);
        border-color: var(--border-default);
    }
    /* 2×2: Noon/Meem + Other rules on top, Madd + Waqf key on the bottom (Madd and
       Waqf both carry six rows so the bottom row aligns). Rows size to content —
       the top row runs taller than the bottom, which keeps every quadrant roomy
       rather than forcing one to stretch. The column gap lands under the player's
       play button (see `centerOnPlay`). */
    .tjs-cols {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--s-3);
        align-items: stretch;
    }
    .tjs-group {
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: var(--s-2) var(--s-3);
    }
    .tjs-group h4 {
        margin: 0 0 var(--s-2);
        padding-bottom: var(--s-1);
        font-size: var(--fs-meta);
        color: var(--text-primary);
        border-bottom: 1px solid var(--border-quiet);
    }
    /* Group header carrying the quick-disable switch — title left, toggle right. */
    .tjs-h4 {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--s-2);
    }
    .tjs-grp-toggle {
        flex: 0 0 auto;
    }
    /* Every column fills the shared (tallest-column) height: the body grows and
       distributes its rows + sub-headers with even vertical spacing. In the Other
       column the body grows to pin its dashed/silent key block to the bottom. */
    .tjs-group.fill {
        display: flex;
        flex-direction: column;
    }
    .tjs-body {
        display: flex;
        flex-direction: column;
    }
    .tjs-group.fill .tjs-body {
        flex: 1 1 auto;
        justify-content: space-between;
        /* Baseline gap so the tallest fill column (which has no slack to
           distribute) still breathes; shorter columns spread beyond it. */
        gap: 5px;
    }
    /* Madd + Waqf share a row and both carry six entries: render each body as six
       equal tracks so the columns align entry-for-entry despite Madd's short rule
       rows and Waqf's taller glyph cells (each entry centres in its track). */
    .tjs-group.fill .tjs-body.rows-6,
    .tjs-group.fill .waqf-body.rows-6 {
        display: grid;
        /* Full-width single column so each row stretches edge-to-edge (the rule
           duration stays snapped to the right edge); six equal tracks for the
           Madd↔Waqf row alignment. */
        grid-template-columns: minmax(0, 1fr);
        grid-template-rows: repeat(6, 1fr);
        gap: 0;
    }
    .tjs-group.fill .tjs-row {
        margin-bottom: 0;
    }
    /* Noon / Meem sub-sections — each headed by its own h4 (no redundant column
       header); the two blocks distribute top/bottom to fill the column. */
    .tjs-subsec {
        display: flex;
        flex-direction: column;
        gap: 5px;
    }
    .tjs-subsec h4 {
        margin: 0;
    }
    .tjs-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        margin-bottom: 4px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        white-space: nowrap;
        transition: opacity var(--t-fast);
    }
    .tjs-row.off {
        opacity: 0.45;
    }
    .tjs-control {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: var(--s-1);
        flex: 0 0 auto;
    }
    /* Colour chip: a tint of the rule's hue with its underline bar at the bottom,
       so it reads as both the colour and a preview of the bar. Hover → accent ring
       + a dropper badge so recolouring is obviously available. */
    .tjs-swatch {
        position: relative;
        width: 26px;
        height: 16px;
        padding: 0;
        border: 1px solid var(--border-default);
        border-radius: var(--r-1);
        background: color-mix(in oklch, var(--sw) 17%, var(--canvas-inset));
        box-shadow: inset 0 -3px 0 var(--sw);
        cursor: pointer;
        transition: box-shadow var(--t-fast), border-color var(--t-fast);
    }
    .tjs-swatch:hover {
        border-color: var(--accent);
        box-shadow: inset 0 -3px 0 var(--sw), 0 0 0 2px var(--accent-tint);
    }
    /* kubrā preview: short side-wraps curling up the chip's bottom corners. */
    .tjs-swatch.kubra .kl,
    .tjs-swatch.kubra .kr {
        position: absolute;
        bottom: 0;
        width: 2px;
        height: 7px;
        background: var(--sw);
    }
    .tjs-swatch.kubra .kl {
        left: 0;
        border-bottom-left-radius: 3px;
    }
    .tjs-swatch.kubra .kr {
        right: 0;
        border-bottom-right-radius: 3px;
    }
    .tjs-dropper {
        position: absolute;
        top: -6px;
        right: -6px;
        width: 13px;
        height: 13px;
        border-radius: 50%;
        background: var(--accent);
        color: var(--accent-fg);
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        transform: scale(0.6);
        pointer-events: none;
        transition: opacity var(--t-fast), transform var(--t-fast);
    }
    .tjs-swatch:hover .tjs-dropper {
        opacity: 1;
        transform: scale(1);
    }
    /* The native picker is invisible; the chip button proxies the click. */
    .tjs-color-input {
        position: absolute;
        left: 0;
        bottom: 0;
        width: 1px;
        height: 1px;
        opacity: 0;
        pointer-events: none;
    }
    .tjs-toggle {
        width: 22px;
        height: 12px;
        padding: 0;
        border: 1px solid var(--border-default);
        border-radius: 999px;
        background: var(--panel);
        cursor: pointer;
        transition: background var(--t-fast), border-color var(--t-fast);
    }
    .tjs-toggle .knob {
        display: block;
        width: 8px;
        height: 8px;
        margin: 1px;
        border-radius: 50%;
        background: var(--text-muted);
        transition: transform var(--t-fast), background var(--t-fast);
    }
    .tjs-toggle.on {
        background: var(--accent-tint);
        border-color: var(--accent);
    }
    .tjs-toggle.on .knob {
        transform: translateX(10px);
        background: var(--accent);
    }
    .tjs-label {
        flex: 1 1 auto;
    }
    .tjs-dur {
        flex: 0 0 auto;
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }

    /* Non-interactive cell keys: dashed = sounded-but-unwritten, greyed = silent. */
    .tjs-key {
        margin-top: var(--s-2);
        padding-top: var(--s-2);
        border-top: 1px solid var(--border-quiet);
        display: flex;
        flex-direction: column;
        gap: 7px;
    }
    .tjs-key-row {
        display: flex;
        align-items: center;
        gap: 7px;
    }
    /* The letter + its haraka bottom-align, mirroring the real grapheme row where
       the small diacritic cell is pinned to the letter cell's bottom edge. */
    .tjs-key-cells {
        display: flex;
        align-items: flex-end;
        gap: 4px;
        flex: 0 0 auto;
    }
    .kcell {
        display: flex;
        align-items: center;
        justify-content: center;
        flex: 0 0 auto;
        background: var(--canvas-inset);
        border: 1px solid var(--border-default);
        border-radius: 3px;
        font-family: 'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif;
        color: var(--text-secondary);
    }
    /* Real analysis-cell dimensions: a 30×34 letter cell + a 16.5×11.9 haraka cell. */
    .kcell.big {
        width: 30px;
        height: 34px;
        font-size: 22px;
    }
    /* A full-letter-height dia column holding the two dashed harakas, each pinned
       and centred exactly like the real `.dia-track` / `.haraka-cell` pair — the
       glyph is scaled + nudged by the shared `--haraka-*` calibration. */
    .kdia {
        position: relative;
        width: 16.5px;
        height: 34px;
        flex: 0 0 auto;
    }
    .kharaka {
        position: absolute;
        left: 0;
        right: 0;
        height: 11.9px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--canvas-inset);
        border: 1px solid transparent;
        border-radius: 3px;
        overflow: hidden;
    }
    .kharaka.pin-top {
        top: 0;
    }
    .kharaka.pin-bottom {
        bottom: 0;
    }
    .kharaka.dashed {
        border-style: dashed;
        border-color: var(--ts-inserted-border);
    }
    .kg {
        display: inline-block;
        line-height: 1;
        color: var(--ts-idle-fg);
        font-family: 'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif;
        font-size: calc(var(--analysis-letter-font-size, 1.05rem) * var(--haraka-scale, 1.4));
        transform: translate(var(--haraka-shift, 0em), var(--haraka-raise, 0em));
    }
    .kcell.dashed {
        border-style: dashed;
        border-color: var(--ts-inserted-border);
        color: var(--ts-idle-fg);
    }
    .kcell.silent {
        opacity: 0.5;
        color: var(--ts-silent-fg);
    }
    .kcap {
        font-size: 11px;
        color: var(--text-muted);
        line-height: 1.35;
        white-space: normal;
    }

    /* Waqf key: each pause mark in a real analysis pause-cell (dark resting tile),
       the lone combining glyph scaled + nudged by the shared `--waqf-*` calibration
       projected by `waqfRenderStyle` — same data the live `.pause-waqf` cell reads. */
    .waqf-body {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    .waqf-row {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        white-space: nowrap;
    }
    .waqf-cell {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 3px;
        flex: 0 0 auto;
        width: 28px;
        height: 24px;
        background: var(--hl-cell-rest);
        border: 1px solid var(--border-default);
        border-radius: 3px;
        overflow: hidden;
    }
    /* muʿānaqah: the two marks of the "stop at one only" pair share one cell. The
       glyphs are zero-advance combining marks, so the flex gap sets the distance
       between their ink centres — kept wide (and the marks scaled down) so the two
       three-dot clusters read as a clear either/or pair inside the fixed cell. */
    .waqf-cell.pair {
        gap: 7px;
    }
    .waqf-cell.pair .waqf-mark {
        font-size: calc(var(--analysis-word-font-size, 1.3rem) * var(--waqf-scale, 1) * 0.55);
    }
    .waqf-mark {
        display: inline-block;
        line-height: 1;
        color: var(--ts-waqf-fg);
        font-family: 'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif;
        font-size: calc(var(--analysis-word-font-size, 1.3rem) * var(--waqf-scale, 1));
        transform: translate(var(--waqf-shift, 0), var(--waqf-raise, 0));
    }
    .waqf-cap {
        flex: 1 1 auto;
    }
</style>
