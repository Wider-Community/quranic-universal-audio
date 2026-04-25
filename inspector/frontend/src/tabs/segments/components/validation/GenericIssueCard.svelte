<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';

    import {
        getAdjacentSegments,
        getChapterSegments,
        segAllData,
        selectedChapter,
    } from '../../stores/chapter';
    import { segConfig } from '../../stores/config';
    import {
        dirtyTick,
        getChapterOpsSnapshot,
        isSegmentDirty,
    } from '../../stores/dirty';
    import { historyData } from '../../stores/history';
    import { IssueRegistry } from '../../domain/registry';
    import { isIgnoredFor } from '../../utils/validation/classified-issues';
    import { resolveIssueSeg } from '../../utils/validation/resolve-issue';
    import { getSplitGroupMembers } from '../../utils/validation/split-group';
    import { ignoreIssueOnSegment } from '../../utils/edit/ignore';
    import type { SegValAnyItem, SegValBoundaryAdjItem } from '../../../../lib/types/api';
    import type { Segment } from '../../../../lib/types/domain';
    import SegmentRow from '../list/SegmentRow.svelte';

    const dispatch = createEventDispatcher<{ contextchange: boolean }>();

    // ---- Props ----
    export let category: string;
    export let item: SegValAnyItem;

    // ---- State ----
    let showContext = false;
    let isAlreadyIgnored = false;
    // Bind to the first-resolved segment's UID so subsequent resolutions stay
    // pinned to the same logical segment across split/merge reindexing. Once
    // bound, `_resolveIssue` looks up by UID first and only falls back to the
    // (chapter, seg_index) + ref heuristic when the UID is missing.
    let _boundUid: string | null = null;

    // ---- Derived ----
    $: boundaryItem = category === 'boundary_adj' ? (item as SegValBoundaryAdjItem) : null;
    $: issueMsg = (item as { msg?: string }).msg;

    // Subscribe to segAllData so resolvedSeg re-derives after split/merge
    // mutates item.seg_index in place. _resolveIssue reads segAllData via
    // getSegByChapterIndex / getChapterSegments; the extra reference here
    // forces the reactive statement to register the dependency.
    $: segStoreTick = $segAllData;
    // Wrap in a local helper — passing `_boundUid` directly as an argument
    // would make Svelte see a cyclical dep (`resolvedSeg` → `_boundUid` →
    // `resolvedSeg`). Reading it inside a called function hides it from the
    // reactive-dep walker; the `segStoreTick` re-fire handles re-derivation.
    function _resolveLocal(it: SegValAnyItem, cat: string): Segment | null {
        return resolveIssueSeg(it, cat, _boundUid);
    }
    $: resolvedSeg = (void segStoreTick, _resolveLocal(item, category));
    // Pin to the first resolution's UID. After this, resolvedSeg only tracks
    // that specific segment — even if the seg is split (firstHalf keeps the
    // UID) or merged into (first.uid is kept). If the seg is deleted or
    // consumed by a merge, resolvedSeg collapses to null and the card body
    // hides via `{#if resolvedSeg}`.
    $: if (!_boundUid && resolvedSeg) _boundUid = resolvedSeg.segment_uid ?? null;

    // Base gate from the registry; ``low_confidence`` adds a runtime guard so
    // a segment whose confidence has been promoted to 1.0 (e.g. after a save
    // edit) doesn't keep offering the Ignore button.
    $: canIgnore =
        resolvedSeg != null &&
        (IssueRegistry[category]?.canIgnore ?? false) &&
        (category !== 'low_confidence' || (resolvedSeg.confidence ?? 1) < 1.0);

    $: segChapterForBtn =
        resolvedSeg != null ? (resolvedSeg.chapter ?? parseInt(get(selectedChapter))) : 0;

    $: isDirtySegment = (
        $dirtyTick,
        resolvedSeg != null
            ? isSegmentDirty(segChapterForBtn, resolvedSeg.index)
            : false
    );

    $: ctxMode = $segConfig.accordionContext?.[category] ?? 'hidden';
    $: ctxDefaultOpen = ctxMode !== 'hidden';
    $: ctxNextOnly = ctxMode === 'next_only';

    $: showPhonemes =
        category === 'boundary_adj' &&
        $segConfig.showBoundaryPhonemes &&
        !isDirtySegment &&
        !!(boundaryItem?.gt_tail || boundaryItem?.asr_tail);

    // Split-group expansion: once a resolvedSeg has been split, render every
    // descendant in the main slot so the accordion card grows with the split
    // rather than hopping between halves. Prev/Next anchor to segments outside
    // the group. `getSplitGroupMembers` returns [] when no split has touched
    // the seg — we fall back to the single resolvedSeg render.
    //
    // Dependencies: $segAllData (segStoreTick) covers chapter-seg re-derivation;
    // $historyData picks up newly-saved batches; $dirtyTick ensures the op log
    // snapshot refreshes after each in-progress split mutation.
    $: _groupChapter = ((): number => {
        if (resolvedSeg?.chapter != null) return resolvedSeg.chapter;
        const parsed = parseInt(get(selectedChapter));
        return Number.isFinite(parsed) ? parsed : 0;
    })();
    // Memoize the split-group computation by a length-based fingerprint key.
    // `getSplitGroupMembers` runs a multi-pass fixpoint over every split op
    // in both the edit-history batches and the current op log; firing it on
    // every `$segAllData` / `$dirtyTick` / `$historyData` tick multiplies
    // with N accordion cards mounted.
    //
    // Length fingerprints are safe because every mutation path that grows a
    // group (split op) ALSO grows `opLog` or `historyBatches` by at least
    // one entry — the cache gets invalidated on the same tick. Pure in-place
    // mutations of existing segs (trim / ref-edit) don't change group
    // membership, so the stale memo is correct for them.
    let _splitGroupMemoKey = '';
    let _splitGroupMemoResult: Segment[] = [];
    $: {
        void segStoreTick; void $dirtyTick;
        if (_boundUid != null && _groupChapter > 0) {
            const chapterSegs = getChapterSegments(_groupChapter);
            const batches = $historyData?.batches ?? [];
            const ops = getChapterOpsSnapshot(_groupChapter);
            const key = `${_groupChapter}|${_boundUid}|${chapterSegs.length}|${batches.length}|${ops.length}`;
            if (key !== _splitGroupMemoKey) {
                _splitGroupMemoKey = key;
                _splitGroupMemoResult = getSplitGroupMembers(
                    _groupChapter, _boundUid, chapterSegs, batches, ops,
                );
            }
        } else if (_splitGroupMemoKey !== '') {
            _splitGroupMemoKey = '';
            _splitGroupMemoResult = [];
        }
    }
    $: groupMembers = _splitGroupMemoResult;
    $: mainMembers = groupMembers.length > 0
        ? groupMembers
        : (resolvedSeg ? [resolvedSeg] : []);
    $: firstMember = mainMembers[0] ?? null;
    $: lastMember = mainMembers.length > 0 ? mainMembers[mainMembers.length - 1] ?? null : null;

    $: prevSeg = ((): Segment | null => {
        if (!showContext || ctxNextOnly || !firstMember || firstMember.chapter == null) return null;
        const p = getAdjacentSegments(firstMember.chapter, firstMember.index).prev;
        // Guard against prev being itself a split-group member (shouldn't
        // happen given time_start sort + splice, but keeps the contract safe).
        if (p && p.segment_uid && groupMembers.some((m) => m.segment_uid === p.segment_uid)) return null;
        return p;
    })();
    $: nextSeg = ((): Segment | null => {
        if (!showContext || !lastMember || lastMember.chapter == null) return null;
        const n = getAdjacentSegments(lastMember.chapter, lastMember.index).next;
        if (n && n.segment_uid && groupMembers.some((m) => m.segment_uid === n.segment_uid)) return null;
        return n;
    })();

    // Open default context once resolvedSeg becomes available.
    let _didAutoOpen = false;
    $: if (resolvedSeg && ctxDefaultOpen && !_didAutoOpen) {
        showContext = true;
        _didAutoOpen = true;
    }

    // Track ignored state reactively.
    $: if (resolvedSeg) {
        isAlreadyIgnored = isIgnoredFor(resolvedSeg, category);
    }

    // ---- Public interface (forwarded from ErrorCard dispatcher) ----
    export function getIsContextShown(): boolean { return showContext; }
    export function showContextForced(): void { showContext = true; dispatch('contextchange', true); }
    export function hideContextForced(): void { showContext = false; dispatch('contextchange', false); }

    function toggleContext(): void {
        showContext = !showContext;
        dispatch('contextchange', showContext);
    }

    // ---- Ignore handler ----
    function handleIgnore(): void {
        if (!resolvedSeg) return;
        try {
            if (ignoreIssueOnSegment(resolvedSeg, category)) {
                isAlreadyIgnored = true;
            }
        } catch (err) {
            console.warn('Ignore: dispatch failed:', err);
        }
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
        {#each mainMembers as m (m.segment_uid ?? `${m.chapter}:${m.index}`)}
            <SegmentRow
                seg={m}
                showGotoBtn={true}
                showPlayBtn={true}
                showChapter={true}
                validationCategory={category}
            />
            {#if showPhonemes && boundaryItem && m.segment_uid === _boundUid}
                <div class="val-phoneme-tail">
                    <span class="val-tail-label">GT:</span>
                    <span class="val-tail-phonemes">{boundaryItem.gt_tail || ''}</span>
                    <span class="val-tail-label">ASR:</span>
                    <span class="val-tail-phonemes">{boundaryItem.asr_tail || ''}</span>
                </div>
            {/if}
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
