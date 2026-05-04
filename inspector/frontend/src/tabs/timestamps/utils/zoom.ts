/**
 * Timestamps tab — waveform zoom helpers + lifecycle.
 *
 * Two ways the visible window narrows:
 *
 *   1. **Loop-driven** (`computeZoomView` + `animateZoomTo`) — every time
 *      the loop target lands on a new word (entry, switch, exit-and-
 *      re-enter), the view window slides to `[wordStart - dur/2,
 *      wordEnd + dur/2]` (interior: width = `2 × dur`). Each side is
 *      clamped independently to `[0, fullSpan]`: near-edge words keep the
 *      full 50% padding on the NON-clamped side and show up to the slice
 *      bound on the clamped side — i.e. they get a narrower view rather
 *      than a shifted-same-width view. The slide itself is an rAF tween
 *      of `TS_ZOOM_ANIMATE_MS` with an ease-out curve — teleporting felt
 *      abrupt and made "where did my view go" confusing when switching
 *      loops.
 *
 *   2. **Wheel-driven** (`applyTsWheelZoom`) — standard zoom-to-cursor on
 *      wheel events over the canvas. Instant (no tween) because the wheel
 *      IS the animation. Bounded by `TS_MIN_VIEW_SEC` and `fullSpan`;
 *      reaching `fullSpan` clears `tsZoom` so the canvas falls back to
 *      the full-slice peak base.
 *
 * Lifecycle (`setupZoomLifecycle`):
 *   - `null → target`          → animate full view → zoomViewFor(target).
 *   - `A → B` (different word) → animate current view → zoomViewFor(B).
 *   - drill within same word    → no-op (letter/phoneme inside word A).
 *   - `target → null`          → animate current view → [0, fullSpan],
 *                                  then clear tsZoom (mirror of entry).
 *   - verse change             → cancel tween, `tsZoom.set(null)` (no
 *                                  animation — user left the context).
 *
 * A single `_activeRafId` guards against overlapping tweens: firing a new
 * animation cancels the previous one, so rapid loop switches don't leave
 * two frame loops racing to write `tsZoom`.
 *
 * All times here are SLICE-RELATIVE seconds (matching `loopTarget`,
 * `findWordAt`, and the waveform's `tToX` mapping).
 */

import { get } from 'svelte/store';

import { TS_VIEW_MODES, viewMode } from '../stores/display';
import { loopTarget } from '../stores/playback';
import type { TsLoopTarget } from '../stores/playback';
import { loadedVerse } from '../stores/verse';
import { tsZoom, tsZoomAnimating } from '../stores/zoom';
import type { TsZoom } from '../stores/zoom';
import {
    TS_MIN_VIEW_SEC,
    TS_WHEEL_ZOOM_FACTOR,
    TS_ZOOM_ANIMATE_MAX_MS,
    TS_ZOOM_ANIMATE_MIN_MS,
    TS_ZOOM_ANIMATE_MS_PER_SEC,
} from './constants';

/** Slice span in seconds: `tsSegEnd - tsSegOffset`, the upper bound for any
 *  view window. Returns 0 if no verse is loaded. */
function _fullSpanSec(): number {
    const lv = get(loadedVerse);
    if (!lv) return 0;
    return Math.max(0, lv.tsSegEnd - lv.tsSegOffset);
}

/**
 * Compute (don't commit) the view window that should display the word
 * `[wordStart, wordEnd]`: the natural window is `[wordStart - dur/2,
 * wordEnd + dur/2]` (50% word-duration padding on each side, total width
 * `2 × dur`). Each side is clamped INDEPENDENTLY to `[0, fullSpan]`:
 *
 *   - Interior words → both paddings fit → width = `2 × dur`.
 *   - Near-left-edge → left padding clamped to 0; right keeps full 50% →
 *     narrower view, word aligned to the left of it.
 *   - Near-right-edge → symmetric on the other side.
 *
 * This is different from the earlier shift-preserve-width policy (where a
 * near-edge word kept the full `2 × dur` width by shifting the view) —
 * users found it confusing that edge words had the same width but
 * off-center framing. Independent clamping trades width for consistent
 * framing: the 50%-padding rule visibly holds on whichever side isn't
 * clamped.
 *
 * Returns `null` only when the post-clamp window spans the entire slice
 * (caller should clear `tsZoom` so the canvas uses the full-slice base) —
 * e.g. a word so long that even symmetric padding leaves no slack on
 * either side.
 */
