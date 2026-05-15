/**
 * PreviewPlaybackContext — isolated playback for SavePreview / HistoryPanel.
 *
 * The main-list playback path (`playFromSegment`, `_segRange`,
 * `playingSegmentIndex`) is bound to live segment state — it can't safely
 * play snapshot rows whose `segment_uid`/`index` may not match the current
 * store. SavePreview and HistoryPanel hide the main `<AudioPlayer>` mount
 * while visible, so they also have no audio element to drive.
 *
 * This module provides a self-contained context that owns:
 *   - one per-panel `AudioPort` wrapping the panel's hidden `<audio>`
 *     element, so CBR-vs-VBR transport stays hidden the same way the
 *     main playback path hides it
 *   - one AudioRange instance (single-segment, `policy: 'stop'`)
 *   - reactive `activeSeg` / `playingSeg` stores so SegmentRow can derive
 *     its play-glyph + class:playing state without touching the main-list
 *     `playingSegmentIndex` store
 *   - playhead drawing for the active row's canvas, via the same
 *     `drawSegPlayhead` helper the main list uses
 *   - a one-shot peaks fetch on row registration so snapshot rows render
 *     a waveform even when the main-list cache is cold
 *
 * One context per panel; dispose on panel unmount.
 */

import { get, type Readable, type Writable,writable } from 'svelte/store';

import { AudioPort } from '../../../../lib/playback/audio-port';
import { AudioRange } from '../../../../lib/playback/audio-range';
import { fetchSegmentPeaks } from '../../../../lib/utils/peaks-fetch';
import { reciterVbrChapters, selectedReciter } from '../../stores/chapter';
import { playbackSpeed } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import { drawSegPlayhead } from '../waveform/draw-seg';
import { _findCoveringPeaks } from '../waveform/peaks-cache';
import { indexSegPeaksBulk, redrawPeaksWaveforms } from '../waveform/utils';

export interface PreviewActiveSeg {
    /** Stable per-row id minted by the caller (chapter:index:start:end). */
    uid: string;
}

export interface PreviewPlaybackContext {
    /** Bind the panel's hidden `<audio>` element after mount. */
    attachAudioEl(el: HTMLAudioElement): void;
    /** Register a row's canvas + range for playhead drawing and peak loading.
     *  Idempotent — re-registering with the same uid replaces the prior entry.
     *  When `opId` is supplied (history rows), peaks fetched here are also
     *  persisted server-side so future sessions render the row without
     *  re-computing.
     *
     *  `wfStartMs`/`wfEndMs` describe the canvas's *visual* range, which is
     *  wider than `startMs`/`endMs` for split-leaf history rows (they show
     *  the parent's union peak with the leaf slice highlighted in green
     *  while playback only spans the leaf slice itself). Defaults to the
     *  playback range when omitted — the common case for SavePreview and
     *  non-split history rows. */
    registerRow(uid: string, canvas: HTMLCanvasElement, audioUrl: string, startMs: number, endMs: number, opId?: string, wfStartMs?: number, wfEndMs?: number, chapter?: number): void;
    /** Drop a row entry; if it was the active one, stop playback and clear the playhead. */
    deregisterRow(uid: string): void;
    /** Click-handler for a row's play button. Toggles play/pause for the
     *  same row, switches the active range to a different row otherwise. */
    toggle(uid: string): void;
    /** Tear down the AudioRange + listeners; call from panel onDestroy. */
    dispose(): void;
    /** Which row is the current playback target (set on play, cleared on
     *  boundary stop or dispose). Drives `class:playing` highlight. */
    activeSeg: Readable<PreviewActiveSeg | null>;
    /** Subset of `activeSeg` — non-null only while audio is actively
     *  playing (cleared on `pause`, restored on `play`). Drives the
     *  pause-glyph swap on the row's play button. */
    playingSeg: Readable<PreviewActiveSeg | null>;
}

interface RowEntry {
    canvas: HTMLCanvasElement;
    audioUrl: string;
    /** Playback range — `AudioRange` boundaries (audio plays only this slice). */
    startMs: number;
    endMs: number;
    /** Visual range — canvas width and `drawSegPlayhead` arguments. Equal to
     *  `startMs`/`endMs` for non-split rows; wider for split-leaf history
     *  rows showing the parent's union peak. */
    wfStartMs: number;
    wfEndMs: number;
    chapter?: number;
    opId?: string;
}

