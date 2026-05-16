/**
 * CBR audio warmup — NOT a revival of the deleted `prefetchNextSegAudio`.
 *
 * Different semantics: a 64 KB Range fetch at the seg's byte offset (vs the
 * deleted util's full chapter `fetch().blob()`); priority hint; 30 s dedupe;
 * fires on user-intent signals (chapter load, accordion mount, hover,
 * play→next-seg). Same goal — hide cold-FUSE / cold-CDN play stalls — but
 * ~80% less bandwidth and actually targets the right bytes.
 *
 * VBR is deferred — segments tab routes VBR per-seg through the segment-clip
 * endpoint, which is its own pre-rendered, deterministically-cacheable URL.
 *
 * Skip rules (in order):
 *   1. Chapter not CBR with valid kbps  → no-op (covers VBR + missing data).
 *   2. Same `(reciter, audio_url, byteStart >> 16)` warmed within 30 s → skip.
 *   3. When `current` supplied: same chapter AND `gap < 30 s` → skip
 *      (browser forward buffer covers it).
 *
 * Byte formula (CBR, naive — server-side FUSE page-cache warming is what
 * matters, not browser-side Range coalescing, and 64 KB covers the typical
 * ~25 KB ID3v2 prefix offset error):
 *
 *   bytesPerSec = kbps * 125            // = kbps * 1000 / 8
 *   byteStart   = (time_start / 1000) * bytesPerSec
 *
 * Cost: one 64 KB Range fetch per warm. Fire-and-forget; rejected fetches
 * are swallowed.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { segAllData } from '../../stores/chapter';
import { cbrKbpsForChapter } from '../../stores/chapter-meta';

/** Main-list segs from `/api/seg/all/<reciter>` deliberately omit `audio_url`
 *  to save wire bytes; every FE consumer falls back to the top-level
 *  `audio_by_chapter[chapter]` map. Mirror that here so the hover and
 *  next-seg triggers don't silently no-op on main-list segs. */
function _segAudioUrl(seg: Segment): string {
    if (seg.audio_url) return seg.audio_url;
    const chapter = seg.chapter;
    if (chapter == null) return '';
    return get(segAllData)?.audio_by_chapter?.[String(chapter)] ?? '';
}

const WARMUP_BYTES = 65536;            // 64 KB
const DEDUPE_WINDOW_MS = 30_000;
const PROXIMITY_GAP_MS = 30_000;

/** key -> last-fired-at-ms. Key is `${reciter}|${audio_url}|${byteBucket}`
 *  where byteBucket = byteStart >> 16, i.e. one slot per 64 KB region. */
const warmedRecently = new Map<string, number>();

function _pruneExpired(nowMs: number): void {
    for (const [k, t] of warmedRecently) {
        if (nowMs - t > DEDUPE_WINDOW_MS) warmedRecently.delete(k);
    }
}

