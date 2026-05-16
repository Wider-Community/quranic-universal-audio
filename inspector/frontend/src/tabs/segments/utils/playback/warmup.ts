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

import type { Segment } from '../../../../lib/types/domain';
import { cbrKbpsForChapter } from '../../stores/chapter-meta';

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
    if (!seg || !reciter || !seg.audio_url) return;
    const chapter = seg.chapter;
    if (chapter == null) return;
    if (current
        && current.audio_url === seg.audio_url
        && seg.time_start - current.time_end < PROXIMITY_GAP_MS) return;
    const kbps = cbrKbpsForChapter(chapter);
    if (!kbps) return;
    const bytesPerSec = kbps * 125;
    const byteStart = Math.max(0, Math.floor((seg.time_start / 1000) * bytesPerSec));
    _warmAtByte(reciter, seg.audio_url, byteStart);
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

/** Test-only — reset the dedupe map between cases. */
export function _resetWarmedRecentlyForTest(): void {
    warmedRecently.clear();
}
