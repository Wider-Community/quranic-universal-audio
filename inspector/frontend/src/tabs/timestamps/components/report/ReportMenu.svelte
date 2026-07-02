<script lang="ts">
    /**
     * Category picker for the Report drop-up.
     *
     * Lists the surfaced report taxonomy (timing · tajweed · phonemes · audio ·
     * other). Comment-flow categories (audio, other) expand a comment composer
     * INLINE in the row's accordion (the menu stays visible). `timing` + `phonemes`
     * enter the in-grid report mode directly; `tajweed` + `silence` expand to their
     * subtypes, each entering report mode via `onenterMode`.
     * A category that already carries an open report on this verse gets the amber
     * "reported" highlight + a count.
     */
    import * as m from '$lib/paraglide/messages';
    import { i18n } from '$lib/i18n/locale.svelte';
    import type { TsReport } from '../../../../lib/types/generated/schemas';
    import type { SilenceSubtype, TajweedSubtype } from '../../stores/report-mode';
    import {
        REPORT_CATEGORIES,
        type ReportCategoryDef,
    } from '../../domain/report-categories';
    import ReportComposer from './ReportComposer.svelte';
    import ReportIcon from './ReportIcon.svelte';

    let {
        slug,
        verseKey,
        verseReports,
        onchanged,
        onenterMode,
    }: {
        slug: string;
        verseKey: string;
        verseReports: TsReport[];
        onchanged: () => void;
        onenterMode: (
            mode: 'timing' | 'tajweed' | 'phonemes' | 'silence',
            subtype?: TajweedSubtype | SilenceSubtype,
        ) => void;
    } = $props();

    const TAJWEED_ENTRIES: { subtype: TajweedSubtype; icon: string; label: () => string; blurb: () => string }[] = [
        { subtype: 'wrong_rule', icon: 'wrong_rule', label: m.ts_report_tajweed_wrong_rule_label, blurb: m.ts_report_menu_tajweed_wrong_rule_blurb },
        { subtype: 'missing_rule', icon: 'missing_rule', label: m.ts_report_tajweed_missing_rule_label, blurb: m.ts_report_menu_tajweed_missing_rule_blurb },
    ];

    const SILENCE_ENTRIES: { subtype: SilenceSubtype; icon: string; label: () => string; blurb: () => string }[] = [
        { subtype: 'pause_boundary', icon: 'timing', label: m.ts_report_silence_pause_boundary_label, blurb: m.ts_report_menu_silence_pause_boundary_blurb },
        { subtype: 'pause_wasl', icon: 'wrong_rule', label: m.ts_report_silence_pause_wasl_label, blurb: m.ts_report_menu_silence_pause_wasl_blurb },
        { subtype: 'pause_missed', icon: 'missing_rule', label: m.ts_report_silence_pause_missed_label, blurb: m.ts_report_menu_silence_pause_missed_blurb },
    ];

    /** Open-report count per category on this verse → drives the highlight. */
    const openByCategory = $derived.by(() => {
        const m = new Map<string, number>();
        for (const r of verseReports) {
            if (r.status !== 'open') continue;
            m.set(r.category, (m.get(r.category) ?? 0) + 1);
        }
        return m;
    });

    let expandedId = $state<string | null>(null);

    function onRow(cat: ReportCategoryDef): void {
        if (cat.entersMode === 'timing' || cat.entersMode === 'phonemes') {
            onenterMode(cat.entersMode);
            return;
        }
        // comment (audio/other inline composer) or tajweed/silence subtypes
        expandedId = expandedId === cat.id ? null : cat.id;
    }

    // Attribute/text labels gated on i18n.locale so they re-render on a locale switch.
    const menuTitle = $derived((i18n.locale, m.ts_report_menu_title()));
</script>

