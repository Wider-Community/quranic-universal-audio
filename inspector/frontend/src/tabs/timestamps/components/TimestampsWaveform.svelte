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
    import { loadedVerse, selectedReciter } from '../stores/verse';
    import { loopTarget, tsAudioElement } from '../stores/playback';
    import {
        TS_GRANULARITIES,
        TS_VIEW_MODES,
        granularity,
        showLetters,
        showPhonemes,
        tsConfig,
        tsHoveredElement,
        tsWaveformHoverTime,
        viewMode,
    } from '../stores/display';
    import { findWordAt } from '../utils/loop-target';
    import { applyTsWheelZoom, isTsZoomAnimating, panTsViewBy } from '../utils/zoom';
    import { tsZoom, tsZoomAnimating } from '../stores/zoom';
    import { TS_PAN_HALF_CANVAS_VIEWS_PER_SEC } from '../utils/constants';
    import { fetchSegmentPeaks } from '../../../lib/utils/peaks-fetch';
    import { drawWaveformPeaks } from '../../../lib/utils/waveform-draw';
    import { safePlay } from '../../../lib/utils/audio';
    import type { PeakBucket, SegmentPeaks } from '../../../lib/types/domain';
    import {
        LETTER_HIGHLIGHT_COLOR,
        PREVIEW_PLAYHEAD_COLOR,
        WAVEFORM_BG_COLOR,
        WAVEFORM_STROKE_COLOR,
    } from '../../../lib/utils/constants';

    // ---- Local layout constants ----
    const TS_WAVEFORM_DEFAULT_WIDTH = 1200;
    const TS_WAVEFORM_HEIGHT = 200;
    const TS_PHONEME_LABEL_STRIP_HEIGHT = 30;
    /** Max in-component peaks slices retained across verse switches. */
    const PEAKS_LRU_SIZE = 5;

    // Fallback word color if /api/ts/config hasn't loaded yet.
    const WORD_COLOR_FALLBACK = '#f0a500';

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

    // ---- Sizing ----

    let containerEl: HTMLDivElement;
    let waveformRef: WaveformCanvas;
    let canvasWidth = TS_WAVEFORM_DEFAULT_WIDTH;
    const canvasHeight = TS_WAVEFORM_HEIGHT;

    // ---- Peaks ----

    let peaks: PeakBucket[] | null = null;
    let fetchGen = 0;

    /** Per-tab LRU keyed by `${url}:${startMs}:${endMs}`. */
    const _peaksLRU = new Map<string, SegmentPeaks>();

    function _lruGet(key: string): SegmentPeaks | undefined {
        const v = _peaksLRU.get(key);
        if (v !== undefined) {
            _peaksLRU.delete(key);
            _peaksLRU.set(key, v);
        }
        return v;
    }

    function _lruSet(key: string, value: SegmentPeaks): void {
        if (_peaksLRU.size >= PEAKS_LRU_SIZE) {
            const oldest = _peaksLRU.keys().next().value;
            if (oldest !== undefined) _peaksLRU.delete(oldest);
        }
        _peaksLRU.set(key, value);
    }

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
    $: wordColor = $tsConfig?.anim_highlight_color ?? WORD_COLOR_FALLBACK;

    // Redraw when toggles / hover store / loop store change so overlays update
    // even while paused. Subscriptions on `$tsHoveredElement` and `$loopTarget`
    // trigger block-originated hover renders + loop band updates respectively.
    $: ($tsHoveredElement, $loopTarget, lettersActive, phonemesActive, wordColor, drawOverlays());

    // ---- Zoom: pass sub-range to WaveformCanvas + recapture base on change ----

    /** Cached for fast read inside `tToX` / `_pointerTime` (avoids repeated
     *  `get(tsZoom)` per draw call). Updated by the reactive subscription. */
    let _zoom: { viewStart: number; viewEnd: number } | null = null;
    $: _zoom = $tsZoom;

    /** Sub-range props forwarded to WaveformCanvas. Both `undefined` → full
     *  slice (default). When zoomed, `wcStartMs/wcEndMs` are SLICE-relative
     *  ms (the WaveformCanvas already has full-slice peaks; we just tell it
     *  which window to render). */
    $: wcTotalDurationMs = $loadedVerse
        ? Math.round(($loadedVerse.tsSegEnd - $loadedVerse.tsSegOffset) * 1000)
        : undefined;
    $: wcStartMs = _zoom ? Math.round(_zoom.viewStart * 1000) : undefined;
    $: wcEndMs = _zoom ? Math.round(_zoom.viewEnd * 1000) : undefined;

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

    $: reactToVerse(
        $loadedVerse?.data.audio_url ?? null,
        $loadedVerse?.tsSegOffset ?? 0,
        $loadedVerse?.tsSegEnd ?? 0,
    );

    async function reactToVerse(
        url: string | null,
        startSec: number,
        endSec: number,
    ): Promise<void> {
        if (!url) {
            peaks = null;
            _baseImageData = null;
            _baseCacheKey = null;
            return;
        }
        const startMs = Math.max(0, Math.round(startSec * 1000));
        const endMs = Math.round(endSec * 1000);
        if (endMs <= startMs) {
            peaks = null;
            _baseImageData = null;
            _baseCacheKey = null;
            return;
        }
        const reciter = get(selectedReciter);
        if (!reciter) return;

        const key = `${url}:${startMs}:${endMs}`;
        const gen = ++fetchGen;

        let entry: SegmentPeaks | null | undefined = _lruGet(key);
        if (!entry) {
            try {
                entry = await fetchSegmentPeaks(reciter, url, startMs, endMs);
            } catch (e) {
                console.error('Waveform peaks fetch failed:', e);
                return;
            }
            if (gen !== fetchGen) return;
            if (!entry || !entry.peaks?.length) {
                peaks = null;
                _baseImageData = null;
                _baseCacheKey = null;
                return;
            }
            _lruSet(key, entry);
        }

        peaks = entry.peaks;

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
            const lv = get(loadedVerse);
            const zoom = _zoom;
            const totalMs = lv ? Math.round((lv.tsSegEnd - lv.tsSegOffset) * 1000) : undefined;
            drawWaveformPeaks(ctx, peaks, {
                width: canvas.width,
                height: canvas.height,
                startMs: zoom ? Math.round(zoom.viewStart * 1000) : undefined,
                endMs: zoom ? Math.round(zoom.viewEnd * 1000) : undefined,
                totalDurationMs: totalMs,
            });
        }
        _baseImageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        _baseCacheKey = key;
    }

    // ---- Overlays ----

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
        const heightAll = canvas.height;
        const height = heightAll - TS_PHONEME_LABEL_STRIP_HEIGHT;
        const lv = get(loadedVerse);
        if (!lv) return;

        const segOffset = lv.tsSegOffset;
        const segEnd = lv.tsSegEnd;
        const duration = segEnd - segOffset || 1;
        const words = lv.data.words;
        const intervals = lv.data.intervals;

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
        if (!animating && _baseImageData && _baseImageData.width === width && _baseImageData.height === heightAll) {
            ctx.putImageData(_baseImageData, 0, 0);
        } else if (peaks) {
            const zoomMs = _zoom
                ? { startMs: Math.round(_zoom.viewStart * 1000), endMs: Math.round(_zoom.viewEnd * 1000) }
                : { startMs: undefined, endMs: undefined };
            drawWaveformPeaks(ctx, peaks, {
                width,
                height: heightAll,
                startMs: zoomMs.startMs,
                endMs: zoomMs.endMs,
                totalDurationMs: Math.round(duration * 1000),
            });
        } else {
            ctx.fillStyle = '#0f0f23';
            ctx.fillRect(0, 0, width, heightAll);
        }

        // Zoom-aware time → pixel. When `_zoom` is null, maps the full slice to
        // canvas width (existing behavior). When zoomed, maps only [viewStart,
        // viewEnd] — boundaries/fills/playhead outside the view naturally land
        // past [0, width] and get clipped by the canvas.
        const tToX = _zoom
            ? (t: number): number => ((t - _zoom!.viewStart) / (_zoom!.viewEnd - _zoom!.viewStart)) * width
            : (t: number): number => (t / duration) * width;
        const audio = get(tsAudioElement);
        const audioPaused = !audio || audio.paused;

        // 1.5. Dim silence-region peaks. MFA phoneme tiling is vocal-only in
        //      this dataset, so silence is inferred from inter-word gaps plus
        //      the head/tail margins of the slice. Fading the peaks toward bg
        //      gives the classic DAW "quiet zone" look without a rectangular wash.
        const dimSilence = (start: number, end: number): void => {
            if (end <= start) return;
            _fillBand(ctx, tToX(start), tToX(end), heightAll, WAVEFORM_BG_COLOR, SILENCE_DIM_ALPHA);
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
                loopColor = LETTER_HIGHLIGHT_COLOR;
                loopAlpha = PLAYING_ALPHA_LETTER;
            } else {
                loopColor = WAVEFORM_STROKE_COLOR;
                loopAlpha = PLAYING_ALPHA_PHONEME;
            }
            _fillBand(ctx, tToX(loop.startSec), tToX(loop.endSec), height, loopColor, loopAlpha);
        }

        // 2a. Playing-current fills — always show the tiers currently active,
        //     based on audio.currentTime, in both Analysis and Animation modes.
        //     Drawn below hover so hover stays visually dominant.
        if (audio) {
            const t = audio.currentTime - segOffset;
            const curW = findWordAt(t, words, false);
            if (curW) _fillBand(ctx, tToX(curW.start), tToX(curW.end), height, wordColor, PLAYING_ALPHA_WORD);
            if (lettersActive && curW) {
                for (const l of curW.letters) {
                    if (l.start == null || l.end == null) continue;
                    if (t >= l.start && t < l.end) {
                        _fillBand(ctx, tToX(l.start), tToX(l.end), height, LETTER_HIGHLIGHT_COLOR, PLAYING_ALPHA_LETTER);
                        break;
                    }
                }
            }
            if (phonemesActive) {
                for (const iv of intervals) {
                    if (t >= iv.start && t < iv.end) {
                        _fillBand(ctx, tToX(iv.start), tToX(iv.end), height, WAVEFORM_STROKE_COLOR, PLAYING_ALPHA_PHONEME);
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
                        _fillBand(ctx, tToX(l.start), tToX(l.end), height, LETTER_HIGHLIGHT_COLOR, HOVER_ALPHA_LETTER);
                        break;
                    }
                }
            }
            if (phonemesActive) {
                for (const iv of intervals) {
                    if (t >= iv.start && t < iv.end) {
                        _fillBand(ctx, tToX(iv.start), tToX(iv.end), height, WAVEFORM_STROKE_COLOR, HOVER_ALPHA_PHONEME);
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
                    _fillBand(ctx, sx, ex, height, LETTER_HIGHLIGHT_COLOR, HOVER_ALPHA_LETTER);
                } else {
                    _fillBand(ctx, sx, ex, height, WAVEFORM_STROKE_COLOR, HOVER_ALPHA_PHONEME);
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
        _strokeLines(ctx, phonemeXs, height, WAVEFORM_STROKE_COLOR, PHONEME_LINE_WIDTH);
        _strokeLines(ctx, letterXs, height, LETTER_HIGHLIGHT_COLOR, LETTER_LINE_WIDTH);
        _strokeLines(ctx, wordXs, height, wordColor, WORD_LINE_WIDTH);

        // 4. Playhead. Zoom-aware via `tToX` — playback outside the visible
        // window gets `px` past [0, width], clipped by canvas (i.e. no visible
        // playhead until playback re-enters the view).
        if (!audio) return;
        const time = audio.currentTime - segOffset;
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
        const lv = get(loadedVerse);
        if (!lv) return null;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const progress = x / Math.max(1, rect.width);
        // Zoom-aware: when zoomed, pixel x maps back to view window, not full slice.
        if (_zoom) return _zoom.viewStart + progress * (_zoom.viewEnd - _zoom.viewStart);
        return progress * (lv.tsSegEnd - lv.tsSegOffset);
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
        const audio = get(tsAudioElement);
        if (!audio || !audio.duration) return;
        const lv = get(loadedVerse);
        if (!lv) return;
        const t = _pointerTime(e);
        if (t == null) return;

        const words = lv.data.words;
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
            audio.currentTime = w.start + lv.tsSegOffset;
            if (audio.paused) void safePlay(audio);
            drawOverlays();
            return;
        }

        // Snap to enclosing word's start.
        audio.currentTime = w.start + lv.tsSegOffset;
        // Start playback if paused — matches block-click behavior.
        if (audio.paused) void safePlay(audio);
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
        const canvas = waveformRef?.getCanvas();
        canvas?.addEventListener('wheel', onWheel, { passive: false });
        return () => {
            window.removeEventListener('resize', onResize);
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
    <div class="phoneme-labels" id="phoneme-labels"></div>
</div>
