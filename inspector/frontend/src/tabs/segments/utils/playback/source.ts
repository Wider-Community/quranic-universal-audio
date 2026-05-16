/**
 * Per-segment AudioPort source resolution.
 *
 * `loadChapterData` binds `segPort` once per chapter dropdown change. That
 * leaves the port stuck on the active chapter when the user plays an
 * accordion row from a different chapter (validation cards mount rows from
 * any chapter), or when autoplay advances across a multi-chapter displayed
 * slice. The result was wrong audio: VBR clips built from the active
 * chapter's URL with the row's file-absolute timestamps, or CBR plays of
 * the active chapter at the row's offset.
 *
 * This helper resolves a per-row `AudioSource` so every play / edit entry
 * point can call `segPort.setSource(...)` for the seg it's about to play.
 * `setSource` is `_sameSource`-guarded — same-chapter calls are free no-ops,
 * different-source calls invalidate `_window` and abort any pending swap so
 * the next `loadCovering` issues a fresh transport-correct request.
 */

import { get } from 'svelte/store';

import type { AudioSource } from '../../../../lib/playback/audio-port';
import type { Segment } from '../../../../lib/types/domain';
import { reciterVbrChapters, selectedReciter } from '../../stores/chapter';

/** Wrap a cross-origin chapter MP3 URL in the same-origin audio-proxy.
 *  Required when the resulting `<audio>` is routed through Web Audio's
 *  `MediaElementAudioSourceNode` (kill-switch enabled ports) — the CDN
 *  response carries no `Access-Control-Allow-Origin`, so a cross-origin src
 *  on a `crossorigin="anonymous"` element makes the source node output
 *  zeroes. The proxy streams same-origin with `ACAO: *`.
 *
 *  Earlier this gated on `_isCurrentReciterBySurah()` reading
 *  `audio_source.startsWith('by_surah')`, but the actual values served by
 *  `/api/seg/reciters` are channel names (`mp3quran`, `qul`, etc.) — the
 *  check always returned false, so every cross-origin CBR URL went raw to
 *  the audio element and played silently. Switching to a URL-pattern check
 *  is the correct condition: same-origin `/api/...` paths are pass-through;
 *  anything else (http:, https:, protocol-relative) needs the proxy wrap. */
export function wrapCbrSrcIfBySurah(audioUrl: string, reciter: string | null): string {
    if (!reciter || !audioUrl) return audioUrl;
    if (audioUrl.startsWith('/api/')) return audioUrl;
    return `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(audioUrl)}`;
}

/** Resolve the AudioPort source descriptor for a segment.
 *
 *  Mirrors `loadChapterData`'s `setSource(...)` but per-row instead of
 *  per-chapter:
 *  - `audioUrl` is the seg's canonical CDN URL.
 *  - `reciter` is the active reciter — accordion rows are always for the
 *    active reciter (cross-reciter History snapshots stay in their per-panel
 *    preview port and never reach this path).
 *  - `vbr` is read from the per-reciter map keyed on the row chapter, so a
 *    cross-chapter row gets ITS chapter's encoding, not the active one's.
 *  - `cbrSrc` applies the audio-proxy wrap only for `by_surah` reciters
 *    (mirrors `chapter-actions.ts:55-57`).
 *
 *  Returns null when the source can't be resolved (no reciter or empty
 *  audio_url) — callers skip the setSource call in that case. */
export function resolveSegSource(seg: Segment, chapterOverride?: number | null): AudioSource | null {
    const reciter = get(selectedReciter);
    if (!reciter || !seg.audio_url) return null;
    const chapter = chapterOverride ?? seg.chapter ?? 0;
    const vbr = chapter > 0 && (get(reciterVbrChapters)?.has(chapter) ?? false);
    const cbrSrc = wrapCbrSrcIfBySurah(seg.audio_url, reciter);
    return { audioUrl: seg.audio_url, cbrSrc, reciter, vbr };
}
