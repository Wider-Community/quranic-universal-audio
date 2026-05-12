<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    import type { SegValAutoFix,SegValMissingWordsItem } from '../../../../lib/types/api';
    import type { Segment } from '../../../../lib/types/domain';
    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
        segAllData,
    } from '../../stores/chapter';
    import { segConfig } from '../../stores/config';
    import {
        dirtyTick,
        getChapterOpsSnapshot,
    } from '../../stores/dirty';
    import { historyData } from '../../stores/history';
    import { autoFixMissingWord } from '../../utils/edit/auto-fix';
    import { getSplitGroupMembers } from '../../utils/validation/split-group';
    import SegmentRow from '../list/SegmentRow.svelte';

    const dispatch = createEventDispatcher<{ contextchange: boolean }>();

    // ---- Props ----
    export let item: SegValMissingWordsItem;

    // ---- State ----
    let showContext = false;

    $: ctxMode = $segConfig.accordionContext?.['missing_words'] ?? 'hidden';
    $: ctxDefaultOpen = ctxMode !== 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

    // Segments in the gap range. Subscribes to segAllData so the list
    // re-derives after split/merge mutates indices in place. For each base
    // seg, include its full split-group (transitive descendants) so splits
    // inside the gap stay visible rather than snapping to whichever half
    // currently holds the original index. Preserves source order and dedupes
    // by UID — groups themselves are time-sorted, so relative position is
    // meaningful.
    //
    // Memoized by split-op-only fingerprint over (chapterSegs, splitOps, base
    // UIDs) — see GenericIssueCard for the invariant rationale. Counting only
    // split ops (not all batches/ops) keeps trim/ref-edit ops as cache hits.
    // Prevents a N-card accordion × M-gap-segment re-walk of every split op
    // on every reactive tick.
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
        let splitOpsCount = 0;
        for (const b of batches) {
            for (const op of b.operations) {
                if (op.op_type === 'split_segment') splitOpsCount++;
            }
        }
        for (const op of ops) {
            if (op.op_type === 'split_segment') splitOpsCount++;
        }
        const key = `${item.chapter}|${(item.seg_indices ?? []).join(',')}|${baseUids.join(',')}|${chapterSegs.length}|${splitOpsCount}`;
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

    let _didAutoOpen = false;
    $: if (segmentsInRange.length > 0 && ctxDefaultOpen && !_didAutoOpen) {
        showContext = true;
        _didAutoOpen = true;
    }

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

    // Ordered sibling list — render order — passed to every SegmentRow so
    // playback prefetch can warm the next sibling's clip URL by list
    // position. Mirrors the template below exactly.
    $: siblings = ((): Segment[] => {
        const out: Segment[] = [];
        if (prevSeg) out.push(prevSeg);
        for (const s of segmentsInRange) out.push(s);
        if (nextSeg) out.push(nextSeg);
        return out;
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
    function handleAutoFix(autoFix: SegValAutoFix | undefined): void {
        if (!autoFix) return;
        const targetSeg = getSegByChapterIndex(item.chapter, autoFix.target_seg_index);
        if (!targetSeg) return;
        const newRef = `${autoFix.new_ref_start}-${autoFix.new_ref_end}`;
        autoFixMissingWord(targetSeg, newRef);
    }

</script>

<div>
    <div class="val-card-gap-label">{item.msg || 'Missing words between segments'}</div>
    {#if prevSeg}
        <SegmentRow
            seg={prevSeg}
            isContext={true}
            contextLabel="Previous"
            showPlayBtn={true}
            showChapter={true}
            accordionSiblings={siblings}
        />
    {/if}
    {#each segmentsInRange as s (s.segment_uid ?? `${s.chapter}:${s.index}`)}
        <SegmentRow
            seg={s}
            showGotoBtn={true}
            showPlayBtn={true}
            showChapter={true}
            validationCategory="missing_words"
            accordionSiblings={siblings}
        />
    {/each}
    {#if nextSeg}
        <SegmentRow
            seg={nextSeg}
            isContext={true}
            contextLabel="Next"
            showPlayBtn={true}
            showChapter={true}
            accordionSiblings={siblings}
        />
    {/if}
    <div class="val-card-actions">
        {#if item.auto_fix}
            <button
                class="val-action-btn"
                title="Extend segment ref to cover the missing word"
                on:click={() => handleAutoFix(item.auto_fix)}
            >Auto Fill</button>
        {:else if item.auto_fix_up && item.auto_fix_down}
            <button
                class="val-action-btn"
                title="Extend previous segment to cover the missing word"
                on:click={() => handleAutoFix(item.auto_fix_up)}
            >Auto Fill Up</button>
            <button
                class="val-action-btn"
                title="Extend next segment to cover the missing word"
                on:click={() => handleAutoFix(item.auto_fix_down)}
            >Auto Fill Down</button>
        {/if}
        <button
            class="val-action-btn val-action-btn-muted val-ctx-toggle-btn"
            on:click={toggleContext}
        >{showContext ? 'Hide Context' : 'Show Context'}</button>
    </div>
</div>
