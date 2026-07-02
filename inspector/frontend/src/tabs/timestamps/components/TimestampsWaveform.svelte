<script lang="ts">
    /**
     * TimestampsWaveform — waveform + overlays for the Timestamps tab.
     *
     * Peaks come from the backend ffmpeg + HTTP-Range endpoint
     * (`/api/seg/segment-peaks/<reciter>`) — no full-file decode in the browser.
     *
     * Overlays (boundary markers, hover fills, playhead) are drawn on top of
     * an immutable ImageData snapshot of the pristine peaks base, mirroring
     * `tabs/segments/utils/waveform/draw-seg.ts`.
     *
     * Boundary markers respect the active view/granularity: word lines are
     * always drawn; letter and phoneme lines are gated on the same toggles
     * that drive UnifiedDisplay. Precedence prevents double-draws: word > letter > phoneme.
     *
     * Hover behavior:
     *   - Pointer on the waveform: translucent word-region band, plus letter
     *     and phoneme bands layered on top when the respective tiers are active.
     *   - Pointer on a UnifiedDisplay block (via `tsHoveredElement` store):
     *     single-tier matching-color band. Waveform-origin hover wins.
     *
     * Click: always snaps to the enclosing word's start time.
     */

    import { onMount, tick } from 'svelte';
    import { get } from 'svelte/store';

    import WaveformCanvas from '../../../lib/components/WaveformCanvas.svelte';
    import { signalDashSeekIntent } from '../../../lib/playback/dash-buffering';
    import { dashPort } from '../../../lib/playback/dash-port';
    import { ensureDashCovering } from '../../../lib/playback/dash-covering';
    import { recitationConfigStore } from '../../../lib/recitation-animation/recitation-settings';
    import { themeStore, THEME_CHANGE_EVENT } from '../../../lib/stores/theme.svelte';
    import type { AudioPeaks, PeakBucket, SegmentPeaks } from '../../../lib/types/peaks-transport';
    import type { TsVerseData } from '../../../lib/types/ts-client';
    import { themeColor } from '../../../lib/utils/canvas-theme';
    import { triadForTheme } from '../../../lib/utils/highlight-model';
    import {
        PREVIEW_PLAYHEAD_COLOR,
        WAVEFORM_BG_COLOR,
    } from '../../../lib/utils/constants';
    import { ensureChapterPeaks, ensureSegmentPeaks, pickChapterPeaks } from '../../../lib/utils/peaks-fetch';
    import { drawWaveformPeaks } from '../../../lib/utils/waveform-draw';
    import {
        granularity,
        showLetters,
        showPhonemes,
        TS_GRANULARITIES,
        TS_VIEW_MODES,
        tsHoveredElement,
        tsWaveformHoverTime,
        viewMode,
    } from '../stores/display';
    import { loopTarget } from '../stores/playback';
    import { focusWaslGroup, loadedVerse } from '../stores/verse';
    import { tsZoom, tsZoomAnimating } from '../stores/zoom';
    import { TS_PAN_HALF_CANVAS_VIEWS_PER_SEC } from '../utils/constants';
    import { findWordAt } from '../utils/loop-target';
    import { applyTsWheelZoom, isTsZoomAnimating, panTsViewBy } from '../utils/zoom';

    // ---- Local layout constants ----
    const TS_WAVEFORM_DEFAULT_WIDTH = 1200;
    const TS_WAVEFORM_HEIGHT = 200;

    // Pixel tolerance for "same boundary" deduplication across tiers.
    const BOUNDARY_DEDUP_EPS = 1;

    // Hover fill opacity per tier (stacked on the waveform, single-tier from blocks).
    const HOVER_ALPHA_WORD = 0.15;
    const HOVER_ALPHA_LETTER = 0.20;
    const HOVER_ALPHA_PHONEME = 0.25;

    // Current-position (playback) fills — dimmer than hover so hover stays louder.
    const PLAYING_ALPHA_WORD = 0.10;
    const PLAYING_ALPHA_LETTER = 0.15;
    const PLAYING_ALPHA_PHONEME = 0.18;

    // Silence-region peak dim: translucent bg fill fades the peaks toward
    // background without fully erasing them. Applied before any other overlays
    // so boundary markers / playhead / hover fills stay crisp on top.
    const SILENCE_DIM_ALPHA = 0.55;

    // Boundary stroke widths — subtle visual hierarchy.
    const WORD_LINE_WIDTH = 2;
    const LETTER_LINE_WIDTH = 1.5;
    const PHONEME_LINE_WIDTH = 1;

    // Minimum avg pixel spacing between boundaries before a tier's lines are
    // suppressed. Prevents the waveform becoming a wall of stripes when zoomed
    // out; lines reappear automatically as the user zooms in.
    const MIN_PHONEME_LINE_SPACING_PX = 12;
    const MIN_LETTER_LINE_SPACING_PX  = 8;

    // ---- Sizing ----

    let containerEl: HTMLDivElement;
    let waveformRef: WaveformCanvas;
    let canvasWidth = TS_WAVEFORM_DEFAULT_WIDTH;
    const canvasHeight = TS_WAVEFORM_HEIGHT;

    // ---- Peaks ----

    // PeakBucket[] from the ffmpeg fallback; Int8Array from the baked 10bps
    // chapter-peaks fast path (pre-sliced to the verse window).
    let peaks: PeakBucket[] | Int8Array | null = null;
    let fetchGen = 0;
    // Chapter the current `peaks`/`_baseImageData` represent. On a cross-chapter
    // jump we clear before the (possibly cold) fetch so the draw blank-fills
    // instead of compositing the new verse's overlays onto the previous
    // chapter's waveform. Same-chapter slices are instant, so we never clear
    // there (avoids a flash on every in-chapter advance).
    let _loadedPeaksChapter = 0;

    // Bucket-snap metadata for the baked-peaks fast path. `_sliceVerseLocal`
    // snaps the int8 slice to bucket boundaries, so the array covers a span
    // slightly WIDER than the exact verse window. These describe that slice so
    // the drawer's density matches the array (peaks line up with overlays):
    //   _peaksSpanMs   — the slice's true covered duration (drawer totalDurationMs)
    //   _peaksOriginMs — offset (≥0) from the slice's true start to the exact
    //                    window start; added to window-relative sub-range ms.
    // null for the ffmpeg fallback (PeakBucket[] is already verse-exact).
    let _peaksSpanMs: number | null = null;
    let _peaksOriginMs = 0;

    // ---- Snapshot of peaks-only base ----
    let _baseImageData: ImageData | null = null;
    let _baseCacheKey: string | null = null;

    // Eager base invalidation the moment a zoom tween starts. Without this,
    // an audio-tick rAF queued earlier in the same frame can reach
    // `drawOverlays` BEFORE `onZoomChange`'s two-tick capture-skip logic
    // has run — and it would composite new overlays onto the pre-sweep
    // cached base, leaving a stale playhead stroke baked into what the
    // NEXT `_captureBase` (at sweep end) eventually snapshots. Flipping
    // the flag store to `true` here clears the cache first thing.
    $: if ($tsZoomAnimating) { _baseImageData = null; _baseCacheKey = null; }

    // ---- Active-tier flags (drive marker + hover behavior) ----
    $: lettersActive =
        ($viewMode === TS_VIEW_MODES.ANALYSIS && $showLetters)
        || ($viewMode === TS_VIEW_MODES.ANIMATION && $granularity === TS_GRANULARITIES.CHARACTERS);
    $: phonemesActive = $viewMode === TS_VIEW_MODES.ANALYSIS && $showPhonemes;
    // Waveform overlay colors derive from the SHARED recitation accent so the
    // word/letter/phoneme bands + boundary strokes match the analysis display
    // and the now-reciting animation (one analogous family).
    // Theme-conditional band (mirrors the analysis cells): light uses a darker
    // legible band so the markers read on the light waveform. `curTheme` is a
    // local mirror of the runes theme store, updated by the `themechange`
    // listener below (a legacy `$:` can't reliably track the store field).
    let curTheme = themeStore.current;
    $: triad = triadForTheme($recitationConfigStore.highlightColor, curTheme);
    $: wordColor = triad.word;
    $: letterColor = triad.letter;
    $: phonemeColor = triad.phoneme;

    // Redraw when toggles / hover store / loop store change so overlays update
    // even while paused. Subscriptions on `$tsHoveredElement` and `$loopTarget`
    // trigger block-originated hover renders + loop band updates respectively.
    // `themeStore.current` is listed so a light/dark flip re-runs the redraw;
    // because a legacy `$:` block may not reliably track a runes-store field,
    // the onMount `themechange` listener below is the guaranteed repaint path
    // (it also invalidates the cached base snapshot so peaks repaint, not just
    // overlays).
    $: ($tsHoveredElement, $loopTarget, lettersActive, phonemesActive, wordColor, themeStore.current, drawOverlays());

    // ---- Zoom: pass sub-range to WaveformCanvas + recapture base on change ----

    /** Cached for fast read inside `tToX` / `_pointerTime` (avoids repeated
     *  `get(tsZoom)` per draw call). Updated by the reactive subscription. */
    let _zoom: { viewStart: number; viewEnd: number } | null = null;
    $: _zoom = $tsZoom;

    // The displayed window: the whole cross-verse waṣl span when the focus verse
    // is in a group (so the waveform shows the continuous recitation as one), else
    // the focus verse. Drives the peaks fetch + the coordinate base; the merged
    // group's cells 0-anchor to the group start, matching `_dispOffsetSec`.
    $: _dispOffsetSec = $focusWaslGroup ? $focusWaslGroup.span[0] / 1000 : ($loadedVerse?.tsSegOffset ?? 0);
    $: _dispEndSec = $focusWaslGroup ? $focusWaslGroup.span[1] / 1000 : ($loadedVerse?.tsSegEnd ?? 0);

    // Sub-range props forwarded to WaveformCanvas, resolved via `_drawRange` so
    // the bucket-snapped baked slice and the verse-exact ffmpeg slice both map
    // to the exact-window-relative overlay coords. For the verse-exact path
    // un-zoomed, all three are `undefined` (drawer renders the full array);
    // for the baked slice they're always set (window shifted into the slice).
    // `_peaksSpanMs`/`_peaksOriginMs` are referenced so the reactive re-resolves
    // when the slice metadata flips (baked ↔ ffmpeg fallback).
    $: _wcRange = _drawRange(
        _zoom,
        ($loadedVerse || $focusWaslGroup) ? (_dispEndSec - _dispOffsetSec) * 1000 : 0,
        _peaksSpanMs,
        _peaksOriginMs,
    );
    $: wcStartMs = _wcRange.startMs;
    $: wcEndMs = _wcRange.endMs;
    $: wcTotalDurationMs = _wcRange.totalDurationMs;

    // When `tsZoom` changes, the base peak canvas re-renders via WaveformCanvas's
    // reactive on (startMs, endMs, totalDurationMs). We drop the cached
    // ImageData snapshot so the overlay system doesn't composite onto a stale
    // base, and recapture AFTER WaveformCanvas redraws. Two `tick()`s: one for
    // Svelte to flow new props down, one for WaveformCanvas's reactive redraw.
    //
    // During a loop-target sweep (`isTsZoomAnimating()`), `_zoom` mutates ~60
    // times per second. Capturing a fresh ImageData snapshot each frame means
    // allocating ~960 KB × ~54 frames for a long sweep — a noticeable GC
    // spike. While animating, skip the capture: the overlay path falls
    // through to the WaveformCanvas reactive redraw (peaks re-render every
    // frame anyway), and we recapture ONCE when the tween finishes.
    let _zoomFetchGen = 0;
    $: void onZoomChange(_zoom);
    async function onZoomChange(_z: { viewStart: number; viewEnd: number } | null): Promise<void> {
        if (!waveformRef) return;
        const gen = ++_zoomFetchGen;
        _baseImageData = null;
        _baseCacheKey = null;
        await tick();
        await tick();
        if (gen !== _zoomFetchGen) return; // stale — newer zoom landed
        if (isTsZoomAnimating()) {
            // Mid-sweep: no base capture; WaveformCanvas already redrew
            // peaks this frame, overlays paint on top via drawOverlays.
            drawOverlays();
            return;
        }
        const k = `zoom:${_z?.viewStart ?? 'full'}:${_z?.viewEnd ?? 'full'}`;
        _captureBase(k);
        drawOverlays();
    }

    // ---- Hover state (waveform-origin) ----
    /** Slice-relative seconds. null when pointer is off the waveform. */
    let _waveformHoverTime: number | null = null;

    // ---- Peaks fetch ----

    // Read the reciter from `loadedVerse.data.reciter`, NOT from the
    // `selectedReciter` store. `ingestVerseData` in TimestampsTab updates
    // `loadedVerse` before `selectedReciter`, and Svelte fires this
    // reactive on the first store write — so reading from the store sees
    // the stale empty-string and the early-return below silently kills
    // the peaks fetch on first paint. The reciter is already part of the
    // reactive's input via loadedVerse.data, so use that directly.
    $: reactToVerse(
        $loadedVerse?.data.audio_url ?? null,
        $loadedVerse?.data.reciter ?? '',
        $loadedVerse?.data.chapter ?? 0,
        _dispOffsetSec,
        _dispEndSec,
    );

    function _clearPeaks(): void {
        peaks = null;
        _peaksSpanMs = null;
        _peaksOriginMs = 0;
        _baseImageData = null;
        _baseCacheKey = null;
        _loadedPeaksChapter = 0;
    }

    /** Slice a chapter int8 [min,max] envelope down to a VERSE-LOCAL Int8Array
     *  for the chapter-absolute window [startMs,endMs]. floor(start)/ceil(end)
     *  bucket convention (matches the drawer) so the verse fully covers its
     *  peaks; the slice runs ≤1 bucket (≤100ms at 10bps) wide of the exact
     *  window per side.
     *
     *  Because of that snap, the slice's TRUE covered span is wider than the
     *  exact window. We return that span (`spanMs`) and the offset from the
     *  slice's true start to the exact window start (`originMs` ≥ 0). Draw
     *  sites feed `spanMs` as the drawer's `totalDurationMs` and add `originMs`
     *  to the (window-relative) sub-range so the drawer's density matches the
     *  array — the painted peaks then line up with the boundary/playhead
     *  overlays instead of drifting by up to one bucket. */
    function _sliceVerseLocal(
        chapterPeaks: Int8Array,
        durationMs: number,
        startMs: number,
        endMs: number,
    ): { peaks: Int8Array; spanMs: number; originMs: number } | null {
        const pairs = chapterPeaks.length >> 1;
        if (pairs <= 0 || durationMs <= 0) return null;
        const pairsPerMs = pairs / durationMs;
        const startPair = Math.max(0, Math.floor(startMs * pairsPerMs));
        const endPair = Math.min(pairs, Math.ceil(endMs * pairsPerMs));
        if (endPair <= startPair) return null;
        const trueStartMs = startPair / pairsPerMs;
        const trueEndMs = endPair / pairsPerMs;
        return {
            peaks: chapterPeaks.slice(startPair * 2, endPair * 2),
            spanMs: trueEndMs - trueStartMs,
            originMs: startMs - trueStartMs,
        };
    }

    /** Resolve the drawer sub-range for the current peaks + zoom. Returns the
     *  `{ startMs, endMs, totalDurationMs }` to feed `drawWaveformPeaks` so the
     *  painted peaks align with the (exact-window-relative) overlays.
     *
     *  `exactDurationMs` is the exact verse window; the visible window in OVERLAY
     *  coords (ms from the window start) is `[0, exactDurationMs]` un-zoomed or
     *  `[viewStart, viewEnd]` zoomed.
     *
     *  For the bucket-snapped baked slice (`spanMs` set) the array covers a span
     *  WIDER than the exact window, so we declare that true span as
     *  `totalDurationMs` and shift the window by `originMs` into the array. For
     *  the verse-exact ffmpeg path (`spanMs == null`) the window maps 1:1, with
     *  an un-zoomed full slice signalled by `undefined` sub-range (drawer renders
     *  the whole array linearly). */
    function _drawRange(
        zoom: { viewStart: number; viewEnd: number } | null,
        exactDurationMs: number,
        spanMs: number | null,
        originMs: number,
    ): { startMs: number | undefined; endMs: number | undefined; totalDurationMs: number | undefined } {
        if (spanMs != null) {
            const winStartMs = zoom ? zoom.viewStart * 1000 : 0;
            const winEndMs = zoom ? zoom.viewEnd * 1000 : exactDurationMs;
            return {
                startMs: Math.round(winStartMs + originMs),
                endMs: Math.round(winEndMs + originMs),
                totalDurationMs: Math.round(spanMs),
            };
        }
        // Verse-exact peaks: existing behaviour (undefined sub-range when unzoomed).
        return {
            startMs: zoom ? Math.round(zoom.viewStart * 1000) : undefined,
            endMs: zoom ? Math.round(zoom.viewEnd * 1000) : undefined,
            totalDurationMs: zoom ? Math.round(exactDurationMs) : undefined,
        };
    }

    async function reactToVerse(
        url: string | null,
        reciter: string,
        chapter: number,
        startSec: number,
        endSec: number,
    ): Promise<void> {
        if (!reciter) { _clearPeaks(); return; }
        const startMs = Math.max(0, Math.round(startSec * 1000));
        const endMs = Math.round(endSec * 1000);
        if (endMs <= startMs) { _clearPeaks(); return; }
        // `url` may be null/'' for a non-templatable source — the baked
        // chapter-peaks fast path needs only reciter+chapter, so don't bail here.
        // The ffmpeg fallback (fetchSegmentPeaks) no-ops on empty url, clearing
        // cleanly.
        const safeUrl = url ?? '';
        const key = `${safeUrl}:${startMs}:${endMs}`;
        const gen = ++fetchGen;

        // Cross-chapter jump: drop the stale peak before the (possibly cold)
        // fetch so the draw blank-fills rather than painting the new verse's
        // overlays on the previous chapter's waveform. Same-chapter slices are
        // instant and keep their base — no flash on in-chapter advance.
        if (chapter && chapter !== _loadedPeaksChapter) _clearPeaks();

        // PLACEHOLDER: baked 10bps chapter peaks (server-cached, sliced
        // client-side). One ~6KB GET per chapter then a ~2µs slice per verse —
        // paints instantly, but at 10bps int8 it's coarse on this full-width
        // hero canvas, so it's only a placeholder: we always upgrade to the HD
        // ffmpeg peaks below. When no baked peaks exist the HD path is primary.
        let drewPlaceholder = false;
        if (chapter) {
            let chMap: Record<string, AudioPeaks> | null = null;
            try {
                chMap = await ensureChapterPeaks(reciter, chapter);
            } catch {
                chMap = null;
            }
            if (gen !== fetchGen) return; // a newer verse landed mid-fetch
            const chEntry = chMap ? pickChapterPeaks(chMap, safeUrl) : null;
            if (chEntry && chEntry.peaks instanceof Int8Array && chEntry.duration_ms > 0) {
                const sliced = _sliceVerseLocal(chEntry.peaks, chEntry.duration_ms, startMs, endMs);
                if (sliced && sliced.peaks.length) {
                    peaks = sliced.peaks;
                    _peaksSpanMs = sliced.spanMs;
                    _peaksOriginMs = sliced.originMs;
                    _loadedPeaksChapter = chapter;
                    _baseImageData = null;
                    _baseCacheKey = null;
                    await tick();
                    if (gen !== fetchGen) return;
                    _captureBase(key);
                    drawOverlays();
                    drewPlaceholder = true;
                    // fall through to the HD upgrade
                }
            }
        }

        // HD UPGRADE / PRIMARY: per-verse ffmpeg peaks (verse-exact float
        // PeakBucket[] @30bps — 3× the temporal points + continuous amplitude
        // vs the 10bps int8 placeholder). Shared module cache (ensureSegmentPeaks)
        // so a look-ahead prewarm of this same window makes it a cache hit
        // instead of a cold ffmpeg/CDN fetch. When a placeholder was drawn this
        // REPLACES it; a fetch error/empty result keeps the placeholder.
        let entry: SegmentPeaks | null;
        try {
            entry = await ensureSegmentPeaks(reciter, safeUrl, startMs, endMs, chapter || undefined);
        } catch (e) {
            if (!drewPlaceholder) console.error('Waveform peaks fetch failed:', e);
            return;
        }
        if (gen !== fetchGen) return;
        if (!entry || !entry.peaks?.length) { if (!drewPlaceholder) _clearPeaks(); return; }

        peaks = entry.peaks;
        // ffmpeg peaks are verse-exact (no bucket-snap) — use the exact window.
        _peaksSpanMs = null;
        _peaksOriginMs = 0;
        _loadedPeaksChapter = chapter;

        _baseImageData = null;
        _baseCacheKey = null;
        await tick();
        if (gen !== fetchGen) return;
        _captureBase(key);
        drawOverlays();
    }

    function _captureBase(key: string): void {
        if (!waveformRef) return;
        const canvas = waveformRef.getCanvas();
        if (!canvas || !canvas.width || !canvas.height) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        // Force a clean peaks-only canvas BEFORE snapshotting. We can't
        // trust that WaveformCanvas's reactive redraw fired on this flush:
        // `wcStartMs` / `wcEndMs` are `Math.round(_zoom * 1000)`, and the
        // final tween frame often rounds to the same integer as the
        // second-to-last frame — Svelte sees no prop change, skips the
        // child redraw, and the canvas still holds the PREVIOUS frame's
        // overlays + playhead. Capturing that as the base would bake a
        // stale playhead into every subsequent `putImageData` call
        // (user-visible as a fixed ghost cursor inside the loop word).
        if (peaks) {
            const win = dispWindow();
            const exactMs = win ? (win.end - win.offset) * 1000 : 0;
            const range = _drawRange(_zoom, exactMs, _peaksSpanMs, _peaksOriginMs);
            drawWaveformPeaks(ctx, peaks, {
                width: canvas.width,
                height: canvas.height,
                startMs: range.startMs,
                endMs: range.endMs,
                totalDurationMs: range.totalDurationMs,
            });
        }
        _baseImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        _baseCacheKey = key;
    }

    // ---- Overlays ----

    /** Imperative read of the displayed window (the whole waṣl group when the
     *  focus is in one, else the focus verse). Matches the reactive
     *  `_dispOffsetSec`/`_dispEndSec` + the merged cells, so peaks / playhead /
     *  bands / click all share one group-anchored coordinate base. */
    function dispWindow(): { offset: number; end: number; data: TsVerseData } | null {
        const fg = get(focusWaslGroup);
        if (fg) return { offset: fg.span[0] / 1000, end: fg.span[1] / 1000, data: fg.data };
        const lv = get(loadedVerse);
        return lv ? { offset: lv.tsSegOffset, end: lv.tsSegEnd, data: lv.data } : null;
    }

    /**
     * Draw overlays. Called per-frame from the parent animation loop and on
     * reactive store changes. Restores the immutable peaks base, then paints
     * hover fills → boundary markers → playhead.
     */
    export function drawOverlays(): void {
        if (!waveformRef) return;
        const canvas = waveformRef.getCanvas();
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const width = canvas.width;
        const height = canvas.height;
        const win = dispWindow();
        if (!win) return;

        const segOffset = win.offset;
        const segEnd = win.end;
        const duration = segEnd - segOffset || 1;
        const words = win.data.words;
        const intervals = win.data.intervals;

        // 1. Restore pristine base.
        //    Fast path: use the cached ImageData snapshot when it matches the
        //    current canvas size. Fallback (mid-sweep, or before first
        //    capture): redraw peaks inline via the pure helper. Pure black
        //    fill only when peaks haven't loaded yet.
        //
        //    During a zoom tween (`isTsZoomAnimating()`), always take the
        //    inline-redraw path — never `putImageData`. Reason: an
        //    audio-tick rAF that fires BEFORE the zoom-step rAF on the
        //    first sweep frame would otherwise paint new overlays on top
        //    of the last-captured base (which still reflects the pre-sweep
        //    zoom), leaving ghosted playhead / double-intensity overlay
        //    bands. Forcing the fallback path guarantees each mid-sweep
        //    frame starts from a full canvas clear.
        const animating = isTsZoomAnimating();
        if (!animating && _baseImageData && _baseImageData.width === width && _baseImageData.height === height) {
            ctx.putImageData(_baseImageData, 0, 0);
        } else if (peaks) {
            const range = _drawRange(_zoom, duration * 1000, _peaksSpanMs, _peaksOriginMs);
            drawWaveformPeaks(ctx, peaks, {
                width,
                height: height,
                startMs: range.startMs,
                endMs: range.endMs,
                totalDurationMs: range.totalDurationMs,
            });
        } else {
            ctx.fillStyle = themeColor('--wf-bg', '#0f0f23');
            ctx.fillRect(0, 0, width, height);
        }

        // Zoom-aware time → pixel. When `_zoom` is null, maps the full slice to
        // canvas width (existing behavior). When zoomed, maps only [viewStart,
        // viewEnd] — boundaries/fills/playhead outside the view naturally land
        // past [0, width] and get clipped by the canvas.
        const tToX = _zoom
            ? (t: number): number => ((t - _zoom!.viewStart) / (_zoom!.viewEnd - _zoom!.viewStart)) * width
            : (t: number): number => (t / duration) * width;
        const audioPaused = !dashPort.element || dashPort.paused;

        // 1.5. Dim silence-region peaks. MFA phoneme tiling is vocal-only in
        //      this dataset, so silence is inferred from inter-word gaps plus
        //      the head/tail margins of the slice. Fading the peaks toward bg
        //      gives the classic DAW "quiet zone" look without a rectangular wash.
        const dimSilence = (start: number, end: number): void => {
            if (end <= start) return;
            _fillBand(ctx, tToX(start), tToX(end), height, themeColor('--wf-bg', WAVEFORM_BG_COLOR), SILENCE_DIM_ALPHA);
        };
        if (words.length > 0) {
            const first = words[0];
            const last = words[words.length - 1];
            if (first) dimSilence(0, first.start);                 // leading
            for (let i = 0; i < words.length - 1; i++) {
                const cur = words[i];
                const next = words[i + 1];
                if (cur && next) dimSilence(cur.end, next.start);  // inter-word
            }
            if (last) dimSilence(last.end, duration);              // trailing
        } else {
            dimSilence(0, duration); // no words → entire slice is "silence"
        }
        // Also fade any explicitly-silent phoneme intervals (when the backend
        // does emit sil/sp) — idempotent with the word-gap pass above.
        for (const iv of intervals) {
            const ph = iv.phone;
            if (!ph || ph === 'sil' || ph === 'sp') dimSilence(iv.start, iv.end);
        }

        // 1.75. Permanent loop-region fill — drawn below hover so hover still
        //       overlays on top, but above silence-dim so the loop band reads
        //       through even inside dimmed regions.
        const loop = get(loopTarget);
        if (loop) {
            let loopColor: string;
            let loopAlpha: number;
            if (loop.kind === 'word') {
                loopColor = wordColor;
                loopAlpha = PLAYING_ALPHA_WORD;
            } else if (loop.kind === 'letter') {
                loopColor = letterColor;
                loopAlpha = PLAYING_ALPHA_LETTER;
            } else {
                loopColor = phonemeColor;
                loopAlpha = PLAYING_ALPHA_PHONEME;
            }
            _fillBand(ctx, tToX(loop.startSec), tToX(loop.endSec), height, loopColor, loopAlpha);
        }

        // 2a. Playing-current fills — always show the tiers currently active,
        //     based on dashPort.currentTimeMs, in both Analysis and Animation modes.
        //     Drawn below hover so hover stays visually dominant.
        if (dashPort.element) {
            const t = dashPort.currentTimeMs() / 1000 - segOffset;
            const curW = findWordAt(t, words, false);
            if (curW) _fillBand(ctx, tToX(curW.start), tToX(curW.end), height, wordColor, PLAYING_ALPHA_WORD);
            if (lettersActive && curW) {
                for (const l of curW.letters) {
                    if (l.start == null || l.end == null) continue;
                    if (t >= l.start && t < l.end) {
                        _fillBand(ctx, tToX(l.start), tToX(l.end), height, letterColor, PLAYING_ALPHA_LETTER);
                        break;
                    }
                }
            }
            if (phonemesActive) {
                for (const iv of intervals) {
                    if (t >= iv.start && t < iv.end) {
                        _fillBand(ctx, tToX(iv.start), tToX(iv.end), height, phonemeColor, PLAYING_ALPHA_PHONEME);
                        break;
                    }
                }
            }
        }

        // 2b. Hover fills — waveform-origin (stacked) wins over block-origin (single tier).
        //     Block-origin hover is suppressed while audio is playing — it would
        //     compete with the playing-current fills and distract the user.
        if (_waveformHoverTime != null) {
            const t = _waveformHoverTime;
            // Strict lookup: silence/inter-word gaps produce no band.
            const w = findWordAt(t, words, false);
            if (w) _fillBand(ctx, tToX(w.start), tToX(w.end), height, wordColor, HOVER_ALPHA_WORD);
            if (lettersActive && w) {
                for (const l of w.letters) {
                    if (l.start == null || l.end == null) continue;
                    if (t >= l.start && t < l.end) {
                        _fillBand(ctx, tToX(l.start), tToX(l.end), height, letterColor, HOVER_ALPHA_LETTER);
                        break;
                    }
                }
            }
            if (phonemesActive) {
                for (const iv of intervals) {
                    if (t >= iv.start && t < iv.end) {
                        _fillBand(ctx, tToX(iv.start), tToX(iv.end), height, phonemeColor, HOVER_ALPHA_PHONEME);
                        break;
                    }
                }
            }
        } else if (audioPaused) {
            const hover = $tsHoveredElement;
            if (hover) {
                const sx = tToX(hover.startSec);
                const ex = tToX(hover.endSec);
                if (hover.kind === 'word') {
                    _fillBand(ctx, sx, ex, height, wordColor, HOVER_ALPHA_WORD);
                } else if (hover.kind === 'letter') {
                    _fillBand(ctx, sx, ex, height, letterColor, HOVER_ALPHA_LETTER);
                } else {
                    _fillBand(ctx, sx, ex, height, phonemeColor, HOVER_ALPHA_PHONEME);
                }
            }
        }

        // 3. Boundary markers with precedence: word > letter > phoneme.
        //
        // For each token we emit BOTH its start and its end column so the last
        // token before a silence gap (where `next.start > this.end`) still gets
        // a visible closing line. The `occupied` Set handles the common case
        // where adjacent tokens share a boundary.
        const occupied = new Set<number>();
        const addOccupied = (x: number): void => {
            for (let dx = -BOUNDARY_DEDUP_EPS; dx <= BOUNDARY_DEDUP_EPS; dx++) occupied.add(x + dx);
        };
        const pushIfFree = (xs: number[], x: number): void => {
            if (occupied.has(x)) return;
            xs.push(x);
            addOccupied(x);
        };

        const wordXs: number[] = [];
        for (const w of words) {
            pushIfFree(wordXs, Math.round(tToX(w.start)));
            pushIfFree(wordXs, Math.round(tToX(w.end)));
        }

        const letterXs: number[] = [];
        if (lettersActive) {
            for (const w of words) {
                for (const l of w.letters) {
                    if (l.start == null || l.end == null) continue;
                    pushIfFree(letterXs, Math.round(tToX(l.start)));
                    pushIfFree(letterXs, Math.round(tToX(l.end)));
                }
            }
        }

        const phonemeXs: number[] = [];
        if (phonemesActive) {
            for (const iv of intervals) {
                pushIfFree(phonemeXs, Math.round(tToX(iv.start)));
                pushIfFree(phonemeXs, Math.round(tToX(iv.end)));
            }
        }

        // Draw phoneme → letter → word so the strongest tier renders on top.
        // Suppress a tier when its average pixel spacing falls below the
        // minimum threshold — lines become unreadable noise when too dense.
        const avgPhSpacing = phonemeXs.length > 1 ? width / phonemeXs.length : Infinity;
        const avgLtSpacing = letterXs.length  > 1 ? width / letterXs.length  : Infinity;
        _strokeLines(ctx,
            avgPhSpacing >= MIN_PHONEME_LINE_SPACING_PX ? phonemeXs : [],
            height, phonemeColor, PHONEME_LINE_WIDTH);
        _strokeLines(ctx,
            avgLtSpacing >= MIN_LETTER_LINE_SPACING_PX ? letterXs : [],
            height, letterColor, LETTER_LINE_WIDTH);
        _strokeLines(ctx, wordXs, height, wordColor, WORD_LINE_WIDTH);

        // 4. Playhead. Zoom-aware via `tToX` — playback outside the visible
        // window gets `px` past [0, width], clipped by canvas (i.e. no visible
        // playhead until playback re-enters the view).
        if (!dashPort.element) return;
        const time = dashPort.currentTimeMs() / 1000 - segOffset;
        const px = tToX(time);

        ctx.strokeStyle = PREVIEW_PLAYHEAD_COLOR;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, 0);
        ctx.lineTo(px, height);
        ctx.stroke();
        ctx.fillStyle = PREVIEW_PLAYHEAD_COLOR;
        ctx.beginPath();
        ctx.moveTo(px - 6, 0);
        ctx.lineTo(px + 6, 0);
        ctx.lineTo(px, 10);
        ctx.closePath();
        ctx.fill();
    }

    function _fillBand(
        ctx: CanvasRenderingContext2D,
        x0: number,
        x1: number,
        h: number,
        color: string,
        alpha: number,
    ): void {
        if (x1 <= x0) return;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.fillStyle = color;
        ctx.fillRect(x0, 0, x1 - x0, h);
        ctx.restore();
    }

    function _strokeLines(
        ctx: CanvasRenderingContext2D,
        xs: number[],
        h: number,
        color: string,
        width: number,
    ): void {
        if (!xs.length) return;
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.beginPath();
        for (const x of xs) {
            ctx.moveTo(x, 0);
            ctx.lineTo(x, h);
        }
        ctx.stroke();
    }

    // ---- Pointer handlers ----

    function _pointerTime(e: MouseEvent): number | null {
        if (!waveformRef) return null;
        const canvas = waveformRef.getCanvas();
        if (!canvas) return null;
        const win = dispWindow();
        if (!win) return null;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const progress = x / Math.max(1, rect.width);
        // Zoom-aware: when zoomed, pixel x maps back to view window, not full slice.
        if (_zoom) return _zoom.viewStart + progress * (_zoom.viewEnd - _zoom.viewStart);
        return progress * (win.end - win.offset);
    }

    function onCanvasMove(e: MouseEvent): void {
        const t = _pointerTime(e);
        if (t == null) return;
        _waveformHoverTime = t;
        tsWaveformHoverTime.set(t);
        drawOverlays();
    }

    function onCanvasLeave(): void {
        if (_waveformHoverTime == null) return;
        _waveformHoverTime = null;
        tsWaveformHoverTime.set(null);
        drawOverlays();
    }

    function onCanvasClick(e: MouseEvent): void {
        if (!dashPort.element || !dashPort.element.duration) return;
        const win = dispWindow();
        if (!win) return;
        const t = _pointerTime(e);
        if (t == null) return;

        const words = win.data.words;
        // Strict lookup — clicks in inter-word silence (or leading/trailing
        // margin) are no-ops rather than snapping to an unrelated token.
        const w = findWordAt(t, words, false);
        if (!w) return;

        // Loop mode: waveform clicks ALWAYS target the word tier (regardless
        // of which tiers are visible). Clicking the currently-looped word is
        // a no-op so the loop isn't interrupted by incidental clicks.
        const cur = get(loopTarget);
        if (cur) {
            const wi = words.indexOf(w);
            if (cur.kind === 'word' && cur.wordIndex === wi) return;
            loopTarget.set({ kind: 'word', startSec: w.start, endSec: w.end, wordIndex: wi });
            const targetMs = (w.start + win.offset) * 1000;
            ensureDashCovering(targetMs);
            dashPort.seek(targetMs);
            signalDashSeekIntent();
            if (dashPort.paused) dashPort.play();
            drawOverlays();
            return;
        }

        // Snap to enclosing word's start.
        const targetMs = (w.start + win.offset) * 1000;
        ensureDashCovering(targetMs);
        dashPort.seek(targetMs);
        signalDashSeekIntent();
        // Start playback if paused — matches block-click behavior.
        if (dashPort.paused) dashPort.play();
        drawOverlays();
    }

    // ---- Resize handling ----

    // Wheel zoom on the waveform canvas (works in both Analysis and Animation
    // views). `{ passive: false }` lets us call `preventDefault()` so scrolling
    // the wheel over the canvas doesn't also scroll the page. Wired via
    // addEventListener rather than svelte's `on:wheel` because the latter
    // doesn't support the passive flag.
    function onWheel(e: WheelEvent): void {
        if (!waveformRef) return;
        const canvas = waveformRef.getCanvas();
        if (!canvas) return;
        e.preventDefault();
        applyTsWheelZoom(canvas, e.clientX, e.deltaY);
    }

    // ---- Middle-mouse pan (while zoomed) --------------------------------
    //
    // Velocity-based pan: press middle button anchors a reference `clientX`;
    // the rAF loop pans `tsZoom` at a speed proportional to the cursor's
    // current offset from the anchor. At an offset of half the canvas width,
    // the view pans `TS_PAN_HALF_CANVAS_VIEWS_PER_SEC` view-widths per second.
    // Scales linearly; returning to the anchor stops the pan, crossing it
    // pans the other way.
    //
    // This single model captures both the "hold-and-drag" and "Windows-style
    // continuous autoscroll" interactions the user asked for: a fast cursor
    // flick produces a big transient offset (≈ direct drag), and a stationary
    // held offset produces continuous velocity (≈ autoscroll).
    //
    // `document`-level mousemove/mouseup so release anywhere (including
    // outside the canvas) ends the session cleanly.
    let _panAnchorX = 0;
    let _panCurrentX = 0;
    let _panRafId: number | null = null;
    let _panPrevTs = 0;

    function onMouseDown(e: MouseEvent): void {
        if (e.button !== 1) return;                // middle only
        if (get(tsZoom) === null) return;          // not zoomed → no-op
        if (isTsZoomAnimating()) return;           // tween in flight → no-op
        e.preventDefault();                        // suppress browser autoscroll cursor
        _panAnchorX = e.clientX;
        _panCurrentX = e.clientX;
        _panPrevTs = performance.now();
        document.addEventListener('mousemove', onPanMove);
        document.addEventListener('mouseup', onPanUp);
        containerEl?.classList.add('ts-pan-grabbing');
        if (_panRafId !== null) cancelAnimationFrame(_panRafId);
        _panRafId = requestAnimationFrame(panTick);
    }

    function onPanMove(e: MouseEvent): void {
        _panCurrentX = e.clientX;
    }

    function onPanUp(e: MouseEvent): void {
        if (e.button !== 1) return;                // require middle-button release
        if (_panRafId !== null) { cancelAnimationFrame(_panRafId); _panRafId = null; }
        document.removeEventListener('mousemove', onPanMove);
        document.removeEventListener('mouseup', onPanUp);
        containerEl?.classList.remove('ts-pan-grabbing');
    }

    /** Defensive variant of `onPanUp` that force-stops the session regardless
     *  of which button fired. Used by `panTick` when zoom state changes out
     *  from under it (tween starts, verse change) and by `onDestroy`. */
    function _forceEndPan(): void {
        if (_panRafId !== null) { cancelAnimationFrame(_panRafId); _panRafId = null; }
        document.removeEventListener('mousemove', onPanMove);
        document.removeEventListener('mouseup', onPanUp);
        containerEl?.classList.remove('ts-pan-grabbing');
    }

    function panTick(ts: number): void {
        const dtMs = ts - _panPrevTs;
        _panPrevTs = ts;
        const z = get(tsZoom);
        // Abort if zoom cleared (verse change) or a loop-tween took over —
        // the tween writes tsZoom each frame and we shouldn't fight it.
        if (z === null || isTsZoomAnimating()) {
            _forceEndPan();
            return;
        }
        const canvas = waveformRef?.getCanvas();
        if (!canvas) { _panRafId = requestAnimationFrame(panTick); return; }
        const rectWidth = canvas.getBoundingClientRect().width;
        const halfCanvas = (rectWidth || 1) / 2;
        const dxPx = _panCurrentX - _panAnchorX;
        const offsetNorm = dxPx / halfCanvas;
        const viewSpan = z.viewEnd - z.viewStart;
        const deltaSec = offsetNorm * viewSpan * TS_PAN_HALF_CANVAS_VIEWS_PER_SEC * (dtMs / 1000);
        if (deltaSec !== 0) panTsViewBy(deltaSec);
        _panRafId = requestAnimationFrame(panTick);
    }

    onMount(() => {
        updateSizeFromContainer();
        const onResize = (): void => {
            updateSizeFromContainer();
        };
        window.addEventListener('resize', onResize);
        // Theme flip: invalidate the cached base snapshot so peaks repaint with
        // the new theme's --wf-* colours, then redraw overlays. The reactive
        // `themeStore.current` dep above can't be relied on inside a legacy `$:`,
        // so this listener is the guaranteed repaint trigger.
        const onThemeChange = (): void => {
            curTheme = themeStore.current; // recompute the tier triad in the new band
            _baseImageData = null;
            _baseCacheKey = null;
            drawOverlays();
        };
        window.addEventListener(THEME_CHANGE_EVENT, onThemeChange);
        const canvas = waveformRef?.getCanvas();
        canvas?.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            window.removeEventListener('resize', onResize);
            window.removeEventListener(THEME_CHANGE_EVENT, onThemeChange);
            canvas?.removeEventListener('wheel', onWheel);
            _forceEndPan();
        };
    });

    function updateSizeFromContainer(): void {
        if (!containerEl) return;
        const rect = containerEl.getBoundingClientRect();
        const w = Math.max(1, Math.floor(rect.width));
        if (w === canvasWidth) return;
        canvasWidth = w;
        const key = _baseCacheKey ?? '';
        _baseImageData = null;
        if (peaks) {
            void tick().then(() => {
                _captureBase(key);
                drawOverlays();
            });
        }
    }
</script>

<div
    bind:this={containerEl}
    class="visualization"
    on:click={onCanvasClick}
    on:mousedown={onMouseDown}
    on:mousemove={onCanvasMove}
    on:mouseleave={onCanvasLeave}
    on:keydown={() => {}}
    role="button"
    tabindex="-1"
>
    <WaveformCanvas bind:this={waveformRef} {peaks} width={canvasWidth} height={canvasHeight}
        startMs={wcStartMs} endMs={wcEndMs} totalDurationMs={wcTotalDurationMs} />
</div>