export function computeZoomView(
    wordStart: number,
    wordEnd: number,
    fullSpan: number,
): TsZoom | null {
    if (fullSpan <= 0 || wordEnd <= wordStart) return null;
    const pad = (wordEnd - wordStart) / 2;
    let viewStart = wordStart - pad;
    let viewEnd = wordEnd + pad;
    if (viewStart < 0) viewStart = 0;
    if (viewEnd > fullSpan) viewEnd = fullSpan;
    if (viewEnd - viewStart >= fullSpan - 1e-9) return null;
    if (viewEnd <= viewStart) return null;
    return { viewStart, viewEnd };
}

/**
 * Commit `computeZoomView` directly (no animation). Used by tests and by
 * wheel-zoom; the loop-target path uses `animateZoomTo` instead.
 */
export function zoomToWord(wordStart: number, wordEnd: number): void {
    const v = computeZoomView(wordStart, wordEnd, _fullSpanSec());
    tsZoom.set(v);
}

// ---- rAF tween ----------------------------------------------------------

let _activeRafId: number | null = null;
let _animatingFlag = false;

/** True while a zoom tween is mid-flight. `TimestampsWaveform` reads this
 *  to gate its expensive per-frame `_captureBase` (ImageData snapshot) so
 *  the snapshot lands once at the end of the tween, not every frame. */
export function isTsZoomAnimating(): boolean {
    return _animatingFlag;
}

function _setAnimatingFlag(v: boolean): void {
    _animatingFlag = v;
    tsZoomAnimating.set(v);
}

function _cancelTween(): void {
    if (_activeRafId !== null) {
        cancelAnimationFrame(_activeRafId);
        _activeRafId = null;
    }
    _setAnimatingFlag(false);
}

/** Ease-in-out-quad: accelerate, hold near-constant speed, decelerate. Gives
 *  the "reel through the waveform" effect — middle of the tween has the
 *  clearest, most legible pan because that's where the user spends the
 *  most perceptual time. Ease-out-cubic front-loads motion (90% done in
 *  first 30% of time), which makes the sweep look like a teleport for any
 *  non-trivial jump. */
function _easeInOutQuad(x: number): number {
    return x < 0.5 ? 2 * x * x : 1 - ((-2 * x + 2) ** 2) / 2;
}

/**
 * Duration in ms for a sweep between two view windows. Scales linearly
 * with center-distance (ms per second of audio travelled) and clamps to
 * [MIN, MAX]. Short hops stay snappy; long jumps get enough time to read
 * as a visible scroll through the intermediate waveform.
 */
export function computeSweepDurationMs(fromView: TsZoom, toView: TsZoom): number {
    const fromCenter = (fromView.viewStart + fromView.viewEnd) / 2;
    const toCenter = (toView.viewStart + toView.viewEnd) / 2;
    const distance = Math.abs(toCenter - fromCenter);
    const scaled = TS_ZOOM_ANIMATE_MIN_MS + distance * TS_ZOOM_ANIMATE_MS_PER_SEC;
    return Math.min(TS_ZOOM_ANIMATE_MAX_MS, Math.max(TS_ZOOM_ANIMATE_MIN_MS, scaled));
}

/**
 * Core rAF tween. `target` is always a concrete window; `finalizeToNull`
 * tells the step function to commit `tsZoom.set(null)` at end instead of
 * `tsZoom.set(target)` — used by `animateZoomOut` to reverse-mirror the
 * entry animation (view widens back to full slice, then drops the zoom so
 * the canvas reuses the full-slice peak base).
 */
function _runTween(
    fromView: TsZoom,
    toView: TsZoom,
    durationMs: number,
    finalizeToNull: boolean,
): void {
    const EPS = 1e-4;
    if (
        Math.abs(fromView.viewStart - toView.viewStart) < EPS
        && Math.abs(fromView.viewEnd - toView.viewEnd) < EPS
    ) {
        tsZoom.set(finalizeToNull ? null : toView);
        return;
    }
    if (durationMs <= 0) {
        tsZoom.set(finalizeToNull ? null : toView);
        return;
    }

    const { viewStart: fromStart, viewEnd: fromEnd } = fromView;
    const { viewStart: toStart, viewEnd: toEnd } = toView;
    const startTs = performance.now();
    _setAnimatingFlag(true);

    const step = (now: number): void => {
        const elapsed = now - startTs;
        const t = Math.min(1, elapsed / durationMs);
        const e = _easeInOutQuad(t);
        if (t >= 1) {
            _activeRafId = null;
            _setAnimatingFlag(false);
            tsZoom.set(finalizeToNull ? null : { viewStart: toStart, viewEnd: toEnd });
            return;
        }
        tsZoom.set({
            viewStart: fromStart + (toStart - fromStart) * e,
            viewEnd:   fromEnd   + (toEnd   - fromEnd)   * e,
        });
        _activeRafId = requestAnimationFrame(step);
    };

    _activeRafId = requestAnimationFrame(step);
}

