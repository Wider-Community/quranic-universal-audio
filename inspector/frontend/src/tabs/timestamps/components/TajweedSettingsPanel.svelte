<script lang="ts">
    /**
     * Tajweed legend + per-rule settings drop-up for the Timestamps footer. Three
     * equal columns — Noon / Meem, Madd, Other rules — each row a colour chip
     * (click → native colour picker, live recolour, hover reveals a dropper) with a
     * mini enable toggle, label and ḥarakāt duration. Qalqala is two coupled rows
     * (ṣughrā / kubrā) sharing the `qalqala` key, the kubrā chip previewing the
     * side-wrap. The Other column closes with two non-interactive keys explaining
     * the dashed (sounded-but-unwritten) and greyed (written-but-silent) cells. All
     * state lives in the `tajweed-settings` store; colours apply via `--tj-*`
     * overrides, toggles drive the per-cell underline. `tajweedDump()` (devtools)
     * prints the current palette + enables for promoting to shipped defaults.
     */
    import { LEGEND, type LegendRow } from '../utils/tajweed-rules';
    import {
        resetAllTajweed,
        setRuleColor,
        setRuleEnabled,
        tajweedSettings,
    } from '../stores/tajweed-settings';

    // Hidden native colour inputs, one per row, opened by clicking its chip.
    let inputs: Record<string, HTMLInputElement | undefined> = $state({});

    /** Normalise any CSS colour (oklch / rgb / hex) to a `#rrggbb` the native
     *  picker accepts, via a throwaway canvas (Chromium parses oklch). */
    function cssColorToHex(input: string): string {
        const s = input.trim();
        if (/^#[0-9a-f]{6}$/i.test(s)) return s;
        try {
            const ctx = document.createElement('canvas').getContext('2d');
            if (ctx) {
                ctx.fillStyle = '#000000';
                ctx.fillStyle = s;
                const v = ctx.fillStyle;
                if (/^#[0-9a-f]{6}$/i.test(v)) return v;
                const m = v.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                if (m) {
                    return (
                        '#' +
                        [1, 2, 3]
                            .map((i) => Number(m[i]).toString(16).padStart(2, '0'))
                            .join('')
                    );
                }
            }
        } catch {
            /* unsupported parse — fall through */
        }
        return '#888888';
    }

    /** The rule's current effective colour as hex (override, else the live CSS var). */
    function effectiveHex(row: LegendRow): string {
        const override = $tajweedSettings[row.legendKey]?.color;
        if (override) return override;
        const raw = getComputedStyle(document.documentElement).getPropertyValue(row.colorVar);
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
    <div class="tjs-tip">
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
            <path
                d="M6 18 L13.5 10.5 L16 13 L8.5 20.5 H6 Z"
                fill="none"
                stroke="currentColor"
                stroke-width="1.7"
                stroke-linejoin="round"
            />
            <path d="M14.5 9.5 L16.8 7.2 A1.6 1.6 0 0 1 19 9.4 L16.7 11.7 Z" fill="currentColor" />
        </svg>
        Click a colour chip to recolour it · toggle to show or hide each rule
    </div>

    <div class="tjs-cols">
        {#each LEGEND as group (group.title)}
            <section class="tjs-group">
                <h4>{group.title}</h4>
                {#each group.rows as row (row.label)}
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
                {/each}

                {#if group.category === 'other'}
                    <div class="tjs-key">
                        <div class="tjs-key-row">
                            <span class="kcell big dashed">ا</span>
                            <span class="kcell small dashed">◌ِ</span>
                            <span class="kcap">Pronounced but unwritten/transformed</span>
                        </div>
                        <div class="tjs-key-row">
                            <span class="kcell big silent">ٱ</span>
                            <span class="kcap">Written but silent</span>
                        </div>
                    </div>
                {/if}
            </section>
        {/each}
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
    }
    .tjs-title {
        font-size: var(--fs-meta);
        font-weight: 600;
        color: var(--text-primary);
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
    .tjs-tip {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        color: var(--text-faint);
        padding-bottom: var(--s-1);
        border-bottom: 1px solid var(--border-quiet);
    }
    .tjs-cols {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
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
    .kcell.big {
        width: 22px;
        height: 28px;
        font-size: 18px;
    }
    .kcell.small {
        width: 15px;
        height: 17px;
        font-size: 12px;
    }
    .kcell.dashed {
        border-style: dashed;
        border-color: #6a6f8c;
        color: #aaa;
    }
    .kcell.silent {
        opacity: 0.5;
        color: #777;
    }
    .kcap {
        font-size: 11px;
        color: var(--text-muted);
        line-height: 1.35;
        white-space: normal;
    }
</style>
