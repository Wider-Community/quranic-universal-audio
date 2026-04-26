<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
        segAllData,
    } from '../../stores/chapter';
    import { commitRefEdit } from '../../utils/edit/reference';
    import { segConfig } from '../../stores/config';
    import {
        createOp,
        dirtyTick,
        getChapterOpsSnapshot,
        getOpLog,
        isSegmentDirty,
        setPendingOp,
        snapshotSeg,
        unmarkDirty,
    } from '../../stores/dirty';
    import { historyData } from '../../stores/history';
    import { getSplitGroupMembers } from '../../utils/validation/split-group';
    import type { SegValMissingWordsItem } from '../../../../lib/types/api';
    import type { Segment } from '../../../../lib/types/domain';
    import SegmentRow from '../list/SegmentRow.svelte';

    const dispatch = createEventDispatcher<{ contextchange: boolean }>();

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
    // re-derives after split/merge mutates indices in place. For each base
    // seg, include its full split-group (transitive descendants) so splits
    // inside the gap stay visible rather than snapping to whichever half
    // currently holds the original index. Preserves source order and dedupes
    // by UID — groups themselves are time-sorted, so relative position is
    // meaningful.
    //
    // Memoized by length fingerprint over (chapterSegs, batches, ops, base
    // UIDs) — see GenericIssueCard for the invariant rationale. Prevents a
    // N-card accordion × M-gap-segment re-walk of every split op on every
    // reactive tick.
    $: segStoreTick = $segAllData;
    let _segRangeMemoKey = '';
    let _segRangeMemoResult: Segment[] = [];
    $: {
        void segStoreTick; void $dirtyTick;
        const chapterSegs = getChapterSegments(item.chapter);
        const batches = $historyData?.batches ?? [];
        const ops = getChapterOpsSnapshot(item.chapter);
        // Base UIDs are looked up per `seg_index`; include them in the key
        // so a fixup that swaps the seg at a given index also invalidates.
        const baseUids: string[] = [];
        for (const idx of item.seg_indices ?? []) {
            const base = getSegByChapterIndex(item.chapter, idx);
            baseUids.push(base?.segment_uid ?? `_${idx}`);
        }
        const key = `${item.chapter}|${(item.seg_indices ?? []).join(',')}|${baseUids.join(',')}|${chapterSegs.length}|${batches.length}|${ops.length}`;
        if (key !== _segRangeMemoKey) {
            _segRangeMemoKey = key;
            const out: Segment[] = [];
            const seenUids = new Set<string>();
            for (const idx of item.seg_indices ?? []) {
                const base = getSegByChapterIndex(item.chapter, idx);
                if (!base) continue;
                const baseUid = base.segment_uid ?? null;
                const group = getSplitGroupMembers(item.chapter, baseUid, chapterSegs, batches, ops);
                const list = group.length > 0 ? group : [base];
                for (const s of list) {
                    const segKey = s.segment_uid ?? `${s.chapter}:${s.index}`;
                    if (seenUids.has(segKey)) continue;
                    seenUids.add(segKey);
                    out.push(s);
                }
            }
            _segRangeMemoResult = out;
        }
    }
    $: segmentsInRange = _segRangeMemoResult;

    // Context neighbours: prev of first / next of last. Guard against the
    // neighbour being itself a split-group member (already rendered inline).
    $: prevSeg = ((): Segment | null => {
        if (!showContext || ctxNextOnly) return null;
        const first = segmentsInRange[0];
        if (!first || first.chapter == null) return null;
        const p = getAdjacentSegments(first.chapter, first.index).prev;
        if (p && p.segment_uid && segmentsInRange.some((s) => s.segment_uid === p.segment_uid)) return null;
        return p;
    })();

    $: nextSeg = ((): Segment | null => {
        if (!showContext) return null;
        const last = segmentsInRange[segmentsInRange.length - 1];
        if (!last || last.chapter == null) return null;
        const n = getAdjacentSegments(last.chapter, last.index).next;
        if (n && n.segment_uid && segmentsInRange.some((s) => s.segment_uid === n.segment_uid)) return null;
        return n;
    })();

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; dispatch('contextchange', true); }
    export function hideContextForced(): void { showContext = false; dispatch('contextchange', false); }

    function toggleContext(): void {
        showContext = !showContext;
        dispatch('contextchange', showContext);
    }

    // ---- Auto-fix handler ----
    async function handleAutoFix(): Promise<void> {
        if (!item.auto_fix || autoFixApplied) return;
        const autoFix = item.auto_fix;
        const targetSeg = getSegByChapterIndex(item.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const segChapter = targetSeg.chapter ?? item.chapter;
        const wasDirty = isSegmentDirty(segChapter, targetSeg.index);
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
            validationCategory="missing_words"
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