/**
 * Tween `tsZoom` from its current value (or full-slice if `null`) to
 * `target` over `durationMs`. If `target` is `null`, snaps immediately
 * (use `animateZoomOut` for an animated exit). If the from/to windows are
 * effectively equal, commits `target` without spinning a frame loop.
 *
 * Any in-flight tween is cancelled before the new one starts — call sites
 * never need to track rAF ids themselves.
 */
export function animateZoomTo(target: TsZoom | null, durationMs: number): void {
    _cancelTween();
    if (target === null) {
        tsZoom.set(null);
        return;
    }
    const fullSpan = _fullSpanSec();
    if (fullSpan <= 0) {
        tsZoom.set(target);
        return;
    }
    const cur = get(tsZoom) ?? { viewStart: 0, viewEnd: fullSpan };
    _runTween(cur, target, durationMs, /* finalizeToNull */ false);
}

/**
 * Animate `tsZoom` from its current (zoomed) value back out to
 * `[0, fullSpan]`, ending with `tsZoom.set(null)` so the waveform falls
 * back to the full-slice peak base. This is the exit counterpart of
 * `animateZoomTo` and produces the reverse of the entry sweep: view
 * widens and centers slide out until the whole slice is visible.
 *
 * No-ops when already unzoomed (`tsZoom` is `null`) or when the verse
 * hasn't loaded (`fullSpan === 0`) — nothing meaningful to animate.
 */
export function animateZoomOut(durationMs: number): void {
    _cancelTween();
    const cur = get(tsZoom);
    if (cur === null) return;
    const fullSpan = _fullSpanSec();
    if (fullSpan <= 0) {
        tsZoom.set(null);
        return;
    }
    const toView: TsZoom = { viewStart: 0, viewEnd: fullSpan };
    _runTween(cur, toView, durationMs, /* finalizeToNull */ true);
}

/**
 * Mouse-wheel zoom on the waveform canvas, centered on the mouse cursor
 * (time at mouse stays under mouse). Bounded by `TS_MIN_VIEW_SEC` (floor)
 * and `fullSpan` (ceiling); reaching `fullSpan` clears `tsZoom`.
 *
 * Works in any view (Analysis or Animation). Caller (`TimestampsWaveform`)
 * gates on the wheel event itself — `e.preventDefault()` to suppress page
 * scroll. Cancels any loop-driven tween in flight so the two don't race.
 */
export function applyTsWheelZoom(
    canvas: HTMLCanvasElement,
    mouseClientX: number,
    deltaY: number,
): void {
    const fullSpan = _fullSpanSec();
    if (fullSpan <= 0) return;

    _cancelTween();

    const cur = get(tsZoom) ?? { viewStart: 0, viewEnd: fullSpan };
    const rect = canvas.getBoundingClientRect();
    const w = canvas.width;
    const mouseX = (mouseClientX - rect.left) * (w / Math.max(1, rect.width));

    const curRange = cur.viewEnd - cur.viewStart;
    const factor = deltaY < 0 ? TS_WHEEL_ZOOM_FACTOR : 1 / TS_WHEEL_ZOOM_FACTOR;
    let newRange = curRange * factor;
    newRange = Math.max(TS_MIN_VIEW_SEC, Math.min(newRange, fullSpan));
    if (newRange === curRange) return;

    const ratio = mouseX / w;
    const tAtMouse = cur.viewStart + ratio * curRange;
    let newViewStart = tAtMouse - ratio * newRange;
    let newViewEnd = newViewStart + newRange;

    if (newViewStart < 0)        { newViewStart = 0;            newViewEnd = newRange; }
    if (newViewEnd > fullSpan)   { newViewEnd = fullSpan;       newViewStart = fullSpan - newRange; }

    if (newRange >= fullSpan - 1e-6) {
        tsZoom.set(null);
        return;
    }
    tsZoom.set({ viewStart: newViewStart, viewEnd: newViewEnd });
}

/**
 * Shift `tsZoom` by `deltaSec` seconds, preserving the view WIDTH and
 * clamping the result to `[0, fullSpan]`. The middle-mouse-button pan
 * handler on `TimestampsWaveform` calls this once per rAF frame with
 * a velocity-integrated delta.
 *
 * Width preservation matters: the user is navigating within a fixed zoom
 * level, not resizing the window. If a naive `viewStart += delta` left
 * the right edge past `fullSpan`, the window would shrink at the edge
 * — that's zoom-out behaviour, which isn't what pan should do. Instead
 * we translate both edges by the same amount up to the clamp, then pin
 * the window flush against the edge once it's exhausted its headroom
 * (further pan in the same direction becomes a no-op).
 *
 * No-ops when `tsZoom` is `null` (caller gates on this, but double-
 * checking here is cheap and keeps the helper standalone).
 */
