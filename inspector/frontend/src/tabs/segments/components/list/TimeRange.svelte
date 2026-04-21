<script lang="ts">
    /**
     * TimeRange — row-level time-from/to/duration display for SegmentRow.
     *
     * Thin owner of two <TimeEdit> widgets plus the duration readout. Handles:
     *   1. idle vs active-edit sourcing (seg.time_start/_end vs $trimWindow)
     *   2. side-specific bounds (windowStart/windowEnd clamped by the
     *      opposite handle + EDIT_MIN_DURATION_MS) passed to each TimeEdit
     *   3. entering trim mode on idle-row time clicks, via the same
     *      enterEditWithBuffer path the Adjust button uses
     *   4. pushing typed commits back into _trimWindow (store + canvas mirror
     *      + redraw) so the trim canvas handles track the typed value.
     *
     * Bounds are computed only when needed (active edit, or the moment the
     * user clicks a time on an idle row) — idle rows pay only a formatter
     * cost on render.
     */

    import { get } from 'svelte/store';

    import type { Segment } from '../../../../lib/types/domain';
    import { getWaveformPeaks } from '../../../../lib/utils/waveform-cache';
    import {
        getChapterSegments,
        getCurrentChapterSegs,
        segAllData,
        selectedChapter,
    } from '../../stores/chapter';
    import { segConfig } from '../../stores/config';
    import {
        editCanvas,
        editMode,
        editingMountId,
        editingSegUid,
        trimWindow,
        updateTrimWindow,
    } from '../../stores/edit';
    import type { SegCanvas, TrimWindow } from '../../types/segments-waveform';
    import { EDIT_MIN_DURATION_MS } from '../../utils/constants';
    import { formatDurationMs } from '../../utils/data/references';
    import { enterEditWithBuffer } from '../../utils/edit/enter';
    import { computeTrimBounds } from '../../utils/edit/trim';
    import { drawTrimWaveform } from '../../utils/waveform/trim-draw';
    import TimeEdit from './TimeEdit.svelte';

    export let seg: Segment;
    export let rowEl: HTMLElement | undefined;
    export let mountId: symbol | null = null;
    export let validationCategory: string | null = null;
    export let instanceRole: 'main' | 'accordion' | 'history' | 'preview' = 'accordion';
    export let readOnly: boolean = false;

    // Which side the user most recently clicked. Threaded into TimeEdit as
    // `autoFocusGroup` so the clicked side promotes its first editable group
    // on enter. Cleared when the row exits trim mode.
    let clickedSide: 'start' | 'end' | null = null;
    /** Which digit group the user clicked on in the idle time display —
     *  e.g. they clicked on the `.660` part. Threaded as `autoFocusGroup`
     *  so that group is the one promoted, not a hardcoded default. Null
     *  when the click landed on a separator / the surrounding span. */
    let clickedGroup: 'hh' | 'mm' | 'ss' | 'mmm' | null = null;

    // Same initiating-row gate SegmentRow uses — keeps accordion twins from
    // treating themselves as the live-edit row.
    $: isActiveEdit = !readOnly
        && !!seg.segment_uid
        && $editingSegUid === seg.segment_uid
        && $editMode === 'trim'
        && ($editingMountId === mountId
            || ($editingMountId === null && instanceRole === 'main'));

    $: if (!isActiveEdit && (clickedSide || clickedGroup)) {
        clickedSide = null;
        clickedGroup = null;
    }

    // Live values: when actively editing, follow the trim window. Otherwise
    // the seg's persisted fields.
    $: tw = $trimWindow;
    $: startMs = isActiveEdit && tw ? tw.currentStart : seg.time_start;
    $: endMs   = isActiveEdit && tw ? tw.currentEnd   : seg.time_end;
    $: durMs = endMs - startMs;

    // Bounds — only need real values while actively editing (for the group
    // editability gate inside TimeEdit). Idle rows show plain text, no
    // per-group gate. If the user clicks a time on an idle row we enter
    // trim mode, and by the time TimeEdit re-renders with editing=true
    // the store has tw populated.
    $: startBounds = isActiveEdit && tw
        ? { min: tw.windowStart, max: Math.max(tw.windowStart, tw.currentEnd - EDIT_MIN_DURATION_MS) }
        : null;
    $: endBounds = isActiveEdit && tw
        ? { min: Math.min(tw.windowEnd, tw.currentStart + EDIT_MIN_DURATION_MS), max: tw.windowEnd }
        : null;

    function onStartTimeClick(group: 'hh' | 'mm' | 'ss' | 'mmm' | null): void {
        onTimeClick('start', group);
    }
    function onEndTimeClick(group: 'hh' | 'mm' | 'ss' | 'mmm' | null): void {
        onTimeClick('end', group);
    }

    function onTimeClick(side: 'start' | 'end', group: 'hh' | 'mm' | 'ss' | 'mmm' | null): void {
        if (readOnly) return;
        clickedSide = side;
        clickedGroup = group;
        // If another seg is already in adjust, enterEditWithBuffer is a
        // no-op (existing editMode guard). Same block behavior the user
        // asked for — nothing happens.
        if (get(editMode)) return;
        if (!rowEl) return;
        // Precompute bounds for a sanity-check — if the clamp window is
        // degenerate (no room to move the handle at all), we still enter
        // trim mode so the user can Apply/Cancel as normal, matching the
        // Adjust button behavior.
        const chStr = get(selectedChapter);
        const chapter = seg.chapter || parseInt(chStr);
        const currentChapter = parseInt(chStr);
        const chapterSegs = chapter === currentChapter ? getCurrentChapterSegs() : getChapterSegments(chapter);
        const cfg = get(segConfig);
        const audioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
        const peaksDuration = getWaveformPeaks(audioUrl)?.duration_ms;
        void computeTrimBounds({ ...seg, chapter }, chapterSegs, cfg, peaksDuration);
        enterEditWithBuffer(seg, rowEl, 'trim', validationCategory, mountId);
    }

    function commitStart(newMs: number): void {
        commitSide('start', newMs);
    }
    function commitEnd(newMs: number): void {
        commitSide('end', newMs);
    }

    function commitSide(side: 'start' | 'end', newMs: number): void {
        if (!isActiveEdit) return;
        const canvas = get(editCanvas) as SegCanvas | null;
        updateTrimWindow((w: TrimWindow | null) => {
            if (!w) return w;
            return side === 'start'
                ? { ...w, currentStart: newMs }
                : { ...w, currentEnd: newMs };
        });
        // Mirror onto canvas._trimWindow so the draw path (and drag-handle
        // math) see the same value. Drag handlers follow this same pattern.
        if (canvas?._trimWindow) {
            if (side === 'start') canvas._trimWindow.currentStart = newMs;
            else canvas._trimWindow.currentEnd = newMs;
            drawTrimWaveform(canvas);
        }
    }
</script>

<span class="seg-text-time-range">
    <TimeEdit
        value={startMs}
        bounds={startBounds}
        editing={isActiveEdit && clickedSide === 'start'}
        autoFocusGroup={isActiveEdit && clickedSide === 'start' ? (clickedGroup ?? 'ss') : null}
        onTimeClick={onStartTimeClick}
        onCommit={commitStart}
    />
    <span class="seg-text-sep">&ndash;</span>
    <TimeEdit
        value={endMs}
        bounds={endBounds}
        editing={isActiveEdit && clickedSide === 'end'}
        autoFocusGroup={isActiveEdit && clickedSide === 'end' ? (clickedGroup ?? 'ss') : null}
        onTimeClick={onEndTimeClick}
        onCommit={commitEnd}
    />
    <span class="seg-text-sep">|</span>
    <span class="seg-text-duration" title="{formatDurationMs(durMs)}">{formatDurationMs(durMs)}</span>
</span>
