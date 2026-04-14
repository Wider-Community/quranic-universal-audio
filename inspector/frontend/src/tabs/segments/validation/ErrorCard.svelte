<script lang="ts">
    /**
     * ErrorCard — one validation issue card inside a ValidationPanel accordion.
     *
     * S2-D17: single component with category prop + {#if}/{:else if} branches.
     * Three real rendering paths (matching renderOneItem in error-cards.ts):
     *   1. missing_words  — gap label + multiple seg cards + optional auto-fix
     *   2. missing_verses — verse label + boundary context segs (read-only)
     *   3. catch-all      — single seg card + ignore btn + context toggle
     *
     * Imperative card rendering: segment cards are still rendered by
     * renderSegCard() (segments/rendering.ts) into `cardsContainerEl` via
     * onMount. This preserves Stage-1 DOM structure so event-delegation,
     * waveform observer, and resolveSegFromRow work identically.
     *
     * Context toggle: component-local `showContext` boolean. Adjacent segs
     * are injected into `cardsContainerEl` before/after main cards. The
     * `val-ctx-toggle-btn` CSS class is kept so ValidationPanel's
     * "Show All Context" button can query for it.
     */

    import { onMount, onDestroy } from 'svelte';

    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
    } from '../../../segments/data';
    import { commitRefEdit } from '../../../segments/edit/reference';
    import { findMissingVerseBoundarySegments } from '../../../segments/navigation';
    import { renderSegCard } from '../../../segments/rendering';
    import {
        createOp,
        dom,
        finalizeOp,
        isDirty,
        isIndexDirty,
        markDirty,
        snapshotSeg,
        state,
        unmarkDirty,
    } from '../../../segments/state';
    import { _ensureWaveformObserver } from '../../../segments/waveform/index';
    import { _isIgnoredFor } from '../../../segments/validation/categories';
    import type {
        SegValAnyItem,
        SegValBoundaryAdjItem,
        SegValMissingVerseItem,
        SegValMissingWordsItem,
        Segment,
    } from '../../../types/domain';

    // ---- Props ----
    export let category: string;
    export let item: SegValAnyItem;

    // ---- DOM refs ----
    let cardsContainerEl: HTMLElement;
    let wrapperEl: HTMLElement;

    // ---- State ----
    let showContext = false;
    let contextEls: HTMLElement[] = [];
    let autoFixApplied = false;
    let autoFixOpId: string | null = null;
    let autoFixOldState: {
        ref: string;
        text: string;
        display: string;
        conf: number;
        ignoredCats: string[] | null;
        wasDirty: boolean;
    } | null = null;
    /** Resolved segment for catch-all branch — set in onMount. */
    let resolvedSeg: Segment | null = null;
    let isAlreadyIgnored = false;
    /** Used to decide whether to show "No boundary segments" fallback. */
    let mvHasBoundarySegs = false;

    // ---- Category-specific item casts ----
    $: mwItem = category === 'missing_words' ? (item as SegValMissingWordsItem) : null;
    $: mvItem = category === 'missing_verses' ? (item as SegValMissingVerseItem) : null;
    $: boundaryItem = category === 'boundary_adj' ? (item as SegValBoundaryAdjItem) : null;
    $: issueMsg = (item as { msg?: string }).msg;

    // ---- Derived ----
    $: canIgnore =
        resolvedSeg != null &&
        (category === 'boundary_adj' ||
            category === 'cross_verse' ||
            category === 'audio_bleeding' ||
            category === 'repetitions' ||
            category === 'qalqala' ||
            (category === 'low_confidence' && (resolvedSeg?.confidence ?? 1) < 1.0));

    $: segChapterForBtn =
        resolvedSeg != null ? (resolvedSeg.chapter ?? parseInt(dom.segChapterSelect.value)) : 0;

    $: isDirtySegment =
        resolvedSeg != null
            ? !!(state.segDirtyMap.get(segChapterForBtn)?.indices?.has(resolvedSeg.index))
            : false;

    $: ctxMode = state._accordionContext?.[category] ?? 'hidden';
    $: ctxDefaultOpen = ctxMode !== 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

    $: showPhonemes =
        category === 'boundary_adj' &&
        state.SHOW_BOUNDARY_PHONEMES &&
        !!(boundaryItem?.gt_tail || boundaryItem?.asr_tail);

    // ---- Public interface for ValidationPanel "Show All Context" ----
    export function getIsContextShown(): boolean {
        return showContext;
    }
    export function showContextForced(): void {
        if (!showContext) {
            _doShowContext();
            showContext = true;
        }
    }
    export function hideContextForced(): void {
        if (showContext) {
            _hideContext();
            showContext = false;
        }
    }

    // ---- Helper: inject a seg card into container ----
    function _injectCard(
        container: HTMLElement,
        seg: Segment,
        opts: { showGotoBtn?: boolean; isContext?: boolean; contextLabel?: string; readOnly?: boolean } = {},
        insertBeforeEl?: HTMLElement | null,
    ): HTMLElement {
        const card = renderSegCard(seg, {
            showChapter: true,
            showPlayBtn: true,
            showGotoBtn: opts.showGotoBtn ?? false,
            isContext: opts.isContext ?? false,
            contextLabel: opts.contextLabel ?? '',
            readOnly: opts.readOnly ?? false,
        });
        if (insertBeforeEl) {
            container.insertBefore(card, insertBeforeEl);
        } else {
            container.appendChild(card);
        }
        card.querySelectorAll<HTMLCanvasElement>('canvas[data-needs-waveform]').forEach((c) => {
            _ensureWaveformObserver().observe(c);
        });
        return card;
    }

    // ---- Context toggle ----
    function toggleContext(): void {
        if (showContext) {
            _hideContext();
            showContext = false;
        } else {
            _doShowContext();
            showContext = true;
        }
    }

    function _doShowContext(): void {
        if (!cardsContainerEl) return;
        if (category === 'missing_words' && mwItem) {
            const indices = mwItem.seg_indices || [];
            if (indices.length === 0) return;
            const firstIdx = indices[0];
            const lastIdx = indices[indices.length - 1];
            if (firstIdx == null || lastIdx == null) return;
            const firstSeg = getSegByChapterIndex(mwItem.chapter, firstIdx);
            const lastSeg = getSegByChapterIndex(mwItem.chapter, lastIdx);
            if (!firstSeg || !lastSeg || firstSeg.chapter == null || lastSeg.chapter == null) return;
            const firstCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row:not(.seg-row-context)');
            if (!ctxNextOnly) {
                const { prev } = getAdjacentSegments(firstSeg.chapter, firstSeg.index);
                if (prev) {
                    contextEls.push(_injectCard(cardsContainerEl, prev, { isContext: true, contextLabel: 'Previous' }, firstCard ?? null));
                }
            }
            const { next } = getAdjacentSegments(lastSeg.chapter, lastSeg.index);
            if (next) {
                contextEls.push(_injectCard(cardsContainerEl, next, { isContext: true, contextLabel: 'Next' }));
            }
        } else if (resolvedSeg && resolvedSeg.chapter != null) {
            const mainCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row:not(.seg-row-context)');
            if (!ctxNextOnly) {
                const { prev } = getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index);
                if (prev) {
                    contextEls.push(_injectCard(cardsContainerEl, prev, { isContext: true, contextLabel: 'Previous' }, mainCard ?? null));
                }
            }
            const { next } = getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index);
            if (next) {
                contextEls.push(_injectCard(cardsContainerEl, next, { isContext: true, contextLabel: 'Next' }));
            }
        } else if (category === 'missing_verses' && mvItem) {
            // For missing_verses the boundary segs are the "main" display;
            // context means outer neighbours
            const { prev, next } = findMissingVerseBoundarySegments(mvItem.chapter, mvItem.verse_key);
            if (prev && prev.chapter != null) {
                const { prev: pp } = getAdjacentSegments(prev.chapter, prev.index);
                const firstCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row');
                if (pp) contextEls.push(_injectCard(cardsContainerEl, pp, { isContext: true, contextLabel: 'Before' }, firstCard ?? null));
            }
            if (next && next.chapter != null) {
                const { next: nn } = getAdjacentSegments(next.chapter, next.index);
                if (nn) contextEls.push(_injectCard(cardsContainerEl, nn, { isContext: true, contextLabel: 'After' }));
            }
        }
    }

    function _hideContext(): void {
        contextEls.forEach((el) => el.remove());
        contextEls = [];
    }

    // ---- Segment resolution for catch-all categories ----
    function _resolveIssue(): Segment | null {
        const anyItem = item as { seg_index?: number; chapter: number; ref?: string };
        if (anyItem.seg_index != null && anyItem.seg_index < 0) return null;
        if (category === 'missing_words' || category === 'missing_verses') return null;
        if (category === 'errors') {
            const vk = (item as { verse_key?: string }).verse_key || '';
            const parts = vk.split(':');
            const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : vk;
            const chSegs = getChapterSegments(anyItem.chapter);
            return chSegs.find((s) => s.matched_ref && s.matched_ref.startsWith(prefix)) ?? chSegs[0] ?? null;
        }
        if (anyItem.seg_index == null) return null;
        const seg = getSegByChapterIndex(anyItem.chapter, anyItem.seg_index);
        if (seg && anyItem.ref && seg.matched_ref !== anyItem.ref) {
            const byRef = getChapterSegments(anyItem.chapter).find((s) => s.matched_ref === anyItem.ref);
            if (byRef) return byRef;
        }
        return seg ?? null;
    }

    // ---- Ignore handler ----
    function handleIgnore(): void {
        if (!resolvedSeg || _isIgnoredFor(resolvedSeg, category)) return;
        const segChapter = resolvedSeg.chapter ?? parseInt(dom.segChapterSelect.value);
        let ignoreOp;
        try {
            ignoreOp = createOp('ignore_issue', { contextCategory: category, fixKind: 'ignore' });
            ignoreOp.targets_before = [snapshotSeg(resolvedSeg)];
            ignoreOp.applied_at_utc = ignoreOp.started_at_utc;
        } catch (err) {
            console.warn('Ignore: edit history snapshot failed:', err);
        }
        if (!resolvedSeg.ignored_categories) resolvedSeg.ignored_categories = [];
        resolvedSeg.ignored_categories.push(category);
        delete (resolvedSeg as Segment & { _derived?: unknown })._derived;
        markDirty(segChapter, resolvedSeg.index);
        if (ignoreOp) {
            try {
                ignoreOp.targets_after = [snapshotSeg(resolvedSeg)];
                finalizeOp(segChapter, ignoreOp);
            } catch (err) {
                console.warn('Ignore: edit history finalize failed:', err);
            }
        }
        dom.segSaveBtn.disabled = !isDirty();
        isAlreadyIgnored = true;
        wrapperEl?.style.setProperty('opacity', '0.5');
    }

    // ---- missing_words: auto-fix handler ----
    async function handleAutoFix(): Promise<void> {
        if (!mwItem?.auto_fix || autoFixApplied) return;
        const autoFix = mwItem.auto_fix;
        const targetSeg = getSegByChapterIndex(mwItem.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const segChapter = targetSeg.chapter ?? mwItem.chapter;
        const wasDirty = isIndexDirty(segChapter, targetSeg.index);
        state._pendingOp = createOp('auto_fix_missing_word', {
            contextCategory: 'missing_words',
            fixKind: 'auto_fix',
        });
        state._pendingOp.targets_before = [snapshotSeg(targetSeg)];
        autoFixOpId = state._pendingOp.op_id;
        autoFixOldState = {
            ref: targetSeg.matched_ref || '',
            text: targetSeg.matched_text || '',
            display: targetSeg.display_text || '',
            conf: targetSeg.confidence,
            ignoredCats: targetSeg.ignored_categories ? [...targetSeg.ignored_categories] : null,
            wasDirty,
        };
        const newRef = `${autoFix.new_ref_start}-${autoFix.new_ref_end}`;
        const card =
            cardsContainerEl?.querySelector<HTMLElement>(
                `.seg-row[data-seg-chapter="${segChapter}"][data-seg-index="${targetSeg.index}"]`,
            ) ?? cardsContainerEl;
        await commitRefEdit(targetSeg, newRef, card);
        autoFixApplied = true;
        wrapperEl?.style.setProperty('opacity', '0.5');
    }

    function handleAutoFixUndo(): void {
        if (!mwItem?.auto_fix || !autoFixOldState) return;
        const autoFix = mwItem.auto_fix;
        const targetSeg = getSegByChapterIndex(mwItem.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const { ref, text, display, conf, ignoredCats, wasDirty } = autoFixOldState;
        const segChapter = targetSeg.chapter ?? mwItem.chapter;
        targetSeg.matched_ref = ref;
        targetSeg.matched_text = text;
        targetSeg.display_text = display;
        targetSeg.confidence = conf;
        if (ignoredCats) targetSeg.ignored_categories = ignoredCats;
        else delete targetSeg.ignored_categories;
        if (!wasDirty) unmarkDirty(segChapter, targetSeg.index);
        dom.segSaveBtn.disabled = !isDirty();
        const ops = state.segOpLog.get(segChapter);
        if (ops && autoFixOpId) {
            const idx = ops.findIndex((o) => o.op_id === autoFixOpId);
            if (idx !== -1) ops.splice(idx, 1);
        }
        autoFixApplied = false;
        autoFixOldState = null;
        autoFixOpId = null;
        wrapperEl?.style.removeProperty('opacity');
    }

    // ---- Mount: render imperative segment cards ----
    onMount(() => {
        if (!cardsContainerEl) return;

        if (category === 'missing_words' && mwItem) {
            const indices = mwItem.seg_indices || [];
            indices.forEach((idx) => {
                const s = getSegByChapterIndex(mwItem!.chapter, idx);
                if (s) _injectCard(cardsContainerEl, s, { showGotoBtn: true });
            });
        } else if (category === 'missing_verses' && mvItem) {
            const { prev, next } = findMissingVerseBoundarySegments(mvItem.chapter, mvItem.verse_key);
            const nextDifferent = next != null && (!prev || next.index !== prev.index);
            mvHasBoundarySegs = prev != null || nextDifferent;
            if (prev) _injectCard(cardsContainerEl, prev, { contextLabel: 'Previous verse boundary', readOnly: true });
            if (nextDifferent && next) _injectCard(cardsContainerEl, next!, { contextLabel: 'Next verse boundary', readOnly: true });
        } else {
            resolvedSeg = _resolveIssue();
            if (!resolvedSeg) return;
            isAlreadyIgnored = _isIgnoredFor(resolvedSeg, category);
            if (isAlreadyIgnored) wrapperEl?.style.setProperty('opacity', '0.5');
            _injectCard(cardsContainerEl, resolvedSeg, { showGotoBtn: true });

            // boundary_adj phoneme tail
            if (showPhonemes && boundaryItem) {
                const textBox = cardsContainerEl.querySelector('.seg-text');
                if (textBox) {
                    const tailEl = document.createElement('div');
                    tailEl.className = 'val-phoneme-tail';
                    const gt = boundaryItem.gt_tail || '';
                    const asr = boundaryItem.asr_tail || '';
                    tailEl.innerHTML =
                        `<span class="val-tail-label">GT:</span> <span class="val-tail-phonemes">${gt}</span>\n` +
                        `<span class="val-tail-label">ASR:</span> <span class="val-tail-phonemes">${asr}</span>`;
                    textBox.appendChild(tailEl);
                }
            }

            // Auto-open context if config says so
            if (ctxDefaultOpen) {
                _doShowContext();
                showContext = true;
            }
        }
    });

    onDestroy(() => {
        _hideContext();
    });
</script>

<div class="val-card-wrapper" bind:this={wrapperEl}>
    {#if category === 'missing_words' && mwItem}
        <div class="val-card-gap-label">{mwItem.msg || 'Missing words between segments'}</div>
        <div bind:this={cardsContainerEl}></div>
        <div class="val-card-actions">
            {#if mwItem.auto_fix}
                {#if !autoFixApplied}
                    <button
                        class="val-action-btn"
                        title="Extend segment ref to cover the missing word"
                        on:click={handleAutoFix}
                    >Auto Fill</button>
                {:else}
                    <button class="val-action-btn" disabled>Fixed (save to apply)</button>
                    <button
                        class="val-action-btn val-action-btn-danger"
                        title="Revert auto-fill"
                        on:click={handleAutoFixUndo}
                    >Undo</button>
                {/if}
            {/if}
            <button
                class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
                on:click={toggleContext}
            >{showContext ? 'Hide Context' : 'Show Context'}</button>
        </div>

    {:else if category === 'missing_verses' && mvItem}
        <div class="val-card-issue-label">
            {mvItem.msg ? `${mvItem.verse_key} \u2014 ${mvItem.msg}` : mvItem.verse_key}
        </div>
        <div bind:this={cardsContainerEl}></div>
        {#if !mvHasBoundarySegs}
            <div class="seg-loading">No boundary segments found for this missing verse.</div>
        {:else}
            <div class="val-card-actions">
                <button
                    class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
                    on:click={toggleContext}
                >{showContext ? 'Hide Context' : 'Show Context'}</button>
            </div>
        {/if}

    {:else}
        <!-- Catch-all: failed / errors / low_confidence / boundary_adj /
             cross_verse / audio_bleeding / repetitions / muqattaat / qalqala -->
        {#if issueMsg}
            <div class="val-card-issue-label">{issueMsg}</div>
        {/if}
        <div bind:this={cardsContainerEl}></div>
        <div class="val-card-actions">
            {#if canIgnore}
                <button
                    class="val-action-btn ignore-btn"
                    disabled={isAlreadyIgnored || isDirtySegment}
                    title={isDirtySegment
                        ? 'Cannot ignore \u2014 this segment already has unsaved edits'
                        : 'Dismiss this issue for this category'}
                    on:click={handleIgnore}
                >{isAlreadyIgnored ? 'Ignored' : 'Ignore'}</button>
            {/if}
            <button
                class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
                on:click={toggleContext}
            >{showContext ? 'Hide Context' : 'Show Context'}</button>
        </div>
    {/if}
</div>

<style>
    .val-card-wrapper {
        margin-bottom: 8px;
        padding: 6px 8px;
        background: #0f0f23;
        border: 1px solid #2a2a4a;
        border-radius: 4px;
    }
</style>