export function createPreviewPlaybackContext(opts: { persistPeaks?: boolean } = {}): PreviewPlaybackContext {
    const persistPeaks = opts.persistPeaks ?? true;
    const rows = new Map<string, RowEntry>();
    const _activeSeg: Writable<PreviewActiveSeg | null> = writable(null);
    const _playingSeg: Writable<PreviewActiveSeg | null> = writable(null);

    // Per-panel port — isolated from the segments-tab `segPort`. Each panel
    // mounts its own hidden `<audio>`, attached on `attachAudioEl`. The
    // port owns CBR-vs-VBR transport for whichever row is being played.
    const port = new AudioPort();
    let range: AudioRange | null = null;
    let curUid: string | null = null;
    let curRow: RowEntry | null = null;
    let unsubPlay: (() => void) | null = null;
    let unsubPause: (() => void) | null = null;
    /** Dedup peak fetches per (url, start, end) — registering the same
     *  row twice (e.g. parent re-render) shouldn't trigger duplicate
     *  network calls. */
    const fetched = new Set<string>();

    function _onTick(timeMs: number): void {
        if (!curRow) return;
        // Use the visual range for the canvas rebuild + playhead
        // positioning. For split leaves wfStart/wfEnd is the parent's
        // union range; the green child slice (drawn by the split overlay)
        // sits inside it and the playhead sweeps only across that slice
        // because AudioRange stops audio at the playback range.
        drawSegPlayhead(
            curRow.canvas as SegCanvas,
            curRow.wfStartMs,
            curRow.wfEndMs,
            timeMs,
            curRow.audioUrl,
        );
    }

    function _onBoundary(): void {
        // Boundary fires only for `policy: 'stop'` end-of-range. Clear the
        // playhead by repainting the cached waveform with a currentTimeMs
        // outside the range — drawSegPlayhead returns early after the
        // putImageData restore, leaving the waveform clean.
        _clearPlayheadOnCurrent();
        // Dispose and null the range here so that toggle() on the same row
        // detects "no live range" rather than finding the already-stopped
        // instance, which would require an extra dispose() call and leave
        // the gain node in an ambiguous state.
        if (range) {
            range.dispose();
            range = null;
        }
        curUid = null;
        curRow = null;
        _activeSeg.set(null);
        _playingSeg.set(null);
    }

    function _clearPlayheadOnCurrent(): void {
        if (!curRow) return;
        const canvas = curRow.canvas as SegCanvas;
        canvas._wfCache = null;
        // Pass the visual range; `drawSegPlayhead` rebuilds the cache
        // with overlays baked in (split green / trim red+green / merge
        // green), then the currentTime-outside-range early-return leaves
        // the canvas overlay-intact and cursor-free.
        drawSegPlayhead(
            canvas,
            curRow.wfStartMs,
            curRow.wfEndMs,
            curRow.wfStartMs - 1,
            curRow.audioUrl,
        );
    }

    function _onAudioPlay(): void {
        if (curUid) _playingSeg.set({ uid: curUid });
    }

    function _onAudioPause(): void {
        _playingSeg.set(null);
    }

    function attachAudioEl(el: HTMLAudioElement): void {
        if (port.element === el) return;
        // Detach prior subscriptions before rebinding.
        unsubPlay?.(); unsubPause?.();
        port.attachElement(el);
        unsubPlay = port.onPlay(_onAudioPlay);
        unsubPause = port.onPause(_onAudioPause);
    }

    async function _ensurePeaks(
        audioUrl: string,
        startMs: number,
        endMs: number,
        opId?: string,
    ): Promise<void> {
        if (!audioUrl || endMs <= startMs) return;
        if (_findCoveringPeaks(audioUrl, startMs, endMs)) return;
        const key = `${audioUrl}:${startMs}:${endMs}`;
        if (fetched.has(key)) return;
        fetched.add(key);
        const reciter = get(selectedReciter);
        if (!reciter) return;
        // Pad the fetch window so the playhead has waveform around the
        // boundaries. Generous on both sides — segment_peaks is disk-cached
        // server-side, so over-fetching is cheap on subsequent loads.
        const pad = 200;
        const fetchStart = Math.max(0, startMs - pad);
        const fetchEnd = endMs + pad;
        const peaks = await fetchSegmentPeaks(reciter, audioUrl, fetchStart, fetchEnd);
        if (!peaks?.peaks?.length) return;
        // Reuse the bulk indexer so the entry lands in the same covering
        // cache the IntersectionObserver pipeline reads from.
        indexSegPeaksBulk({ [`${audioUrl}:${fetchStart}:${fetchEnd}`]: peaks });
        redrawPeaksWaveforms();

        // History rows (opId set) — persist so future sessions hydrate
        // these peaks at panel open. Fire-and-forget; failures are silent
        // (next play computes again).
        if (persistPeaks && opId) {
            void fetch(`/api/seg/history-peaks/${reciter}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    records: [{
                        op_id: opId,
                        url: audioUrl,
                        start_ms: peaks.start_ms ?? fetchStart,
                        end_ms: peaks.end_ms ?? fetchEnd,
                        peaks: peaks.peaks,
                        duration_ms: peaks.duration_ms,
                    }],
                }),
            }).catch(() => {});
        }
    }

    function registerRow(
        uid: string,
        canvas: HTMLCanvasElement,
        audioUrl: string,
        startMs: number,
        endMs: number,
        opId?: string,
        wfStartMs?: number,
        wfEndMs?: number,
        chapter?: number,
    ): void {
        // No fetch on register. Persisted peaks (if any) were hydrated at
        // reciter load; rows without persisted peaks render flat until the
        // user clicks play. `toggle()` triggers the on-demand compute path.
        rows.set(uid, {
            canvas,
            audioUrl,
            startMs,
            endMs,
            wfStartMs: wfStartMs ?? startMs,
            wfEndMs: wfEndMs ?? endMs,
            chapter,
            opId,
        });
    }

    function deregisterRow(uid: string): void {
        rows.delete(uid);
        if (curUid === uid) {
            _stop();
        }
    }

    function _stop(): void {
        if (range) {
            range.dispose();
            range = null;
        }
        _clearPlayheadOnCurrent();
        curUid = null;
        curRow = null;
        _activeSeg.set(null);
        _playingSeg.set(null);
    }

    function toggle(uid: string): void {
        if (!port.element) return;
        const row = rows.get(uid);
        if (!row) return;

        // Same row, currently playing → pause (range stays alive, ready to resume)
        if (curUid === uid && range && !port.paused) {
            port.pause();
            return;
        }
        // Same row, paused (range still alive) → resume
        if (curUid === uid && range && port.paused) {
            port.play();
            return;
        }

        // Different row, or no live range → tear down + rebuild.
        if (range) {
            range.dispose();
            range = null;
        }
        _clearPlayheadOnCurrent();

        curUid = uid;
        curRow = row;
        _activeSeg.set({ uid });

        // On-demand peaks compute, against the *visual* range so the
        // wider canvas (split leaves) gets full coverage. Cache hits
        // (persisted-and-hydrated, or a prior play this session)
        // short-circuit inside `_ensurePeaks`. Misses fetch via Range
        // and — when this is a History row (opId set) — also persist so
        // the next session hydrates without a round-trip.
        void _ensurePeaks(row.audioUrl, row.wfStartMs, row.wfEndMs, row.opId);

        // Bind the row's logical source to the per-panel port. CBR rows hit
        // the chapter-URL fast path; VBR rows route through the segment-clip
        // endpoint. Use the row chapter instead of the active chapter so
        // cross-chapter history/save-preview rows keep the same VBR/CBR
        // routing as main row playback.
        const reciter = get(selectedReciter);
        const isVbr = row.chapter != null
            && (get(reciterVbrChapters)?.has(row.chapter) ?? false);
        port.setSource({
            audioUrl: row.audioUrl,
            cbrSrc: row.audioUrl,
            reciter: reciter || null,
            vbr: isVbr,
        });

        // File-absolute spec — port owns transport.
        range = new AudioRange({
            port,
            range: { startMs: row.startMs, endMs: row.endMs },
            policy: { kind: 'stop' },
            onTick: _onTick,
            onBoundary: _onBoundary,
            playbackRate: () => get(playbackSpeed),
        });
        range.start();
    }

    function dispose(): void {
        if (range) {
            range.dispose();
            range = null;
        }
        unsubPlay?.(); unsubPause?.();
        unsubPlay = null;
        unsubPause = null;
        port.dispose();
        rows.clear();
        fetched.clear();
        curUid = null;
        curRow = null;
        _activeSeg.set(null);
        _playingSeg.set(null);
    }

    return {
        attachAudioEl,
        registerRow,
        deregisterRow,
        toggle,
        dispose,
        activeSeg: { subscribe: _activeSeg.subscribe },
        playingSeg: { subscribe: _playingSeg.subscribe },
    };
}
