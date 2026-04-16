<script lang="ts">
    /**
     * SegmentRow — one .seg-row card in the segments list.
     *
     * Wave 7 adopted: this component is now mounted via {#each} in
     * SegmentsList.svelte (no longer "provisioned-but-unused"). The imperative
     * `renderSegList` / `renderSegCard` helpers in segments/rendering.ts stay
     * for validation accordions + history view (read-only / accordion contexts);
     * #seg-list itself is fully Svelte-driven now.
     *
     * History-mode props (S2-D23) accepted from day one. Highlight props
     * (splitHL / trimHL / mergeHL / changedFields) are still future-Wave
     * provisioning slots — Wave 10 implements the visual overlays.
     *
     * Layout: normal mode = horizontal (play-col | left-col | text-box).
     * History mode = vertical (waveform above text) — scoped via `class:mode-history`.
     *
     * Waveform observer: onMount registers the canvas with the segments
     * IntersectionObserver via _ensureWaveformObserver().observe(canvas).
     * On destroy the canvas is implicitly unobserved (the observer's weak
     * tracking releases destroyed nodes; see segments/waveform/index.ts).
     */

    import { onMount } from 'svelte';

    import { getAdjacentSegments, segAllData } from '../../lib/stores/segments/chapter';
    import {
        _addVerseMarkers,
        formatRef,
        formatTimeMs,
    } from '../../lib/utils/segments/references';
    import { isIndexDirty } from '../../segments/state';
    import type {
        MergeHighlight,
        SegCanvas,
        SplitHighlight,
        TrimHighlight,
    } from '../../lib/types/segments-waveform';
    import { getConfClass } from '../../lib/utils/segments/conf-class';
    import { _ensureWaveformObserver } from '../../lib/utils/segments/waveform-utils';
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
    /** Provisioning slot (S2-D23) — Wave 10 applies overlay. */
    export let splitHL: SplitHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 10 applies overlay. */
    export let trimHL: TrimHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 10 applies overlay. */
    export let mergeHL: MergeHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 10 marks changed fields in the card. */
    export let changedFields: Set<'ref' | 'duration' | 'conf' | 'body'> | null = null;
    /** `history` mode = vertical layout (waveform above text). */
    export let mode: 'normal' | 'history' = 'normal';
    /** Fallback chapter when `seg.chapter` is null — only used for dirty lookup. */
    export let fallbackChapter: number = 0;

    // Wave 10: apply history-mode highlight descriptors to the underlying
    // canvas element so the IntersectionObserver draw pipeline
    // (segments/waveform/index.ts + draw.ts) can read them via the SegCanvas
    // ad-hoc fields. `canvasEl` is bound below; these statements run after
    // it is assigned and re-run when any prop changes.
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
    // Wave 10: history-mode changed-field markers. `changedFields` is an
    // optional Set that lists which per-row text spans should receive the
    // `seg-history-changed` CSS class (preserved verbatim from the
    // imperative _highlightChanges impl in rendering.ts).
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
</script>

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
>
    {#if !isContext && !readOnly}
        <div class="seg-play-col">
            <button class="btn btn-sm seg-card-play-btn" title="Play segment audio">&#9654;</button>
            {#if showGotoBtn}
                <button class="btn btn-sm seg-card-goto-btn">Go to</button>
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
        ></canvas>
        {#if !isContext && !readOnly}
            <div class="seg-actions">
                <button class="btn btn-sm btn-adjust">Adjust</button>
                <button class="btn btn-sm btn-merge-prev"
                    disabled={mergePrevDisabled}
                    title={mergePrevTitle}>Merge &uarr;</button>
                <button class="btn btn-sm btn-delete">Delete</button>
                <button class="btn btn-sm btn-split">Split</button>
                <button class="btn btn-sm btn-merge-next"
                    disabled={mergeNextDisabled}
                    title={mergeNextTitle}>Merge &darr;</button>
                <button class="btn btn-sm btn-edit-ref">Edit Ref</button>
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
                <span class="seg-text-ref" class:seg-history-changed={changedRef}>{formatRef(seg.matched_ref, $segAllData?.verse_word_counts)}</span>
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
