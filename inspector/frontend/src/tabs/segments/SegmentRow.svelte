<script lang="ts">
    /**
     * SegmentRow — one .seg-row card in the segments list.
     *
     * Mirrors the imperative `renderSegCard` helper (kept in Wave-5 under
     * `lib/utils/segments-rendering.ts` for validation/history/edit modules
     * that still render cards imperatively). The two renderers MUST stay in
     * DOM sync (class names, data attributes, child order) — edit-delegation
     * + waveform observer + playback code query the same selectors.
     *
     * History-mode props (S2-D23): Wave 10 needs the same component for
     * history op cards; accepted from day one so the signature is stable.
     * Highlight props (splitHL / trimHL / mergeHL / changedFields) are
     * declared but not yet consumed — Wave 6 (waveform) + Wave 10 (history)
     * implement the visual overlays.
     *
     * Layout: normal mode = horizontal (play-col | left-col | text-box).
     * History mode = vertical (waveform above text) — scoped via `class:mode-history`.
     *
     * DOM refs: purely declarative via {#if}/{#each} + data-* attrs. No
     * bind:this needed; the parent list attaches an IntersectionObserver to
     * `canvas[data-needs-waveform]` via a post-render walk (see SegmentsList).
     */

    import type { Segment } from '../../types/domain';
    import type {
        MergeHighlight,
        SplitHighlight,
        TrimHighlight,
    } from '../../segments/waveform/types';
    import { getAdjacentSegments } from '../../lib/stores/segments/chapter';
    import {
        _addVerseMarkers,
        formatRef,
        formatTimeMs,
    } from '../../segments/references';
    import { isIndexDirty } from '../../segments/state';

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
    /** Provisioning slot (S2-D23) — Wave 6 applies overlay. */
    export let splitHL: SplitHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 6 applies overlay. */
    export let trimHL: TrimHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 6 applies overlay. */
    export let mergeHL: MergeHighlight | null = null;
    /** Provisioning slot (S2-D23) — Wave 10 marks changed fields in the card. */
    export let changedFields: Set<'ref' | 'duration' | 'conf' | 'body'> | null = null;
    /** `history` mode = vertical layout (waveform above text). */
    export let mode: 'normal' | 'history' = 'normal';
    /** Fallback chapter when `seg.chapter` is null — only used for dirty lookup. */
    export let fallbackChapter: number = 0;

    // These props intentionally unused in Wave 5 (S2-D23 provisioning slots);
    // referenced so strict unused-prop TS doesn't flag them.
    $: if (splitHL || trimHL || mergeHL || changedFields) void 0;

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
    $: bodyText = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';
    $: confText = seg.matched_ref ? ((seg.confidence ?? 0) * 100).toFixed(1) + '%' : 'FAIL';
    $: indexLabel = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    function getConfClass(s: Segment): string {
        if (!s.matched_ref) return 'conf-fail';
        const conf = s.confidence ?? 0;
        if (conf >= 0.80) return 'conf-high';
        if (conf >= 0.60) return 'conf-mid';
        return 'conf-low';
    }
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
        <canvas width="380" height="60" data-needs-waveform></canvas>
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
                <span class="seg-text-ref">{formatRef(seg.matched_ref)}</span>
                <span class="seg-text-sep">|</span>
                <span class="seg-text-duration" title={durTitle}>{durSec.toFixed(1)}s</span>
                {#if showMissingTag}
                    <span class="seg-tag seg-tag-missing">Missing words</span>
                {/if}
            </div>
            <span class="seg-text-conf {confClass}">{confText}</span>
            {#if contextLabel}
                <div class="seg-text-label">{contextLabel}</div>
            {/if}
        </div>
        <div class="seg-text-body">{bodyText}</div>
    </div>
</div>
