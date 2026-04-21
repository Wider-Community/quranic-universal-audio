<script lang="ts">
    /**
     * SegmentRow — one .seg-row card in the segments list.
     *
     * Used from every SegmentRow site: the primary list (#seg-list) via
     * SegmentsList.svelte, the validation accordion subcomponents
     * (GenericIssueCard / MissingWordsCard / MissingVersesCard), history
     * view (SplitChainRow / HistoryOp), and the save preview. Per-button
     * on:click handlers are wired directly here so no delegated container
     * listeners are needed.
     *
     * History-mode props. Highlight props (splitHL / trimHL / mergeHL /
     * changedFields) drive visual overlays in history mode.
     *
     * Layout: normal mode = horizontal (play-col | left-col | text-box).
     * History mode = vertical (waveform above text) — scoped via `class:mode-history`.
     *
     * Waveform observer: onMount registers the canvas with the segments
     * IntersectionObserver via _ensureWaveformObserver().observe(canvas).
     * On destroy the canvas is implicitly unobserved (the observer's weak
     * tracking releases destroyed nodes; see segments/waveform/index.ts).
     */

    import { get } from 'svelte/store';
    import { onMount, onDestroy } from 'svelte';

    import {
        getAdjacentSegments,
        segAllData,
        selectedChapter,
        selectedVerse,
    } from '../../stores/chapter';
    import {
        _addVerseMarkers,
        formatRef,
        formatTimeMs,
    } from '../../utils/data/references';
    import { dirtyTick, isIndexDirty } from '../../stores/dirty';
    import {
        editMode,
        editingMountId,
        editingSegUid,
        setEditCanvas,
    } from '../../stores/edit';
    import { activeFilters } from '../../stores/filters';
    import { savedFilterView } from '../../stores/navigation';
    import type {
        MergeHighlight,
        SegCanvas,
        SplitHighlight,
        TrimHighlight,
    } from '../../types/segments-waveform';
    import { getConfClass } from '../../utils/validation/conf-class';
    import { _ensureWaveformObserver } from '../../utils/waveform/utils';
    import {
        isMainAudioPlaying,
        playingSegmentIndex,
        segAudioElement,
        segListElement,
    } from '../../stores/playback';
    import {
        chapterIndexKey,
        flashSegmentIndices,
        targetSegmentIndex,
    } from '../../stores/navigation';
    import { deleteSegment } from '../../utils/edit/delete';
    import { enterEditWithBuffer } from '../../utils/edit/enter';
    import { mergeAdjacent } from '../../utils/edit/merge';
    import { beginRefEdit } from '../../utils/edit/reference';
    import { jumpToSegment } from '../../utils/data/navigation-actions';
    import { playFromSegment } from '../../utils/playback/playback';
    import { deregisterRow, registerRow } from '../../utils/playback/row-registry';
    import { SEG_ROW_CANVAS_WIDTH, SEG_ROW_CANVAS_HEIGHT } from '../../utils/constants';
    import type { Segment } from '../../../../lib/types/domain';

    import ReferenceEditor from '../edit/ReferenceEditor.svelte';
    import SplitPanel from '../edit/SplitPanel.svelte';
    import TrimPanel from '../edit/TrimPanel.svelte';
    import TimeRange from './TimeRange.svelte';

    // ---- Required ----
    export let seg: Segment;
    // ---- Optional rendering flags ----
    export let readOnly: boolean = false;
    export let showChapter: boolean = false;
    export let showPlayBtn: boolean = true;
    export let showGotoBtn: boolean = false;
    export let isContext: boolean = false;
    export let contextLabel: string = '';
    export let missingWordSegIndices: Set<number> | null = null;
    export let isNeighbour: boolean = false;
    /** Provisioning slot — overlay applied in history mode. */
    export let splitHL: SplitHighlight | null = null;
    /** Provisioning slot — overlay applied in history mode. */
    export let trimHL: TrimHighlight | null = null;
    /** Provisioning slot — overlay applied in history mode. */
    export let mergeHL: MergeHighlight | null = null;
    /** Provisioning slot — marks changed fields in the card. */
    export let changedFields: Set<'ref' | 'duration' | 'conf' | 'body'> | null = null;
    /** `history` mode = vertical layout (waveform above text). */
    export let mode: 'normal' | 'history' = 'normal';
    /** Fallback chapter when `seg.chapter` is null — only used for dirty lookup. */
    export let fallbackChapter: number = 0;
    /**
     * Which DOM context is rendering this row. Default `accordion` — the
     * most common non-readOnly placement (validation cards, ErrorCard
     * contexts). Only `main` reacts to `$targetSegmentIndex` scroll, so
     * a "Go to" or verse-pill jump always targets the main list even when
     * an identical row is mounted in an accordion twin. Only `main` also
     * claims a programmatic edit session (split-chain handoff, auto-fix,
     * keyboard `E`) when `editingMountId` is null. `history` / `preview`
     * rows are always readOnly and never participate in edit or scroll.
     */
    export let instanceRole: 'main' | 'accordion' | 'history' | 'preview' = 'accordion';
    /**
     * Validation category that initiated this row's rendering (e.g.
     * 'low_confidence', 'cross_verse'). Set by accordion cards on the
     * resolved (non-context) SegmentRow so every edit op started from
     * this row is tagged with its originating category — the save flow
     * then auto-adds the category to `ignored_categories` on commit so
     * the issue disappears from the accordion post-save. Context rows
     * (isContext=true) leave this null: editing a neighbour must not
     * auto-ignore the issue for the original seg.
     */
    export let validationCategory: string | null = null;

    // Apply history-mode highlight descriptors to the underlying canvas element
    // so the IntersectionObserver draw pipeline (segments/waveform/index.ts +
    // draw.ts) can read them via the SegCanvas ad-hoc fields. `canvasEl` is
    // bound below; these statements run after it is assigned and re-run when
    // any prop changes.
    $: if (canvasEl) {
        const c = canvasEl as SegCanvas;
        c._splitHL = splitHL ?? undefined;
        c._trimHL = trimHL ?? undefined;
        c._mergeHL = mergeHL ?? undefined;
    }

    // True only when this specific mounted row is the editing target. The
    // editing row is identified by (segment_uid) AND (initiating mountId).
    // When `editingMountId` is null the edit was started programmatically
    // (split-chain handoff, auto-fix, keyboard E) — the main-list instance
    // claims it so edit panels always appear in the main list, not on an
    // accordion twin. readOnly sites (history, save preview) share uids
    // with main-list rows and must never participate.
    $: isInitiatingEditRow = !readOnly
        && !!seg.segment_uid
        && $editingSegUid === seg.segment_uid
        && ($editingMountId === _mountId
            || ($editingMountId === null && instanceRole === 'main'));

    // Publish canvas to `editCanvas` store whenever THIS mounted row is the
    // active edit target. Replaces the legacy `_getEditCanvas()` document-
    // wide DOM query. UID alone is ambiguous across twin mounts; gating on
    // the initiating mountId keeps the accordion twin from clobbering the
    // main-list row's canvas (or vice-versa) after an edit starts.
    $: {
        if (isInitiatingEditRow && canvasEl) {
            setEditCanvas(canvasEl as SegCanvas);
        }
    }

    // True only for the one live row currently being edited (any mode).
    // Drives the conditional mount of TrimPanel / SplitPanel / ReferenceEditor
    // inside the row, the `.seg-edit-target` class binding, and the hiding of
    // the row control footer during persistent drag modes.
    $: isEditingThisRow = isInitiatingEditRow && $editMode !== null;
    $: editSegCanvas = canvasEl as SegCanvas | undefined;

    // Derived values. Seg-derived reactives also subscribe to $segAllData via
    // `segStoreTick` so they re-fire when refreshSegInStore bumps the store —
    // validation-card sites derive resolvedSeg from the store, so their seg
    // prop points to the refreshed object only after the store tick.
    $: segStoreTick = $segAllData;
    $: chapterForDirty = seg.chapter ?? fallbackChapter;
    $: dirty = (void $dirtyTick, !readOnly && isIndexDirty(chapterForDirty, seg.index));
    $: confClass = (void segStoreTick, getConfClass(seg));
    $: durSec = (void segStoreTick, (seg.time_end - seg.time_start) / 1000);
    $: durTitle = (void segStoreTick, `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`);
    $: adj = !readOnly && !isContext
        ? getAdjacentSegments(seg.chapter ?? 0, seg.index)
        : { prev: null, next: null };
    $: mergePrevDisabled = !adj.prev
        || (!!adj.prev?.audio_url && !!seg.audio_url && adj.prev.audio_url !== seg.audio_url);
    $: mergePrevTitle = !adj.prev
        ? 'No previous segment to merge with'
        : (adj.prev.audio_url && seg.audio_url && adj.prev.audio_url !== seg.audio_url)
        ? 'Cannot merge segments from different audio files'
        : '';
    $: mergeNextDisabled = !adj.next
        || (!!adj.next?.audio_url && !!seg.audio_url && adj.next.audio_url !== seg.audio_url);
    $: mergeNextTitle = !adj.next
        ? 'No next segment to merge with'
        : (adj.next.audio_url && seg.audio_url && adj.next.audio_url !== seg.audio_url)
        ? 'Cannot merge segments from different audio files'
        : '';
    $: showMissingTag = !!missingWordSegIndices && missingWordSegIndices.has(seg.index);
    // History-mode changed-field markers.
    $: changedRef = !!changedFields?.has('ref');
    $: changedDur = !!changedFields?.has('duration');
    $: changedConf = !!changedFields?.has('conf');
    $: changedBody = !!changedFields?.has('body');
    $: bodyText = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref, $segAllData?.verse_word_counts) || '(alignment failed)';
    $: confText = (void segStoreTick, seg.matched_ref ? ((seg.confidence ?? 0) * 100).toFixed(1) + '%' : 'FAIL');
    $: indexLabel = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    // ---------------------------------------------------------------------
    // Playback highlight + jump target (store-driven)
    // ---------------------------------------------------------------------
    // readOnly rows (history view, save preview) share seg.index with rows in
    // the main list. Guarding on !readOnly keeps them from lighting up when
    // the main-list row for the same index is playing or flashing. Validation
    // accordion rows (isContext=true) are NOT readOnly — they MUST light up
    // in sync with the main-list twin for the same segment.
    //
    // Active-pair match: both chapter AND index must match. The validation
    // panel can be mounted with chapter=null (all chapters), so same-index
    // rows in other chapters must not collide.
    $: rowChapter = seg.chapter ?? fallbackChapter;
    $: isPlaying = !readOnly
        && !!$playingSegmentIndex
        && $playingSegmentIndex.chapter === rowChapter
        && $playingSegmentIndex.index === seg.index;
    // flashSegmentIndices is keyed by "chapter:index" — both the main-list
    // and accordion twin for the correctly-matched pair still light up, but
    // a same-index row in a different chapter (validation panel with
    // chapter=null) no longer collides.
    $: rowFlashKey = chapterIndexKey(rowChapter, seg.index);
    $: isFlashing = !readOnly && $flashSegmentIndices.has(rowFlashKey);
    $: highlighted = isPlaying || isFlashing;
    $: playGlyph = isPlaying && $isMainAudioPlaying ? '\u25A0' : '\u25B6';

    // Scroll into view when jump target matches, then clear the store so the
    // next write re-fires reliably. Only the main-list instance reacts —
    // accordion / history / preview twins would otherwise race the main-list
    // row (the accordion's short scroll container usually wins), yanking
    // focus onto the accordion instead of the main list the user expects.
    // `rowEl` is bound below; wait for it.
    $: if (
        instanceRole === 'main'
        && !readOnly
        && rowEl
        && $targetSegmentIndex
        && $targetSegmentIndex.chapter === rowChapter
        && $targetSegmentIndex.index === seg.index
    ) {
        rowEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetSegmentIndex.set(null);
    }

    // Post-split ref-edit chain handoff is owned by
    // `utils/edit/reference.ts::commitRefEdit` now — it reads-and-clears
    // `pendingChainTarget` after clearEdit() and calls beginRefEdit
    // directly. No reactive store indirection, no subscriber race. The
    // accordion path routes via `mountId=null` which the secondHalf's
    // main-list row claims through the `instanceRole === 'main'` fallback.

    // ---------------------------------------------------------------------
    // Waveform observer registration
    // ---------------------------------------------------------------------
    let canvasEl: HTMLCanvasElement | undefined;
    let rowEl: HTMLElement;

    // Unique per-mount identifier — disambiguates twin deregistration so the
    // main-list row and an accordion row for the same segment can coexist
    // and unmount independently without clobbering each other's entry.
    const _mountId = Symbol('seg-row');

    // Track the (chapter, index) we most recently registered under so
    // structural mutations (split/merge/delete reindex) can deregister
    // under the OLD key before re-registering under the new one. Without
    // this, a shifted row would leave a stale entry in the registry keyed
    // to its pre-mutation index.
    let _prevRegChapter: number | null = null;
    let _prevRegIdx: number | null = null;

    onMount(() => {
        // Register every non-readOnly row — both the main-list and any
        // accordion twin. drawActivePlayhead iterates all entries for the
        // playing (chapter, index) so both instances render a synchronized
        // playhead. Keyed by (chapter, index) so same-index rows in different
        // chapters don't collide (validation panel with chapter=null).
        if (!readOnly && rowEl) {
            registerRow(rowChapter, seg.index, rowEl, canvasEl, _mountId, instanceRole);
            _prevRegChapter = rowChapter;
            _prevRegIdx = seg.index;
        }
        if (!canvasEl) return;
        const observer = _ensureWaveformObserver();
        observer.observe(canvasEl);
        return () => {
            observer.unobserve(canvasEl!);
        };
    });

    // Re-register under the new (chapter, index) key whenever seg.index or
    // rowChapter shifts (split/merge/delete reindex). Without this, the
    // registry would still point at the pre-mutation key, and
    // drawActivePlayhead would draw on the wrong row (or miss this row
    // entirely). Fires after onMount completes — the `_prevRegChapter !==
    // null` guard prevents double-registration with the initial mount.
    $: if (
        rowEl
        && !readOnly
        && (rowChapter !== _prevRegChapter || seg.index !== _prevRegIdx)
    ) {
        if (_prevRegChapter !== null && _prevRegIdx !== null) {
            deregisterRow(_prevRegChapter, _prevRegIdx, _mountId);
        }
        registerRow(rowChapter, seg.index, rowEl, canvasEl, _mountId, instanceRole);
        _prevRegChapter = rowChapter;
        _prevRegIdx = seg.index;
    }

    onDestroy(() => {
        // Use the stored prev values rather than the current (potentially
        // shifted) seg.index — otherwise a row that's been reindexed since
        // mount would deregister under the wrong key, leaving a ghost entry.
        if (!readOnly && _prevRegChapter !== null && _prevRegIdx !== null) {
            deregisterRow(_prevRegChapter, _prevRegIdx, _mountId);
        }
    });

    // ---------------------------------------------------------------------
    // Per-button handlers (replace delegated click router for #seg-list rows)
    // ---------------------------------------------------------------------

    function onPlayClick(e: MouseEvent): void {
        e.stopPropagation();
        if (readOnly) return;
        const idx = seg.index;
        const chapter = seg.chapter ?? fallbackChapter;
        const audioEl = get(segAudioElement);
        // Use the full (chapter, index) active pair so a context row for a
        // different chapter with the same index doesn't mistake itself for
        // the playing one and pause unrelated playback.
        const active = get(playingSegmentIndex);
        const isSelfPlaying = !!active
            && active.chapter === chapter
            && active.index === idx
            && audioEl && !audioEl.paused;
        if (isSelfPlaying) {
            audioEl.pause();
        } else {
            playFromSegment(idx, chapter);
        }
    }

    function onGotoClick(e: MouseEvent): void {
        e.stopPropagation();
        const filters = get(activeFilters);
        if (filters.some(f => f.value !== null)) {
            const listEl = get(segListElement);
            savedFilterView.set({
                filters: JSON.parse(JSON.stringify(filters)),
                chapter: get(selectedChapter),
                verse: get(selectedVerse),
                scrollTop: listEl?.scrollTop ?? 0,
            });
        }
        jumpToSegment(seg.chapter ?? 0, seg.index);
    }

    function onAdjustClick(e: MouseEvent): void {
        e.stopPropagation();
        enterEditWithBuffer(seg, rowEl, 'trim', validationCategory, _mountId);
    }

    function onSplitClick(e: MouseEvent): void {
        e.stopPropagation();
        enterEditWithBuffer(seg, rowEl, 'split', validationCategory, _mountId);
    }

    function onMergePrevClick(e: MouseEvent): void {
        e.stopPropagation();
        mergeAdjacent(seg, 'prev', validationCategory, _mountId);
    }

    function onMergeNextClick(e: MouseEvent): void {
        e.stopPropagation();
        mergeAdjacent(seg, 'next', validationCategory, _mountId);
    }

    function onDeleteClick(e: MouseEvent): void {
        e.stopPropagation();
        deleteSegment(seg, rowEl, validationCategory, _mountId);
    }

    function onEditRefClick(e: MouseEvent): void {
        e.stopPropagation();
        beginRefEdit(seg, validationCategory, _mountId);
    }

    function onRefTextClick(e: MouseEvent): void {
        if (readOnly) return;
        e.stopPropagation();
        beginRefEdit(seg, validationCategory, _mountId);
    }

    function onRowClick(e: MouseEvent): void {
        if (get(editMode) || readOnly) return;
        const t = e.target as Element;
        if (t.closest('.seg-row-controls') || t.closest('canvas') || t.closest('.seg-text-ref')) return;
        playFromSegment(seg.index, seg.chapter ?? 0);
    }

    function _seekFromCanvasEvent(e: MouseEvent, canvas: SegCanvas): void {
        const rect = canvas.getBoundingClientRect();
        const progress = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const hl = canvas._splitHL;
        const tStart = hl ? hl.wfStart : seg.time_start;
        const tEnd = hl ? hl.wfEnd : seg.time_end;
        const timeMs = tStart + progress * (tEnd - tStart);

        const audioEl = get(segAudioElement);
        const chapter = seg.chapter ?? fallbackChapter;
        const active = get(playingSegmentIndex);
        const isSelfPlaying = !!active
            && active.chapter === chapter
            && active.index === seg.index
            && audioEl && !audioEl.paused;
        if (isSelfPlaying) {
            audioEl.currentTime = timeMs / 1000;
        } else {
            playFromSegment(seg.index, chapter, timeMs);
        }
    }

    function onCanvasMousedown(e: MouseEvent): void {
        if (readOnly || get(editMode)) return;
        const canvas = e.currentTarget as SegCanvas;

        e.preventDefault();
        _seekFromCanvasEvent(e, canvas);

        function onMove(ev: MouseEvent): void {
            _seekFromCanvasEvent(ev, canvas);
        }
        function onUp(): void {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
        }
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
<div
    class="seg-row"
    class:dirty
    class:playing={highlighted}
    class:seg-row-context={isContext}
    class:seg-neighbour={isNeighbour}
    class:seg-edit-target={isEditingThisRow}
    class:mode-history={mode === 'history'}
    data-seg-index={seg.index}
    data-seg-chapter={seg.chapter ?? undefined}
    data-seg-uid={seg.segment_uid || undefined}
    data-hist-time-start={readOnly ? String(seg.time_start) : undefined}
    data-hist-time-end={readOnly ? String(seg.time_end) : undefined}
    data-hist-audio-url={readOnly && seg.audio_url ? seg.audio_url : undefined}
    bind:this={rowEl}
    on:click={onRowClick}
>
    <div class="seg-left">
        {#if readOnly && showPlayBtn}
            <button class="btn btn-sm seg-card-play-btn" title="Play segment audio">&#9654;</button>
        {/if}
        <canvas
            bind:this={canvasEl}
            width={SEG_ROW_CANVAS_WIDTH}
            height={SEG_ROW_CANVAS_HEIGHT}
            data-needs-waveform
            on:mousedown={onCanvasMousedown}
        ></canvas>
        {#if isEditingThisRow && $editMode === 'trim' && editSegCanvas}
            <TrimPanel {seg} canvas={editSegCanvas} />
        {:else if isEditingThisRow && $editMode === 'split' && editSegCanvas}
            <SplitPanel {seg} canvas={editSegCanvas} />
        {:else if !readOnly}
            <div class="seg-row-controls">
                {#if showPlayBtn || showGotoBtn}
                    <div class="seg-row-play-actions">
                        {#if showPlayBtn}
                            <button class="btn btn-sm seg-card-play-btn" title="Play segment audio" on:click={onPlayClick}>{playGlyph}</button>
                        {/if}
                        {#if showGotoBtn}
                            <button class="btn btn-sm seg-card-goto-btn" on:click={onGotoClick}>Go to</button>
                        {/if}
                    </div>
                {/if}

                {#if !isContext}
                    <div class="seg-actions">
                        <button class="btn btn-sm btn-adjust" on:click={onAdjustClick}>Adjust</button>
                        <button class="btn btn-sm btn-merge-prev"
                            disabled={mergePrevDisabled}
                            title={mergePrevTitle}
                            on:click={onMergePrevClick}>Merge &uarr;</button>
                        <button class="btn btn-sm btn-delete" on:click={onDeleteClick}>Delete</button>
                        <button class="btn btn-sm btn-split" on:click={onSplitClick}>Split</button>
                        <button class="btn btn-sm btn-merge-next"
                            disabled={mergeNextDisabled}
                            title={mergeNextTitle}
                            on:click={onMergeNextClick}>Merge &darr;</button>
                        <button class="btn btn-sm btn-edit-ref" on:click={onEditRefClick}>Edit Ref</button>
                    </div>
                {/if}
            </div>
        {/if}
    </div>

    <div class="seg-text {confClass}">
        <div class="seg-text-meta">
            <div class="seg-text-header">
                <span class="seg-text-index">{indexLabel}</span>
                <span class="seg-text-sep">|</span>
                {#if isEditingThisRow && $editMode === 'reference'}
                    <ReferenceEditor {seg} />
                {:else}
                    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
                    <span class="seg-text-ref" class:seg-history-changed={changedRef} on:click={onRefTextClick}>{formatRef(seg.matched_ref, $segAllData?.verse_word_counts)}</span>
                {/if}
                <span class="seg-text-sep">|</span>
                <span class="seg-text-conf {confClass}" class:seg-history-changed={changedConf}>{confText}</span>
                {#if showMissingTag}
                    <span class="seg-tag seg-tag-missing">Missing words</span>
                {/if}
            </div>
            <div class="seg-text-times" class:seg-history-changed={changedDur} title={durTitle}>
                <TimeRange
                    {seg}
                    {rowEl}
                    mountId={_mountId}
                    {validationCategory}
                    {instanceRole}
                    {readOnly}
                />
            </div>
            {#if contextLabel}
                <div class="seg-text-label">{contextLabel}</div>
            {/if}
        </div>
        <div class="seg-text-body" class:seg-history-changed={changedBody}>{bodyText}</div>
    </div>
</div>