export function panTsViewBy(deltaSec: number): void {
    const cur = get(tsZoom);
    if (cur === null) return;
    if (deltaSec === 0) return;
    const fullSpan = _fullSpanSec();
    if (fullSpan <= 0) return;

    const width = cur.viewEnd - cur.viewStart;
    let newStart = cur.viewStart + deltaSec;
    let newEnd = cur.viewEnd + deltaSec;
    if (newStart < 0) {
        newStart = 0;
        newEnd = width;
    }
    if (newEnd > fullSpan) {
        newEnd = fullSpan;
        newStart = fullSpan - width;
    }
    if (newStart === cur.viewStart && newEnd === cur.viewEnd) return; // fully clamped
    tsZoom.set({ viewStart: newStart, viewEnd: newEnd });
}

// ---- Lifecycle ----------------------------------------------------------

let _wired = false;

/**
 * Wire the zoom lifecycle — all `loopTarget` and `loadedVerse` transitions
 * funnel through one place so callsites (`toggleLoopOn`, `onCanvasClick`,
 * `onWordClick`, etc.) don't each hook zoom independently. Idempotent via
 * `_wired` — safe to call from `TimestampsTab.onMount`.
 *
 * Behavior: loop-driven changes always settle at `width = 2 × dur(newWord)`,
 * animated. There is no "preserve width across switches" mode — that
 * produced entry-vs-switch asymmetry and confused users who expected
 * re-entering a loop on the same word to look the same as switching to it
 * mid-session. Single rule: the window always fits the current word.
 */
export function setupZoomLifecycle(): void {
    if (_wired) return;
    _wired = true;

    let prevLoop: TsLoopTarget | null = get(loopTarget);
    loopTarget.subscribe((lt) => {
        const wasLooped = prevLoop !== null;
        const isLooped = lt !== null;
        const prevWordIdx = prevLoop?.wordIndex ?? null;
        const nextWordIdx = lt?.wordIndex ?? null;

        if (wasLooped && !isLooped) {
            // Exit — reverse the entry animation: widen the view back to
            // the full slice, THEN clear tsZoom. Duration scales with the
            // distance from the current zoomed center to the slice center
            // (same sweep model as entry/switch) so short hops out feel
            // snappy and long hops give visible context restoration.
            const cur = get(tsZoom);
            const fullSpan = _fullSpanSec();
            if (cur && fullSpan > 0) {
                const fullView: TsZoom = { viewStart: 0, viewEnd: fullSpan };
                animateZoomOut(computeSweepDurationMs(cur, fullView));
            } else {
                animateZoomOut(0);
            }
        } else if (isLooped && (!wasLooped || prevWordIdx !== nextWordIdx)) {
            // Entry OR cross-word switch — animate to fresh word window.
            _animateToWord(lt!.wordIndex);
        }
        // else: drill within same word (letter/phoneme) → leave zoom alone.

        prevLoop = lt;
    });

    let prevUrl = get(loadedVerse)?.data.audio_url ?? null;
    loadedVerse.subscribe((lv) => {
        const url = lv?.data.audio_url ?? null;
        if (url !== prevUrl) {
            animateZoomTo(null, 0);
            prevUrl = url;
        }
    });
}

/** Slide the view to the word at `wordIndex`. Analysis view only — Animation
 *  view stays full-width per spec. Duration scales with the center-distance
 *  travelled so long jumps (e.g. word 1 → word 25) reel visibly through the
 *  intermediate waveform instead of snapping in one blink. */
function _animateToWord(wordIndex: number): void {
    if (get(viewMode) !== TS_VIEW_MODES.ANALYSIS) return;
    const lv = get(loadedVerse);
    const word = lv?.data.words[wordIndex];
    if (!word) return;
    const fullSpan = Math.max(0, lv!.tsSegEnd - lv!.tsSegOffset);
    const target = computeZoomView(word.start, word.end, fullSpan);
    if (target === null) {
        // Clamped window covers the whole slice → drop zoom, no sweep needed.
        animateZoomTo(null, 0);
        return;
    }
    const fromView = get(tsZoom) ?? { viewStart: 0, viewEnd: fullSpan };
    animateZoomTo(target, computeSweepDurationMs(fromView, target));
}

// ---- Test-only hooks ----------------------------------------------------

/** Reset the module's wired/animation state. Vitest-only — the implementation
 *  relies on module-level state that would otherwise leak across tests. */
export function _resetZoomModuleForTests(): void {
    _cancelTween();
    _wired = false;
}
