<script lang="ts">
    /**
     * SegmentRow — one .seg-row card in the segments list.
     *
     * Per-button on:click handlers replace the container-level delegated
     * click router. SegmentRow is mounted via {#each} in SegmentsList.svelte
     * for the primary list (#seg-list) — imperatively rendered cards used
     * inside validation accordions, history view, and save preview still use
     * the delegated listeners wired in lib/utils/segments/imperative-card-click.ts.
     *
     * History-mode props accepted from day one. Highlight props (splitHL /
     * trimHL / mergeHL / changedFields) drive visual overlays in history mode.
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
    import { onMount } from 'svelte';

    import {
        getAdjacentSegments,
        segAllData,
        segCurrentIdx,
        selectedChapter,
    } from '../../lib/stores/segments/chapter';
    import {
        _addVerseMarkers,
        formatRef,
        formatTimeMs,
    } from '../../lib/utils/segments/references';
    import { isIndexDirty } from '../../lib/stores/segments/dirty';
    import { editMode } from '../../lib/stores/segments/edit';
    import { activeFilters } from '../../lib/stores/segments/filters';
    import { savedFilterView } from '../../lib/stores/segments/navigation';
    import type {
        MergeHighlight,
        SegCanvas,
        SplitHighlight,
        TrimHighlight,
    } from '../../lib/types/segments-waveform';
    import { getConfClass } from '../../lib/utils/segments/conf-class';
    import { _ensureWaveformObserver } from '../../lib/utils/segments/waveform-utils';
    import { dom } from '../../lib/segments-state';
    import { deleteSegment } from '../../lib/utils/segments/edit-delete';
    import { enterEditWithBuffer } from '../../lib/utils/segments/edit-common';
    import { mergeAdjacent } from '../../lib/utils/segments/edit-merge';
    import { startRefEdit } from '../../lib/utils/segments/edit-reference';
    import { jumpToSegment } from '../../lib/utils/segments/navigation-actions';
    import { playFromSegment } from '../../lib/utils/segments/playback';
    import type { Segment } from '../../types/domain';

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

    // Derived values
    $: chapterForDirty = seg.chapter ?? fallbackChapter;
    $: dirty = !readOnly && isIndexDirty(chapterForDirty, seg.index);
    $: confClass = getConfClass(seg);
    $: durSec = (seg.time_end - seg.time_start) / 1000;
    $: durTitle = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;
    $: adj = !readOnly && !isContext && !showGotoBtn
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
    $: confText = seg.matched_ref ? ((seg.confidence ?? 0) * 100).toFixed(1) + '%' : 'FAIL';
    $: indexLabel = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    // ---------------------------------------------------------------------
    // Waveform observer registration
    // ---------------------------------------------------------------------
    let canvasEl: HTMLCanvasElement | undefined;
    let rowEl: HTMLElement;

    onMount(() => {
        if (!canvasEl) return;
        const observer = _ensureWaveformObserver();
        observer.observe(canvasEl);
        return () => {
            // IntersectionObserver doesn't strongly retain disconnected nodes,
            // but unobserve explicitly avoids dangling entries when rows are
            // recycled mid-edit (e.g. split → re-render).
            observer.unobserve(canvasEl!);
        };
    });

    // ---------------------------------------------------------------------
    // Per-button handlers (replace delegated click router for #seg-list rows)
    // ---------------------------------------------------------------------

    function onPlayClick(e: MouseEvent): void {
        e.stopPropagation();
        if (readOnly) return;
        const idx = seg.index;
        const chapter = seg.chapter ?? 0;
        if (idx === get(segCurrentIdx) && !dom.segAudioEl.paused) {
            dom.segAudioEl.pause();
        } else {
            playFromSegment(idx, chapter);
        }
    }

    function onGotoClick(e: MouseEvent): void {
        e.stopPropagation();
        const filters = get(activeFilters);
        if (filters.some(f => f.value !== null)) {
            savedFilterView.set({
                filters: JSON.parse(JSON.stringify(filters)),
                chapter: get(selectedChapter),
                verse: dom.segVerseSelect.value,
                scrollTop: dom.segListEl.scrollTop,
            });
        }
        jumpToSegment(seg.chapter ?? 0, seg.index);
    }

    function onAdjustClick(e: MouseEvent): void {
        e.stopPropagation();
        enterEditWithBuffer(seg, rowEl, 'trim', null);
    }

    function onSplitClick(e: MouseEvent): void {
        e.stopPropagation();
        enterEditWithBuffer(seg, rowEl, 'split', null);
    }

    function onMergePrevClick(e: MouseEvent): void {
        e.stopPropagation();
        mergeAdjacent(seg, 'prev', null);
    }

    function onMergeNextClick(e: MouseEvent): void {
        e.stopPropagation();
        mergeAdjacent(seg, 'next', null);
    }

    function onDeleteClick(e: MouseEvent): void {
        e.stopPropagation();
        deleteSegment(seg, rowEl, null);
    }

    function onEditRefClick(e: MouseEvent): void {
        e.stopPropagation();
        const refSpan = rowEl.querySelector<HTMLElement>('.seg-text-ref');
        if (refSpan) startRefEdit(refSpan, seg, rowEl, null);
    }

    function onRefTextClick(e: MouseEvent): void {
        if (readOnly) return;
        e.stopPropagation();
        const target = e.currentTarget as HTMLElement;
        startRefEdit(target, seg, rowEl, null);
    }

    function onRowClick(e: MouseEvent): void {
        if (get(editMode) || readOnly) return;
        const t = e.target as Element;
        if (t.closest('.seg-play-col') || t.closest('.seg-actions') || t.closest('canvas') || t.closest('.seg-text-ref')) return;
        playFromSegment(seg.index, seg.chapter ?? 0);
    }

    function _seekFromCanvasEvent(e: MouseEvent, canvas: SegCanvas): void {
        const rect = canvas.getBoundingClientRect();
        const progress = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const hl = canvas._splitHL;
        const tStart = hl ? hl.wfStart : seg.time_start;
        const tEnd = hl ? hl.wfEnd : seg.time_end;
        const timeMs = tStart + progress * (tEnd - tStart);

        if (seg.index === get(segCurrentIdx) && !dom.segAudioEl.paused) {
            dom.segAudioEl.currentTime = timeMs / 1000;
        } else {
            playFromSegment(seg.index, seg.chapter ?? 0, timeMs);
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
    class:seg-row-context={isContext}
    class:seg-neighbour={isNeighbour}
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
    {#if !isContext && !readOnly}
        <div class="seg-play-col">
            <button class="btn btn-sm seg-card-play-btn" title="Play segment audio" on:click={onPlayClick}>&#9654;</button>
            {#if showGotoBtn}
                <button class="btn btn-sm seg-card-goto-btn" on:click={onGotoClick}>Go to</button>
            {/if}
        </div>
    {/if}

    <div class="seg-left">
        {#if readOnly && showPlayBtn}
            <button class="btn btn-sm seg-card-play-btn" title="Play segment audio">&#9654;</button>
        {/if}
        <canvas
            bind:this={canvasEl}
            width="380"
            height="60"
            data-needs-waveform
            on:mousedown={onCanvasMousedown}
        ></canvas>
        {#if !isContext && !readOnly}
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
        {:else if isContext}
            <button class="btn btn-sm seg-card-play-btn" hidden></button>
        {/if}
    </div>

    <div class="seg-text {confClass}">
        <div class="seg-text-meta">
            <div class="seg-text-header">
                <span class="seg-text-index">{indexLabel}</span>
                <span class="seg-text-sep">|</span>
                <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
                <span class="seg-text-ref" class:seg-history-changed={changedRef} on:click={onRefTextClick}>{formatRef(seg.matched_ref, $segAllData?.verse_word_counts)}</span>
                <span class="seg-text-sep">|</span>
                <span class="seg-text-duration" class:seg-history-changed={changedDur} title={durTitle}>{durSec.toFixed(1)}s</span>
                {#if showMissingTag}
                    <span class="seg-tag seg-tag-missing">Missing words</span>
                {/if}
            </div>
            <span class="seg-text-conf {confClass}" class:seg-history-changed={changedConf}>{confText}</span>
            {#if contextLabel}
                <div class="seg-text-label">{contextLabel}</div>
            {/if}
        </div>
        <div class="seg-text-body" class:seg-history-changed={changedBody}>{bodyText}</div>
    </div>
</div>