<div class="menu">
    <header class="menu-head">
        <h4>{menuTitle}</h4>
        <span class="verse">{verseKey}</span>
    </header>

    <div class="rows">
        {#each REPORT_CATEGORIES as cat (cat.id)}
            {@const count = openByCategory.get(cat.id) ?? 0}
            {@const expandable = cat.flow === 'comment' || cat.id === 'tajweed' || cat.id === 'silence'}
            {@const open = expandedId === cat.id}
            <div class="group" class:open>
                <button
                    type="button"
                    class="cat-row"
                    class:reported={count > 0}
                    aria-expanded={expandable ? open : undefined}
                    onclick={() => onRow(cat)}
                >
                    <span class="cat-ic"><ReportIcon name={cat.id} /></span>
                    <span class="cat-text">
                        <span class="cat-label">{cat.label()}</span>
                        <span class="cat-blurb">{cat.blurb()}</span>
                    </span>
                    {#if count > 0}
                        <span class="count" title={m.ts_report_menu_open_reports_count_tooltip({ count })}>{count}</span>
                    {/if}
                    <span class="chev" class:open={expandable && open}><ReportIcon name="chevron" size={14} /></span>
                </button>

                {#if expandable && open}
                    <div class="sub">
                        {#if cat.flow === 'comment'}
                            <ReportComposer
                                inline
                                {slug}
                                {verseKey}
                                category={cat}
                                {verseReports}
                                {onchanged}
                            />
                        {:else if cat.entersMode === 'tajweed'}
                            {#each TAJWEED_ENTRIES as e (e.subtype)}
                                <button type="button" class="sub-row act" onclick={() => onenterMode('tajweed', e.subtype)}>
                                    <span class="sub-ic"><ReportIcon name={e.icon} size={14} /></span>
                                    <span class="sub-text">
                                        <span class="sub-label">{e.label()}</span>
                                        <span class="sub-blurb">{e.blurb()}</span>
                                    </span>
                                    <span class="chev"><ReportIcon name="chevron" size={13} /></span>
                                </button>
                            {/each}
                        {:else if cat.entersMode === 'silence'}
                            {#each SILENCE_ENTRIES as e (e.subtype)}
                                <button type="button" class="sub-row act" onclick={() => onenterMode('silence', e.subtype)}>
                                    <span class="sub-ic"><ReportIcon name={e.icon} size={14} /></span>
                                    <span class="sub-text">
                                        <span class="sub-label">{e.label()}</span>
                                        <span class="sub-blurb">{e.blurb()}</span>
                                    </span>
                                    <span class="chev"><ReportIcon name="chevron" size={13} /></span>
                                </button>
                            {/each}
                        {/if}
                    </div>
                {/if}
            </div>
        {/each}
    </div>
</div>

<style>
    .menu {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        min-width: 300px;
    }
    .menu-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--s-2);
        padding: 2px 2px var(--s-1);
    }
    .menu-head h4 {
        margin: 0;
        font-size: var(--fs-body);
        font-weight: 600;
        color: var(--text-primary);
    }
    .verse {
        font-family: var(--font-mono);
        font-size: var(--fs-meta);
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
    }

    .rows { display: flex; flex-direction: column; gap: 2px; }
    .group {
        border-radius: var(--r-2);
        border: 1px solid transparent;
    }
    .group.open {
        background: var(--canvas-inset);
        border-color: var(--border-quiet);
    }

    .cat-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        padding: var(--s-2);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        text-align: left;
        font: inherit;
        color: var(--text-primary);
        transition: background var(--t-fast), border-color var(--t-fast);
    }
    .cat-row:hover { background: var(--panel-2); }
    .cat-ic {
        display: inline-flex;
        flex: 0 0 auto;
        color: var(--text-secondary);
    }
    .cat-row:hover .cat-ic { color: var(--text-primary); }
    .cat-text {
        display: flex;
        flex-direction: column;
        gap: 1px;
        flex: 1 1 auto;
        min-width: 0;
    }
    .cat-label { font-size: var(--fs-body); font-weight: 500; line-height: 1.25; }
    .cat-blurb {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        line-height: 1.25;
    }
    .chev {
        display: inline-flex;
        flex: 0 0 auto;
        color: var(--text-faint);
        transition: transform var(--t-fast);
    }
    .chev.open { transform: rotate(90deg); }
    .count {
        flex: 0 0 auto;
        min-width: 18px;
        padding: 0 5px;
        text-align: center;
        font-family: var(--font-mono);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        line-height: 17px;
        color: var(--state-warn-fg);
        background: var(--state-warn-bg);
        border: 1px solid var(--state-warn-border);
        border-radius: 999px;
    }

    /* Amber "reported" highlight — same warn hue as the footer Report button. */
    .cat-row.reported .cat-ic { color: var(--state-warn-fg); }
    .cat-row.reported .cat-label { color: var(--state-warn-fg); }

    .sub {
        display: flex;
        flex-direction: column;
        gap: 1px;
        padding: 0 var(--s-2) var(--s-2) calc(var(--s-2) + 24px);
    }
    .sub-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        padding: 4px var(--s-2);
        border-radius: var(--r-1);
        color: var(--text-secondary);
        font-size: var(--fs-meta);
    }
    .sub-ic { display: inline-flex; flex: 0 0 auto; color: var(--text-faint); }
    .sub-label { flex: 0 0 auto; }
    /* Interactive subtype rows (tajweed wrong/missing) enter report mode. */
    button.sub-row.act {
        width: 100%;
        background: transparent;
        border: 1px solid transparent;
        cursor: pointer;
        text-align: left;
        font: inherit;
        transition: background var(--t-fast), color var(--t-fast);
    }
    button.sub-row.act:hover { background: var(--panel-2); color: var(--text-primary); }
    button.sub-row.act:hover .sub-ic { color: var(--text-secondary); }
    .sub-text { display: flex; flex-direction: column; gap: 1px; flex: 1 1 auto; min-width: 0; }
    .sub-text .sub-label { font-weight: 500; }
    .sub-blurb { font-size: var(--fs-meta); color: var(--text-muted); line-height: 1.2; }
    .sub-row .chev { display: inline-flex; flex: 0 0 auto; color: var(--text-faint); }
</style>