function _fire(reciter: string, audioUrl: string, byteStart: number): void {
    const proxyUrl = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(audioUrl)}`;
    // `priority: 'low'` is a browser hint (RequestPriority); not in all TS lib
    // versions. Cast through `any` keeps the option without a global lib bump.
    const init: RequestInit & { priority?: string } = {
        headers: { Range: `bytes=${byteStart}-${byteStart + WARMUP_BYTES - 1}` },
        priority: 'low',
    };
    fetch(proxyUrl, init as RequestInit).catch(() => {});
}

function _warmAtByte(
    reciter: string,
    audioUrl: string,
    byteStart: number,
): void {
    const now = Date.now();
    _pruneExpired(now);
    const key = `${reciter}|${audioUrl}|${byteStart >> 16}`;
    const last = warmedRecently.get(key);
    if (last !== undefined && now - last < DEDUPE_WINDOW_MS) return;
    warmedRecently.set(key, now);
    _fire(reciter, audioUrl, byteStart);
}

/** Warm the chapter MP3 at the byte offset corresponding to `seg.time_start`.
 *
 *  Triggers: accordion card mount (first sibling), hover seg play button,
 *  play seg N → next sibling.
 *
 *  When `current` is supplied (next-sibling trigger), the proximity skip
 *  short-circuits when `seg` lives in the same chapter audio file and is
 *  less than 30 s past `current.time_end` — the browser's forward buffer
 *  on the active `<audio>` element will cover it.
 */
export function warmSeg(
    seg: Segment | null | undefined,
    reciter: string,
    current?: Segment | null,
): void {
    if (!seg || !reciter) return;
    const chapter = seg.chapter;
    if (chapter == null) return;
    const audioUrl = _segAudioUrl(seg);
    if (!audioUrl) return;
    const currentUrl = current ? _segAudioUrl(current) : '';
    if (current
        && currentUrl
        && currentUrl === audioUrl
        && seg.time_start - current.time_end < PROXIMITY_GAP_MS) return;
    const kbps = cbrKbpsForChapter(chapter);
    if (!kbps) return;
    const bytesPerSec = kbps * 125;
    const byteStart = Math.max(0, Math.floor((seg.time_start / 1000) * bytesPerSec));
    _warmAtByte(reciter, audioUrl, byteStart);
}

/** Warm bytes 0–65535 of a chapter MP3 — used by the chapter-load trigger
 *  where no seg context is yet available. Most reviewers start playback
 *  near the chapter start, so byte-0 is the right default. No-op for
 *  VBR + missing-kbps chapters (skip via `cbrKbpsForChapter`).
 */
export function warmChapterStart(
    reciter: string,
    audioUrl: string,
    chapter: number | null | undefined,
): void {
    if (!reciter || !audioUrl || chapter == null) return;
    if (!cbrKbpsForChapter(chapter)) return;
    _warmAtByte(reciter, audioUrl, 0);
}

// ---------------------------------------------------------------------------
// Visibility-driven warmup (IntersectionObserver)
// ---------------------------------------------------------------------------
//
// Covers the "user scrolls down to seg #50 then clicks play" pattern that
// the chapter-load + hover + play-next-seg triggers can't reach. Fires
// `warmSeg(seg, reciter)` when the row scrolls into the viewport (with a
// generous rootMargin so it fires before the user actually sees it).
//
// Single module-scoped observer keeps the per-row cost trivial across the
// ~11k-row main list. Each row registers on mount via `observeRowForWarmup`
// and unobserves on destroy. After the first fire we stop observing the
// element — subsequent visibility changes use the same dedupe map as the
// other triggers so a row that comes back into view doesn't re-fetch.

interface _WarmupTarget {
    getSeg: () => Segment | null | undefined;
    getReciter: () => string;
}

const _observed = new WeakMap<Element, _WarmupTarget>();

let _io: IntersectionObserver | null = null;

function _getObserver(): IntersectionObserver | null {
    if (typeof IntersectionObserver === 'undefined') return null;
    if (_io) return _io;
    _io = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const target = _observed.get(entry.target);
            if (!target) continue;
            warmSeg(target.getSeg(), target.getReciter());
            // One-shot: dedupe map already covers re-entries, but stop
            // observing this element to keep the observer's tracking set
            // small under heavy scrolling.
            _io?.unobserve(entry.target);
            _observed.delete(entry.target);
        }
    }, {
        // Fire ~200 px before the row scrolls into view so the warmup has
        // a head start before the user hovers / clicks.
        rootMargin: '200px 0px',
        threshold: 0,
    });
    return _io;
}

/** Register `el` for a one-shot warmup fire on first viewport entry.
 *  Returns an unobserve fn; SegmentRow calls it from onDestroy.
 *
 *  Getters (not snapshots) so split / merge / reindex of `seg` is reflected
 *  in the fire-time payload without needing to re-register the element.
 */
export function observeRowForWarmup(
    el: Element,
    getSeg: () => Segment | null | undefined,
    getReciter: () => string,
): () => void {
    const io = _getObserver();
    if (!io) return () => {};
    _observed.set(el, { getSeg, getReciter });
    io.observe(el);
    return () => {
        io.unobserve(el);
        _observed.delete(el);
    };
}

/** Test-only — reset the dedupe map between cases. */
export function _resetWarmedRecentlyForTest(): void {
    warmedRecently.clear();
}
