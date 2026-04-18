<script lang="ts">
    /**
     * ValidationPanel — Svelte accordion panel for all 11 validation categories.
     *
     * Subscribes to `$segValidation`. Renders one <details> per non-empty
     * category using `{#each}` over a typed descriptor list (S2-D33).
     * Empty categories are hidden.
     *
     * Category order (per CLAUDE.md):
     *   Failed Alignments, Missing Verses, Missing Words, Structural Errors,
     *   Low Confidence, Detected Repetitions, May Require Boundary Adj,
     *   Cross-verse, Audio Bleeding, Muqatta'at, Qalqala
     *
     * Open-state: component-local Record<string, boolean>. One-at-a-time
     * (collapseSiblingDetails semantics). Resets on chapter change.
     *
     * LC-slider: reactive `lcThreshold` drives Low Confidence item filtering.
     * Qalqala filter: reactive `activeQalqalaLetter` + `qalqalaEndOfVerse`.
     *
     * Batch RAF: skipped — plain `{#each}` is sufficient for typical item counts.
     */

    import { segValidation } from '../../../lib/stores/segments/validation';
    import { get } from 'svelte/store';
    import { segConfig } from '../../../lib/stores/segments/config';
    import {
        jumpToMissingVerseContext,
        jumpToSegment,
        jumpToVerse,
    } from '../../../lib/utils/segments/navigation-actions';
    import ErrorCard from './ErrorCard.svelte';
    import type {
        SegValAnyItem,
        SegValAudioBleedingItem,
        SegValLowConfidenceItem,
        SegValMissingWordsItem,
        SegValQalqalaItem,
        SegValRepetitionItem,
    } from '../../../types/domain';
    import type { SegValidateResponse } from '../../../types/api';

    // ---- Props ----
    /** Filter results to this chapter number. null = all chapters. */
    export let chapter: number | null = null;
    /** Optional section label shown above the accordions. */
    export let label: string | null = null;

    // ---- Open-state (component-local) ----
    let openCategory: string | null = null;

    // Reset on chapter change
    $: {
        void chapter;
        openCategory = null;
    }

    // ---- LC slider ----
    let lcThreshold: number = get(segConfig).lcDefaultThreshold;

    // ---- Qalqala filter ----
    const QALQALA_LETTERS_ORDER: ReadonlyArray<string> = ['\u0642', '\u0637', '\u0628', '\u062c', '\u062f'];
    let activeQalqalaLetter: string | null = null;
    let qalqalaEndOfVerse: boolean = false;

    // ---- Category descriptor type ----
    interface CategoryDescriptor {
        name: string;
        type: string;
        countClass: string;
        /** All items (for summary count on non-LC categories). */
        items: SegValAnyItem[];
        /** Filtered/sorted items that actually render as ErrorCards. */
        visibleItems: SegValAnyItem[];
        /** Count shown in summary badge. */
        summaryCount: number;
        isLowConf: boolean;
        isQalqala: boolean;
        /** Letters present in qalqala items (for filter buttons). */
        qalqalaLetters: string[];
    }

    // ---- Chapter filter ----
    function matchChapter<T extends { chapter: number }>(arr: T[] | undefined): T[] {
        return chapter === null ? (arr ?? []) : (arr ?? []).filter((i) => i.chapter === chapter);
    }

    // ---- Build category list from store ----
    function buildCategories(
        data: SegValidateResponse | null,
        _lcThreshold: number,
        _activeQalqalaLetter: string | null,
        _qalqalaEndOfVerse: boolean,
    ): CategoryDescriptor[] {
        if (!data) return [];

        const failed = matchChapter(data.failed);
        const mv = matchChapter(data.missing_verses);
        const mw = matchChapter(data.missing_words);
        const errs = matchChapter(data.errors ?? data.structural_errors);
        const lowConf = matchChapter(data.low_confidence) as SegValLowConfidenceItem[];
        const ba = matchChapter(data.boundary_adj);
        const cv = matchChapter(data.cross_verse);
        const ab = matchChapter(data.audio_bleeding);
        const rep = matchChapter(data.repetitions);
        const muq = matchChapter(data.muqattaat);
        const qal = matchChapter(data.qalqala) as SegValQalqalaItem[];

        // Low confidence
        const LC_DEFAULT = get(segConfig).lcDefaultThreshold;
        const lcVisible = lowConf
            .filter((i) => (i.confidence * 100) < _lcThreshold)
            .sort((a, b) => a.confidence - b.confidence);
        const lcSummaryCount = lowConf.filter((i) => (i.confidence * 100) < LC_DEFAULT).length;

        // Qalqala
        let qalVisible: SegValQalqalaItem[] = qal;
        if (_activeQalqalaLetter) qalVisible = qalVisible.filter((i) => i.qalqala_letter === _activeQalqalaLetter);
        if (_qalqalaEndOfVerse) qalVisible = qalVisible.filter((i) => i.end_of_verse === true);
        const qalLetters = QALQALA_LETTERS_ORDER.filter((l) => qal.some((i) => i.qalqala_letter === l));

        const all: CategoryDescriptor[] = [
            { name: 'Failed Alignments',              type: 'failed',         countClass: 'has-errors',     items: failed,  visibleItems: failed,     summaryCount: failed.length,    isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Missing Verses',                  type: 'missing_verses', countClass: 'has-errors',     items: mv,      visibleItems: mv,         summaryCount: mv.length,        isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Missing Words',                   type: 'missing_words',  countClass: 'has-errors',     items: mw,      visibleItems: mw,         summaryCount: mw.length,        isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Structural Errors',               type: 'errors',         countClass: 'has-errors',     items: errs,    visibleItems: errs,       summaryCount: errs.length,      isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Low Confidence',                  type: 'low_confidence', countClass: 'has-warnings',   items: lowConf, visibleItems: lcVisible,  summaryCount: lcSummaryCount,   isLowConf: true,  isQalqala: false, qalqalaLetters: [] },
            { name: 'Detected Repetitions',            type: 'repetitions',    countClass: 'val-rep-count',  items: rep,     visibleItems: rep,        summaryCount: rep.length,       isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'May Require Boundary Adjustment', type: 'boundary_adj',   countClass: 'has-warnings',   items: ba,      visibleItems: ba,         summaryCount: ba.length,        isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Cross-verse',                     type: 'cross_verse',    countClass: 'val-cross-count',items: cv,      visibleItems: cv,         summaryCount: cv.length,        isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Audio Bleeding',                  type: 'audio_bleeding', countClass: 'has-warnings',   items: ab,      visibleItems: ab,         summaryCount: ab.length,        isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Muqatta\u02bcat',                 type: 'muqattaat',      countClass: 'val-cross-count',items: muq,     visibleItems: muq,        summaryCount: muq.length,       isLowConf: false, isQalqala: false, qalqalaLetters: [] },
            { name: 'Qalqala',                         type: 'qalqala',        countClass: 'val-cross-count',items: qal,     visibleItems: qalVisible, summaryCount: qal.length,       isLowConf: false, isQalqala: true,  qalqalaLetters: qalLetters },
        ];

        return all.filter((c) => c.items.length > 0);
    }

    $: categories = buildCategories($segValidation, lcThreshold, activeQalqalaLetter, qalqalaEndOfVerse);
    $: hasAny = categories.length > 0;

    // ---- Item navigation button helpers ----
    function getItemBtnClass(type: string, issue: SegValAnyItem): string {
        if (type === 'low_confidence') {
            return ((issue as SegValLowConfidenceItem).confidence < 0.60) ? 'val-conf-low' : 'val-conf-mid';
        }
        if (type === 'repetitions') return 'val-rep';
        if (type === 'cross_verse' || type === 'muqattaat' || type === 'qalqala') return 'val-cross';
        if (type === 'audio_bleeding') return 'val-bleed';
        if (type === 'boundary_adj') return 'val-conf-mid';
        return 'val-error';
    }

    function getItemBtnLabel(type: string, issue: SegValAnyItem): string {
        const any = issue as {
            seg_index?: number; verse_key?: string; ref?: string;
            display_ref?: string; entry_ref?: string; matched_verse?: string;
            chapter: number;
        };
        if (type === 'failed') return `${any.chapter}:#${any.seg_index}`;
        if (type === 'missing_verses' || type === 'errors') return any.verse_key ?? '';
        if (type === 'missing_words') {
            const indices = (issue as SegValMissingWordsItem).seg_indices || [];
            return indices.length > 0 ? `${any.verse_key} #${indices.join('/#')}` : (any.verse_key ?? '');
        }
        if (type === 'repetitions') return (issue as SegValRepetitionItem).display_ref || (any.ref ?? '');
        if (type === 'audio_bleeding') {
            const ab = issue as SegValAudioBleedingItem;
            return `${ab.entry_ref}\u2192${ab.matched_verse}`;
        }
        return any.ref ?? '';
    }

    function getItemBtnTitle(type: string, issue: SegValAnyItem): string {
        const any = issue as { msg?: string; time?: string; verse_key?: string; ref?: string; entry_ref?: string; matched_verse?: string; confidence?: number };
        if (type === 'failed') return any.time ?? '';
        if (type === 'missing_verses' || type === 'errors') return any.msg ?? '';
        if (type === 'missing_words') return any.msg ?? '';
        if (type === 'low_confidence') return `${((any.confidence ?? 0) * 100).toFixed(1)}%`;
        if (type === 'boundary_adj') return any.verse_key ?? '';
        if (type === 'audio_bleeding') {
            const ab = issue as SegValAudioBleedingItem;
            return `audio ${ab.entry_ref} contains segment matching ${ab.ref} (${ab.time})`;
        }
        if (type === 'repetitions') return (issue as SegValRepetitionItem).text;
        return '';
    }

    function handleItemBtnClick(type: string, issue: SegValAnyItem): void {
        const any = issue as {
            seg_index?: number; verse_key?: string; chapter: number;
        };
        if (type === 'failed' || type === 'low_confidence' || type === 'boundary_adj' ||
            type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' ||
            type === 'muqattaat' || type === 'qalqala') {
            if (any.seg_index != null) jumpToSegment(any.chapter, any.seg_index);
        } else if (type === 'missing_verses') {
            jumpToMissingVerseContext(any.chapter, any.verse_key ?? '');
        } else if (type === 'missing_words') {
            const mw = issue as SegValMissingWordsItem;
            const indices = mw.seg_indices || [];
            const first = indices[0];
            if (first != null) jumpToSegment(any.chapter, first);
            else jumpToVerse(any.chapter, any.verse_key ?? '');
        } else if (type === 'errors') {
            jumpToVerse(any.chapter, any.verse_key ?? '');
        }
    }

    // ---- "Show All Context" ----
    function handleShowAllContext(containerEl: Element | null): void {
        if (!containerEl) return;
        const btns = [...containerEl.querySelectorAll<HTMLButtonElement>('.val-ctx-toggle-btn')];
        const anyShown = btns.some((b) => b.textContent?.trim() === 'Hide Context');
        btns.forEach((b) => {
            const isShown = b.textContent?.trim() === 'Hide Context';
            if (anyShown && isShown) b.click();
            else if (!anyShown && !isShown) b.click();
        });
    }

    // ---- Accordion toggle handler (factored out to avoid TS cast in template) ----
    function handleAccordionToggle(e: Event, type: string): void {
        const detailsEl = e.currentTarget as HTMLDetailsElement;
        const isOpen = detailsEl.open;
        openCategory = isOpen ? type : (openCategory === type ? null : openCategory);
    }

    // ---- Show All Context: click handler ----
    function handleShowAllContextClick(e: Event): void {
        const btn = e.currentTarget as HTMLButtonElement;
        const detailsEl = btn.closest('details');
        const container = detailsEl?.querySelector('.val-cards-container');
        if (container) handleShowAllContext(container);
    }
</script>

{#if hasAny}
    <div class="seg-validation-panel">
        {#if label}
            <div class="val-section-label">{label}</div>
        {/if}

        {#each categories as cat (cat.type)}
            <details
                data-category={cat.type}
                open={openCategory === cat.type}
                on:toggle={(e) => handleAccordionToggle(e, cat.type)}
            >
                <summary class="val-summary">
                    {cat.name}
                    <span class="val-count {cat.countClass}" data-lc-count>
                        {cat.isLowConf ? cat.visibleItems.length : cat.summaryCount}
                    </span>
                </summary>

                <!-- LC slider (Low Confidence only) -->
                {#if cat.isLowConf}
                    <div class="lc-slider-row">
                        <!-- svelte-ignore a11y-label-has-associated-control -->
                        <label class="lc-slider-label">
                            Show confidence &lt;
                            <span class="lc-slider-val">{lcThreshold}%</span>
                        </label>
                        <input
                            type="range"
                            class="lc-slider"
                            min="50"
                            max="99"
                            step="1"
                            bind:value={lcThreshold}
                        />
                    </div>
                {/if}

                <!-- Qalqala letter filter -->
                {#if cat.isQalqala && cat.qalqalaLetters.length > 0}
                    <div class="lc-slider-row qalqala-filter-row">
                        <span class="lc-slider-label">Filter by letter:</span>
                        {#each cat.qalqalaLetters as letter}
                            <button
                                class="val-btn val-cross qalqala-letter-btn"
                                class:active={activeQalqalaLetter === letter}
                                title="Show only segments ending with {letter}"
                                data-letter={letter}
                                on:click={() => {
                                    activeQalqalaLetter = activeQalqalaLetter === letter ? null : letter;
                                }}
                            >{letter}</button>
                        {/each}
                        <button
                            class="val-btn val-cross qalqala-eov-btn"
                            class:active={qalqalaEndOfVerse}
                            title="Show only segments that end at a verse boundary"
                            on:click={() => { qalqalaEndOfVerse = !qalqalaEndOfVerse; }}
                        >End of verse</button>
                    </div>
                {/if}

                <!-- Item navigation buttons (non-qalqala) -->
                {#if !cat.isQalqala}
                    <div class="val-items">
                        {#each cat.visibleItems as issue (issue)}
                            <button
                                class="val-btn {getItemBtnClass(cat.type, issue)}"
                                title={getItemBtnTitle(cat.type, issue)}
                                on:click={() => handleItemBtnClick(cat.type, issue)}
                            >{getItemBtnLabel(cat.type, issue)}</button>
                        {/each}
                    </div>
                {/if}

                <!-- "Show All Context" + cards -->
                <div class="val-ctx-all-row">
                    <button
                        class="val-action-btn val-action-btn-muted"
                        on:click={handleShowAllContextClick}
                    >Show/Hide All Context</button>
                </div>

                <div class="val-cards-container">
                    {#each cat.visibleItems as issue (issue)}
                        <ErrorCard category={cat.type} item={issue} />
                    {/each}
                </div>
            </details>
        {/each}
    </div>
{/if}
