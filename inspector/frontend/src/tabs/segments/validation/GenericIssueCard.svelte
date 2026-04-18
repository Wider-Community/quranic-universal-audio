<script lang="ts">
    import { get } from 'svelte/store';

    import {
        getAdjacentSegments,
        getChapterSegments,
        getSegByChapterIndex,
        segAllData,
        selectedChapter,
    } from '../../../lib/stores/segments/chapter';
    import { segConfig } from '../../../lib/stores/segments/config';
    import {
        createOp,
        finalizeOp,
        getDirtyMap,
        markDirty,
        snapshotSeg,
    } from '../../../lib/stores/segments/dirty';
    import { _isIgnoredFor } from '../../../lib/utils/segments/classify';
    import type {
        SegValAnyItem,
        SegValBoundaryAdjItem,
        Segment,
    } from '../../../types/domain';
    import SegmentRow from '../SegmentRow.svelte';

    // ---- Props ----
    export let category: string;
    export let item: SegValAnyItem;

    // ---- State ----
    let showContext = false;
    let isAlreadyIgnored = false;

    // ---- Derived ----
    $: boundaryItem = category === 'boundary_adj' ? (item as SegValBoundaryAdjItem) : null;
    $: issueMsg = (item as { msg?: string }).msg;

    // Subscribe to segAllData so resolvedSeg re-derives after split/merge
    // mutates item.seg_index in place. _resolveIssue reads segAllData via
    // getSegByChapterIndex / getChapterSegments; the extra reference here
    // forces the reactive statement to register the dependency.
    $: segStoreTick = $segAllData;
    $: resolvedSeg = (void segStoreTick, _resolveIssue(item, category));

    $: canIgnore =
        resolvedSeg != null &&
        (category === 'boundary_adj' ||
            category === 'cross_verse' ||
            category === 'audio_bleeding' ||
            category === 'repetitions' ||
            category === 'qalqala' ||
            (category === 'low_confidence' && (resolvedSeg.confidence ?? 1) < 1.0));

    $: segChapterForBtn =
        resolvedSeg != null ? (resolvedSeg.chapter ?? parseInt(get(selectedChapter))) : 0;

    $: isDirtySegment =
        resolvedSeg != null
            ? !!(getDirtyMap().get(segChapterForBtn)?.indices?.has(resolvedSeg.index))
            : false;

    $: ctxMode = $segConfig.accordionContext?.[category] ?? 'hidden';
    $: ctxDefaultOpen = ctxMode !== 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

    $: showPhonemes =
        category === 'boundary_adj' &&
        $segConfig.showBoundaryPhonemes &&
        !!(boundaryItem?.gt_tail || boundaryItem?.asr_tail);

    $: prevSeg =
        showContext && !ctxNextOnly && resolvedSeg != null && resolvedSeg.chapter != null
            ? getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index).prev
            : null;
    $: nextSeg =
        showContext && resolvedSeg != null && resolvedSeg.chapter != null
            ? getAdjacentSegments(resolvedSeg.chapter, resolvedSeg.index).next
            : null;

    // Open default context once resolvedSeg becomes available.
    let _didAutoOpen = false;
    $: if (resolvedSeg && ctxDefaultOpen && !_didAutoOpen) {
        showContext = true;
        _didAutoOpen = true;
    }

    // Track ignored state reactively.
    $: if (resolvedSeg) {
        isAlreadyIgnored = _isIgnoredFor(resolvedSeg, category);
    }

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; }
    export function hideContextForced(): void { showContext = false; }

    function toggleContext(): void {
        showContext = !showContext;
    }

    // ---- Segment resolution ----
    function _resolveIssue(it: SegValAnyItem, cat: string): Segment | null {
        const anyItem = it as { seg_index?: number; chapter: number; ref?: string };
        if (anyItem.seg_index != null && anyItem.seg_index < 0) return null;
        if (cat === 'errors') {
            const vk = (it as { verse_key?: string }).verse_key || '';
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
        const segChapter = resolvedSeg.chapter ?? parseInt(get(selectedChapter));
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
        isAlreadyIgnored = true;
    }
</script>

<div style:opacity={isAlreadyIgnored ? 0.5 : null}>
    {#if issueMsg}
        <div class="val-card-issue-label">{issueMsg}</div>
    {/if}
    {#if resolvedSeg}
        {#if prevSeg}
            <SegmentRow
                seg={prevSeg}
                isContext={true}
                contextLabel="Previous"
                showPlayBtn={true}
                showChapter={true}
            />
        {/if}
        <SegmentRow
            seg={resolvedSeg}
            showGotoBtn={true}
            showPlayBtn={true}
            showChapter={true}
        />
        {#if showPhonemes && boundaryItem}
            <div class="val-phoneme-tail">
                <span class="val-tail-label">GT:</span>
                <span class="val-tail-phonemes">{boundaryItem.gt_tail || ''}</span>
                <span class="val-tail-label">ASR:</span>
                <span class="val-tail-phonemes">{boundaryItem.asr_tail || ''}</span>
            </div>
        {/if}
        {#if nextSeg}
            <SegmentRow
                seg={nextSeg}
                isContext={true}
                contextLabel="Next"
                showPlayBtn={true}
                showChapter={true}
            />
        {/if}
    {/if}
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
