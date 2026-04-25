<script lang="ts">
    /**
     * ValidationPanel — Svelte accordion panel for all 11 validation categories.
     *
     * Subscribes to `$segValidation`. Renders one <details> per non-empty
     * category using `{#each}` over a typed descriptor list.
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
     * Virtualization: the cards container for the open category virtualizes
     * its list when the item count exceeds VIRTUALIZE_THRESHOLD. Only the
     * window of cards intersecting the viewport (plus BUFFER_ROWS above/below)
     * are mounted; spacer divs preserve the container's scroll height.
     * Card context-state (Show/Hide Context toggle) is tracked in a per-type
     * Map so cards restore their state on re-mount as the window slides.
     */

    import { afterUpdate } from 'svelte';
    import { segValidation } from '../../stores/validation';
    import { get } from 'svelte/store';
    import { segConfig } from '../../stores/config';
    import { editingSegUid } from '../../stores/edit';
    import { segAllData } from '../../stores/chapter';
    import { IssueRegistry } from '../../domain/registry';
    import {
        CONF_MID_THRESHOLD,
        VAL_VIRTUALIZE_THRESHOLD,
        VIRT_BUFFER_ROWS,
    } from '../../utils/constants';
    import {
        jumpToMissingVerseContext,
        jumpToSegment,
        jumpToVerse,
    } from '../../utils/data/navigation-actions';
    import { resolveIssueSeg } from '../../utils/validation/resolve-issue';
    import ErrorCard from './ErrorCard.svelte';
    import type {
        SegValAnyItem,
        SegValAudioBleedingItem,
        SegValLowConfidenceItem,
        SegValMissingWordsItem,
        SegValQalqalaItem,
        SegValRepetitionItem,
        SegValidateResponse,
    } from '../../../../lib/types/api';

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

    // ---- Virtualization constants ----
    /** Fallback card height (px) before real measurement. MissingVersesCard with
     *  context rows is much taller; over-estimating reduces pop-in on first open. */
    const FALLBACK_CARD_HEIGHT = 180;
    /** Extra cards rendered above/below the visible window. */
    const BUFFER_ROWS = VIRT_BUFFER_ROWS;

    // ---- Per-category virtualization state ----
    // scrollTop and viewport height of the open category's cards container.
    const CARDS_VIEWPORT_HEIGHT_FALLBACK = 500;
    let cardsScrollTop = 0;
    let cardsViewportHeight = CARDS_VIEWPORT_HEIGHT_FALLBACK;
    let measuredCardHeight = FALLBACK_CARD_HEIGHT;
    let cardsContainerEl: HTMLDivElement | null = null;

    let scrollRaf: number | null = null;
    function onCardsScroll(): void {
        if (scrollRaf !== null) return;
        scrollRaf = requestAnimationFrame(() => {
            scrollRaf = null;
            if (!cardsContainerEl) return;
            cardsScrollTop = cardsContainerEl.scrollTop;
            cardsViewportHeight = cardsContainerEl.clientHeight;
        });
    }

    // After each update: re-measure card heights + sync window refs → Map.
    // Two concerns merged into one afterUpdate to avoid duplicate DOM walks.
    afterUpdate(() => {
        // Measure
        if (cardsContainerEl) {
            const cards = cardsContainerEl.querySelectorAll<HTMLElement>('.val-card-wrapper');
            if (cards.length > 0) {
                let sum = 0;
                for (const c of cards) sum += c.getBoundingClientRect().height;
                const avg = sum / cards.length + 8; // +gap
                if (avg > 20 && Math.abs(avg - measuredCardHeight) > 4) {
                    measuredCardHeight = avg;
                }
            }
        }
        // Sync window-slice refs to absolute-index Map
        cardRefMap.clear();
        for (let li = 0; li < windowCardRefs.length; li++) {
            const card = windowCardRefs[li];
            if (card) cardRefMap.set(startIdx + li, card);
        }
    });

    // Reset scroll position and measured height when the open category changes
    // so the new category starts at the top and re-measures its own card sizes.
    let _prevOpenCategory: string | null = null;
    $: if (openCategory !== _prevOpenCategory) {
        _prevOpenCategory = openCategory;
        cardsScrollTop = 0;
        measuredCardHeight = FALLBACK_CARD_HEIGHT;
    }

    // ---- Per-type context-shown state (survives virtualization re-mounts) ----
    // Maps item array index → boolean. Stored per category type so toggling
    // "Show/Hide All Context" and then scrolling away preserves the state.
    const contextStateByType: Record<string, Map<number, boolean>> = {};

    function getContextState(type: string): Map<number, boolean> {
        if (!contextStateByType[type]) contextStateByType[type] = new Map();
        return contextStateByType[type];
    }

    // Clear context state only when a filter input (chapter / LC threshold /
    // qalqala letter / end-of-verse) changes — not when the items array
    // identity shifts because of a split/merge fixup. Keying on identity
    // used to reset the Show Context toggle every time a structural edit
    // republished the array, throwing away user-visible state mid-edit.
    const _lastFilterSig: Record<string, string> = {};

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

    // ---- Per-category presentation hints (count badge class). ----
    // Severity \u2192 CSS hook for the count pill. The two flag-style classes
    // (val-rep-count, val-cross-count) are used to colour repetition /
    // cross-verse / muqattaat / qalqala counts in their own palette.
    const COUNT_CLASS_OVERRIDES: Record<string, string> = {
        repetitions: 'val-rep-count',
        cross_verse: 'val-cross-count',
        muqattaat: 'val-cross-count',
        qalqala: 'val-cross-count',
    };
    function _countClassFor(kind: string): string {
        const override = COUNT_CLASS_OVERRIDES[kind];
        if (override) return override;
        const sev = IssueRegistry[kind]?.severity ?? 'error';
        return sev === 'error' ? 'has-errors' : 'has-warnings';
    }

    // Each registry entry maps to the response field it consumes. The accordion
    // descriptor is built in registry accordionOrder.
    function _itemsFor(kind: string, data: SegValidateResponse): SegValAnyItem[] {
        if (kind === 'structural_errors') {
            return matchChapter(data.errors ?? data.structural_errors);
        }
        const slot = (data as Record<string, SegValAnyItem[] | undefined>)[kind];
        return matchChapter(slot);
    }

    // ---- Build category list from store ----
    function buildCategories(
        data: SegValidateResponse | null,
        _lcThreshold: number,
        _activeQalqalaLetter: string | null,
        _qalqalaEndOfVerse: boolean,
    ): CategoryDescriptor[] {
        if (!data) return [];

        const ordered = Object.values(IssueRegistry).slice()
            .sort((a, b) => a.accordionOrder - b.accordionOrder);

        const LC_DEFAULT = get(segConfig).lcDefaultThreshold;
        const all: CategoryDescriptor[] = ordered.map((defn) => {
            const items = _itemsFor(defn.kind, data);
            let visibleItems: SegValAnyItem[] = items;
            let summaryCount = items.length;
            let isLowConf = false;
            let isQalqala = false;
            let qalqalaLetters: string[] = [];

            if (defn.kind === 'low_confidence') {
                const lowConf = items as SegValLowConfidenceItem[];
                visibleItems = lowConf
                    .filter((i) => (i.confidence * 100) < _lcThreshold)
                    .sort((a, b) => a.confidence - b.confidence);
                summaryCount = lowConf.filter((i) => (i.confidence * 100) < LC_DEFAULT).length;
                isLowConf = true;
            } else if (defn.kind === 'qalqala') {
                const qal = items as SegValQalqalaItem[];
                let q: SegValQalqalaItem[] = qal;
                if (_activeQalqalaLetter) q = q.filter((i) => i.qalqala_letter === _activeQalqalaLetter);
                if (_qalqalaEndOfVerse) q = q.filter((i) => i.end_of_verse === true);
                visibleItems = q;
                summaryCount = qal.length;
                isQalqala = true;
                qalqalaLetters = QALQALA_LETTERS_ORDER.filter((l) => qal.some((i) => i.qalqala_letter === l));
            }

            return {
                name: defn.displayTitle,
                type: defn.kind,
                countClass: _countClassFor(defn.kind),
                items,
                visibleItems,
                summaryCount,
                isLowConf,
                isQalqala,
                qalqalaLetters,
            };
        });

        return all.filter((c) => c.items.length > 0);
    }

    let categories: CategoryDescriptor[] = [];
    $: {
        categories = buildCategories($segValidation, lcThreshold, activeQalqalaLetter, qalqalaEndOfVerse);
        // Filter signature: the subset of inputs that truly narrow the item
        // list (chapter / LC threshold / qalqala letter / end-of-verse).
        // If none of these change, preserve each type's context-shown map so
        // structural edits (split/merge) that republish the items array via
        // identity shift don't reset Show Context toggles mid-edit.
        const sig = `${chapter}|${lcThreshold}|${activeQalqalaLetter ?? ''}|${qalqalaEndOfVerse}`;
        for (const cat of categories) {
            if (_lastFilterSig[cat.type] !== sig) {
                _lastFilterSig[cat.type] = sig;
                if (contextStateByType[cat.type]) contextStateByType[cat.type].clear();
            }
        }
    }
    $: hasAny = categories.length > 0;

    // ---- Virtualization window for the open category ----
    $: openCat = categories.find((c) => c.type === openCategory) ?? null;
    $: openTotal = openCat?.visibleItems.length ?? 0;
    // Virtualization stays ACTIVE during editMode. To keep the editing row
    // mounted — so scrolling away doesn't evict the edit panel mid-flow —
    // we expand the slice window to include whichever card resolves to the
    // editing segment UID. All other cards virtualize normally, so a 200-row
    // accordion doesn't mount 200 SegmentRows every reactive tick during
    // edit.
    $: virtualize = openTotal > VAL_VIRTUALIZE_THRESHOLD;
    // Resolve editing seg's (chapter, index) — needed to locate the card
    // owning it within `visibleItems`. Only recompute when the UID changes
    // or segAllData identity shifts (structural edits reindex).
    $: editingCoords = ((): { chapter: number; index: number } | null => {
        const uid = $editingSegUid;
        if (!uid) return null;
        const segs = $segAllData?.segments;
        if (!segs) return null;
        const seg = segs.find((s) => s.segment_uid === uid);
        if (!seg || seg.chapter == null) return null;
        return { chapter: seg.chapter, index: seg.index };
    })();
    // Find the editing card's index within the open category's visible list.
    // `seg_index` is the validation item's segment index (mutated in place by
    // the split/merge/delete fixups in `utils/validation/fixups.ts`).
    $: editingItemIdx = ((): number => {
        if (!virtualize || !editingCoords || !openCat) return -1;
        const items = openCat.visibleItems as ReadonlyArray<{
            chapter?: number;
            seg_index?: number;
            seg_indices?: number[];
        }>;
        for (let i = 0; i < items.length; i++) {
            const it = items[i];
            if (!it || it.chapter !== editingCoords.chapter) continue;
            if (it.seg_index === editingCoords.index) return i;
            if (it.seg_indices?.includes(editingCoords.index)) return i;
        }
        return -1;
    })();
    $: baseStartIdx = virtualize
        ? Math.max(0, Math.floor(cardsScrollTop / measuredCardHeight) - BUFFER_ROWS)
        : 0;
    $: baseEndIdx = virtualize
        ? Math.min(openTotal, Math.ceil((cardsScrollTop + cardsViewportHeight) / measuredCardHeight) + BUFFER_ROWS)
        : openTotal;
    // Expand the window to cover the editing card so scrolling away doesn't
    // unmount it. Bound check against openTotal handles items added/removed
    // via fixups while still in edit mode.
    $: startIdx = virtualize && editingItemIdx >= 0
        ? Math.min(baseStartIdx, editingItemIdx)
        : baseStartIdx;
    $: endIdx = virtualize && editingItemIdx >= 0
        ? Math.max(baseEndIdx, editingItemIdx + 1)
        : baseEndIdx;
    $: topSpacerPx = virtualize ? startIdx * measuredCardHeight : 0;
    $: bottomSpacerPx = virtualize ? Math.max(0, (openTotal - endIdx) * measuredCardHeight) : 0;

    // ---- Item navigation button helpers ----
    function getItemBtnClass(type: string, issue: SegValAnyItem): string {
        if (type === 'low_confidence') {
            return ((issue as SegValLowConfidenceItem).confidence < CONF_MID_THRESHOLD) ? 'val-conf-low' : 'val-conf-mid';
        }
        if (type === 'repetitions') return 'val-rep';
        if (type === 'cross_verse' || type === 'muqattaat' || type === 'qalqala') return 'val-cross';
        if (type === 'audio_bleeding') return 'val-bleed';
        if (type === 'boundary_adj') return 'val-conf-mid';
        return 'val-error';
    }

    // Pill label reads the LIVE seg's `matched_ref` so post-edit mutations
    // (split, ref-edit, merge) are reflected immediately — `issue.ref` is a
    // server snapshot frozen at `/api/seg/validate` time and goes stale as
    // soon as the user mutates the seg.  See `utils/validation/resolve-issue.ts`
    // for the "four ref fields" rule.
    function _liveRef(issue: SegValAnyItem, type: string, fallbackRef: string | undefined): string {
        const seg = resolveIssueSeg(issue, type, null);
        return seg?.matched_ref || fallbackRef || '';
    }

    function getItemBtnLabel(type: string, issue: SegValAnyItem): string {
        const any = issue as {
            seg_index?: number; verse_key?: string; ref?: string;
            display_ref?: string; entry_ref?: string; matched_verse?: string;
            chapter: number;
        };
        void $segAllData; // re-evaluate on seg mutations so live ref tracks
        if (type === 'failed') return `${any.chapter}:#${any.seg_index}`;
        if (type === 'missing_verses' || type === 'structural_errors') return any.verse_key ?? '';
        if (type === 'missing_words') {
            const indices = (issue as SegValMissingWordsItem).seg_indices || [];
            return indices.length > 0 ? `${any.verse_key} #${indices.join('/#')}` : (any.verse_key ?? '');
        }
        if (type === 'repetitions') {
            return _liveRef(issue, type, (issue as SegValRepetitionItem).display_ref || any.ref);
        }
        if (type === 'audio_bleeding') {
            const ab = issue as SegValAudioBleedingItem;
            return `${ab.entry_ref}\u2192${ab.matched_verse}`;
        }
        return _liveRef(issue, type, any.ref);
    }

    function getItemBtnTitle(type: string, issue: SegValAnyItem): string {
        const any = issue as { msg?: string; time?: string; verse_key?: string; ref?: string; entry_ref?: string; matched_verse?: string; confidence?: number };
        void $segAllData;
        if (type === 'failed') return any.time ?? '';
        if (type === 'missing_verses' || type === 'structural_errors') return any.msg ?? '';
        if (type === 'missing_words') return any.msg ?? '';
        if (type === 'low_confidence') return `${((any.confidence ?? 0) * 100).toFixed(1)}%`;
        if (type === 'boundary_adj') return any.verse_key ?? '';
        if (type === 'audio_bleeding') {
            const ab = issue as SegValAudioBleedingItem;
            const liveRef = _liveRef(issue, type, ab.ref);
            return `audio ${ab.entry_ref} contains segment matching ${liveRef} (${ab.time})`;
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
        } else if (type === 'structural_errors') {
            jumpToVerse(any.chapter, any.verse_key ?? '');
        }
    }

    // ---- ErrorCard refs (window-slice array, synced to absolute Map in afterUpdate) ----
    // `windowCardRefs` holds bind:this refs for the currently rendered slice.
    // Rebuilt into `cardRefMap` in the shared afterUpdate block above so
    // handleShowAllContext can reach every visible card by absolute index.
    let windowCardRefs: ErrorCard[] = [];
    const cardRefMap: Map<number, ErrorCard> = new Map();

    // ---- "Show/Hide All Context" per category ----
    // Operates on mounted window cards; also writes contextStateByType so cards
    // that scroll into view later restore the correct initial state.
    function handleShowAllContext(type: string): void {
        const ctxMap = getContextState(type);
        const cat = categories.find((c) => c.type === type);
        if (!cat) return;
        const anyShown = Array.from(cardRefMap.values()).some((c) => c?.getIsContextShown());
        const newState = !anyShown;
        for (let i = 0; i < cat.visibleItems.length; i++) {
            ctxMap.set(i, newState);
        }
        for (const c of cardRefMap.values()) {
            if (!c) continue;
            if (newState) c.showContextForced();
            else c.hideContextForced();
        }
    }

    // ---- Accordion toggle handler (factored out to avoid TS cast in template) ----
    function handleAccordionToggle(e: Event, type: string): void {
        const detailsEl = e.currentTarget as HTMLDetailsElement;
        const isOpen = detailsEl.open;
        openCategory = isOpen ? type : (openCategory === type ? null : openCategory);
    }

    // ---- Context state sync: card notifies panel when user toggles Show/Hide ----
    function onCardContextChange(type: string, absIdx: number, shown: boolean): void {
        getContextState(type).set(absIdx, shown);
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

                {#if openCategory === cat.type}
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
                            on:click={() => handleShowAllContext(cat.type)}
                        >Show/Hide All Context</button>
                    </div>

                    <div
                        class="val-cards-container"
                        bind:this={cardsContainerEl}
                        on:scroll={onCardsScroll}
                    >
                        {#if topSpacerPx > 0}
                            <div class="val-cards-spacer" style="height: {topSpacerPx}px" aria-hidden="true"></div>
                        {/if}
                        {#each cat.visibleItems.slice(startIdx, endIdx) as issue, localIdx (issue)}
                            <ErrorCard
                                bind:this={windowCardRefs[localIdx]}
                                category={cat.type}
                                item={issue}
                                initialContextShown={getContextState(cat.type).get(startIdx + localIdx) ?? false}
                                on:contextchange={(e) => onCardContextChange(cat.type, startIdx + localIdx, e.detail)}
                            />
                        {/each}
                        {#if bottomSpacerPx > 0}
                            <div class="val-cards-spacer" style="height: {bottomSpacerPx}px" aria-hidden="true"></div>
                        {/if}
                    </div>
                {/if}
            </details>
        {/each}
    </div>
{/if}
