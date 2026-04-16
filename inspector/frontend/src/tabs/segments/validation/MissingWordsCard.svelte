<script lang="ts">
    import { onMount, onDestroy } from 'svelte';

    import { getAdjacentSegments, getSegByChapterIndex } from '../../../segments/data';
    import { commitRefEdit } from '../../../segments/edit/reference';
    import {
        createOp,
        dom,
        finalizeOp,
        isDirty,
        markDirty,
        snapshotSeg,
        state,
        unmarkDirty,
    } from '../../../segments/state';
    import { injectCard } from '../../../lib/utils/validation-card-inject';
    import type { SegValMissingWordsItem } from '../../../types/domain';

    // ---- Props ----
    export let item: SegValMissingWordsItem;

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

    $: ctxMode = state._accordionContext?.['missing_words'] ?? 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

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
        if (!cardsContainerEl) return;
        const indices = item.seg_indices || [];
        if (indices.length === 0) return;
        const firstIdx = indices[0];
        const lastIdx = indices[indices.length - 1];
        if (firstIdx == null || lastIdx == null) return;
        const firstSeg = getSegByChapterIndex(item.chapter, firstIdx);
        const lastSeg = getSegByChapterIndex(item.chapter, lastIdx);
        if (!firstSeg || !lastSeg || firstSeg.chapter == null || lastSeg.chapter == null) return;
        const firstCard = cardsContainerEl.querySelector<HTMLElement>('.seg-row:not(.seg-row-context)');
        if (!ctxNextOnly) {
            const { prev } = getAdjacentSegments(firstSeg.chapter, firstSeg.index);
            if (prev) {
                contextEls.push(injectCard(cardsContainerEl, prev, { isContext: true, contextLabel: 'Previous' }, firstCard ?? null));
            }
        }
        const { next } = getAdjacentSegments(lastSeg.chapter, lastSeg.index);
        if (next) {
            contextEls.push(injectCard(cardsContainerEl, next, { isContext: true, contextLabel: 'Next' }));
        }
    }

    function _hideContext(): void {
        contextEls.forEach((el) => el.remove());
        contextEls = [];
    }

    // ---- Auto-fix handler ----
    async function handleAutoFix(): Promise<void> {
        if (!item.auto_fix || autoFixApplied) return;
        const autoFix = item.auto_fix;
        const targetSeg = getSegByChapterIndex(item.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const segChapter = targetSeg.chapter ?? item.chapter;
        const wasDirty = !!(state.segDirtyMap.get(segChapter)?.indices?.has(targetSeg.index));
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
        if (!item.auto_fix || !autoFixOldState) return;
        const autoFix = item.auto_fix;
        const targetSeg = getSegByChapterIndex(item.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const { ref, text, display, conf, ignoredCats, wasDirty } = autoFixOldState;
        const segChapter = targetSeg.chapter ?? item.chapter;
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

    // ---- Mount ----
    onMount(() => {
        if (!cardsContainerEl) return;
        const indices = item.seg_indices || [];
        indices.forEach((idx) => {
            const s = getSegByChapterIndex(item.chapter, idx);
            if (s) injectCard(cardsContainerEl, s, { showGotoBtn: true });
        });
    });

    onDestroy(() => { _hideContext(); });
</script>

<div bind:this={wrapperEl}>
    <div class="val-card-gap-label">{item.msg || 'Missing words between segments'}</div>
    <div bind:this={cardsContainerEl}></div>
    <div class="val-card-actions">
        {#if item.auto_fix}
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
</div>
