<script lang="ts">
    import { getAdjacentSegments, getSegByChapterIndex, segAllData } from '../../../lib/stores/segments/chapter';
    import { commitRefEdit } from '../../../lib/utils/segments/edit-reference';
    import { segConfig } from '../../../lib/stores/segments/config';
    import {
        createOp,
        getDirtyMap,
        getOpLog,
        setPendingOp,
        snapshotSeg,
        unmarkDirty,
    } from '../../../lib/stores/segments/dirty';
    import type { SegValMissingWordsItem, Segment } from '../../../types/domain';
    import SegmentRow from '../SegmentRow.svelte';

    // ---- Props ----
    export let item: SegValMissingWordsItem;

    // ---- State ----
    let showContext = false;
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

    $: ctxMode = $segConfig.accordionContext?.['missing_words'] ?? 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

    // Missing-word segment tag set for SegmentRow display.
    $: missingWordSegIndices = new Set<number>(item.seg_indices ?? []);

    // Segments in the gap range. Subscribes to segAllData so the list
    // re-derives after split/merge mutates indices in place.
    $: segStoreTick = $segAllData;
    $: segmentsInRange = (void segStoreTick, ((): Segment[] => {
        const out: Segment[] = [];
        for (const idx of item.seg_indices ?? []) {
            const s = getSegByChapterIndex(item.chapter, idx);
            if (s) out.push(s);
        }
        return out;
    })());

    // Context neighbours: prev of first / next of last.
    $: prevSeg = ((): Segment | null => {
        if (!showContext || ctxNextOnly) return null;
        const first = segmentsInRange[0];
        if (!first || first.chapter == null) return null;
        return getAdjacentSegments(first.chapter, first.index).prev;
    })();

    $: nextSeg = ((): Segment | null => {
        if (!showContext) return null;
        const last = segmentsInRange[segmentsInRange.length - 1];
        if (!last || last.chapter == null) return null;
        return getAdjacentSegments(last.chapter, last.index).next;
    })();

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; }
    export function hideContextForced(): void { showContext = false; }

    function toggleContext(): void {
        showContext = !showContext;
    }

    // ---- Auto-fix handler ----
    async function handleAutoFix(): Promise<void> {
        if (!item.auto_fix || autoFixApplied) return;
        const autoFix = item.auto_fix;
        const targetSeg = getSegByChapterIndex(item.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const segChapter = targetSeg.chapter ?? item.chapter;
        const wasDirty = !!(getDirtyMap().get(segChapter)?.indices?.has(targetSeg.index));
        const pending = createOp('auto_fix_missing_word', {
            contextCategory: 'missing_words',
            fixKind: 'auto_fix',
        });
        pending.targets_before = [snapshotSeg(targetSeg)];
        setPendingOp(pending);
        autoFixOpId = pending.op_id;
        autoFixOldState = {
            ref: targetSeg.matched_ref || '',
            text: targetSeg.matched_text || '',
            display: targetSeg.display_text || '',
            conf: targetSeg.confidence,
            ignoredCats: targetSeg.ignored_categories ? [...targetSeg.ignored_categories] : null,
            wasDirty,
        };
        const newRef = `${autoFix.new_ref_start}-${autoFix.new_ref_end}`;
        await commitRefEdit(targetSeg, newRef);
        autoFixApplied = true;
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
        const ops = getOpLog().get(segChapter);
        if (ops && autoFixOpId) {
            const idx = ops.findIndex((o) => o.op_id === autoFixOpId);
            if (idx !== -1) ops.splice(idx, 1);
        }
        autoFixApplied = false;
        autoFixOldState = null;
        autoFixOpId = null;
    }
</script>

<div style:opacity={autoFixApplied ? 0.5 : null}>
    <div class="val-card-gap-label">{item.msg || 'Missing words between segments'}</div>
    {#if prevSeg}
        <SegmentRow
            seg={prevSeg}
            isContext={true}
            contextLabel="Previous"
            showPlayBtn={true}
            showChapter={true}
        />
    {/if}
    {#each segmentsInRange as s (s.segment_uid ?? `${s.chapter}:${s.index}`)}
        <SegmentRow
            seg={s}
            showGotoBtn={true}
            showPlayBtn={true}
            showChapter={true}
            missingWordSegIndices={missingWordSegIndices}
        />
    {/each}
    {#if nextSeg}
        <SegmentRow
            seg={nextSeg}
            isContext={true}
            contextLabel="Next"
            showPlayBtn={true}
            showChapter={true}
        />
    {/if}
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
