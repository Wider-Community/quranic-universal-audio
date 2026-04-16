<script lang="ts">
    import { onMount, onDestroy } from 'svelte';

    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
    } from '../../../segments/data';
    import {
        createOp,
        dom,
        finalizeOp,
        isDirty,
        markDirty,
        snapshotSeg,
        state,
    } from '../../../segments/state';
    import { _isIgnoredFor } from '../../../segments/validation/categories';
    import { injectCard } from '../../../lib/utils/validation-card-inject';
    import type {
        SegValAnyItem,
        SegValBoundaryAdjItem,
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
    let resolvedSeg: Segment | null = null;
    let isAlreadyIgnored = false;

    // ---- Derived ----
    $: boundaryItem = category === 'boundary_adj' ? (item as SegValBoundaryAdjItem) : null;
    $: issueMsg = (item as { msg?: string }).msg;

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

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void {
        if (!showContext) { _doShowContext(); showContext = true; }
    }
    export function hideContextForced(): void {
        if (showContext) { _hideContext(); showContext = false; }
    }

    // ---- Context toggle ----
    function toggleContext(): void {
        if (showContext) { _hideContext(); showContext = false; }
        else { _doShowContext(); showContext = true; }
    }

    function _doShowContext(): void {
        if (!cardsContainerEl || !resolvedSeg || resolvedSeg.chapter == null) return;
        const mainCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row:not(.seg-row-context)');
        if (!ctxNextOnly) {
            const { prev } = getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index);
            if (prev) {
                contextEls.push(injectCard(cardsContainerEl, prev, { isContext: true, contextLabel: 'Previous' }, mainCard ?? null));
            }
        }
        const { next } = getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index);
        if (next) {
            contextEls.push(injectCard(cardsContainerEl, next, { isContext: true, contextLabel: 'Next' }));
        }
    }

    function _hideContext(): void {
        contextEls.forEach((el) => el.remove());
        contextEls = [];
    }

    // ---- Segment resolution ----
    function _resolveIssue(): Segment | null {
        const anyItem = item as { seg_index?: number; chapter: number; ref?: string };
        if (anyItem.seg_index != null && anyItem.seg_index < 0) return null;
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

    // ---- Mount ----
    onMount(() => {
        if (!cardsContainerEl) return;
        resolvedSeg = _resolveIssue();
        if (!resolvedSeg) return;
        isAlreadyIgnored = _isIgnoredFor(resolvedSeg, category);
        if (isAlreadyIgnored) wrapperEl?.style.setProperty('opacity', '0.5');
        injectCard(cardsContainerEl, resolvedSeg, { showGotoBtn: true });

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

        if (ctxDefaultOpen) {
            _doShowContext();
            showContext = true;
        }
    });

    onDestroy(() => { _hideContext(); });
</script>

<div bind:this={wrapperEl}>
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
</div>
