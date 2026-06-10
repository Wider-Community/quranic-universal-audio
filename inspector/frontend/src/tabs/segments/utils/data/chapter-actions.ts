/**
 * Chapter-level data load action.
 *
 * Shared between SegmentsTab's chapter-change handler and the navigation
 * actions (jumpToSegment etc.) that force a chapter change during their
 * flow.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegDataResponse } from '../../../../lib/types/api';
import type { Segment } from '../../../../lib/types/domain';
import { preconnectOrigins } from '../../../../lib/utils/preconnect';
import type { SegDataState } from '../../stores/chapter';
import {
    reciterVbrChapters,
    segAllData,
    segData,
    selectedChapter,
    selectedReciter,
    selectedVerse,
} from '../../stores/chapter';
import { chapterCbrKbps } from '../../stores/chapter-meta';
import { segPort } from '../../stores/playback';
import { disposeSegRange, stopSegAnimation } from '../playback/playback';
import { wrapCbrSrcIfBySurah } from '../playback/source';
import { warmChapterStart, warmSeg } from '../playback/warmup';
import { _fetchChapterPeaksIfNeeded } from '../waveform/utils';

/**
 * Fetch per-chapter data and update stores + imperative consumers. Handles
 * audio URL rewriting, verse-options derivation (via segData.segments), and
 * peaks prefetch. Does NOT update `selectedChapter` — callers set that
 * before invoking if they are forcing a navigation.
 */
export async function loadChapterData(reciter: string, chapter: string): Promise<void> {
    selectedVerse.set('');

    // Tear down the prior chapter's source. The port pauses any running
    // playback and clears the audio element's src; chapter-src state lives
    // entirely behind the port from here on.
    //
    // Dispose any live AudioRange BEFORE setSource so a stale range whose
    // pending `_startWithPort.then(seekAndPlay)` is still in flight can't
    // fire against the new source after the swap. Without this, a fast
    // reciter / chapter switch mid-cross-chapter-accordion-play would
    // briefly play the new chapter at the old seg's offset.
    disposeSegRange();
    segPort.setSource(null);
    stopSegAnimation();

    if (!reciter || !chapter) return;

    // EAGER PREWARM — start the audio element load BEFORE the chapter-data
    // fetch. The audio URL is already known from `segAllData.audio_by_chapter`
    // (loaded on reciter switch). Setting source + prewarm now starts the
    // browser's fetch + decode + canplay pipeline in parallel with the
    // chapter-data fetch (~300-500 ms), giving the user noticeably more head
    // start before they click play.
    //
    // Skip when we don't yet know audio_url OR the reciter is VBR (clip URL
    // is per-seg, no chapter-level prewarm available). Both fall through to
    // the post-fetch setSource path below.
    const eagerAll = get(segAllData);
    const chNumEager = parseInt(chapter);
    const eagerAudioUrl = eagerAll?.audio_by_chapter?.[String(chNumEager)] ?? '';
    const eagerVbr = (eagerAll?.reciter_vbr_chapters ?? []).includes(chNumEager);
    let eagerPrewarmFired = false;
    if (eagerAudioUrl && !eagerVbr) {
        const eagerCbrSrc = wrapCbrSrcIfBySurah(eagerAudioUrl, reciter);
        segPort.setSource({
            audioUrl: eagerAudioUrl,
            cbrSrc: eagerCbrSrc,
            reciter,
            vbr: false,
        });
        segPort.prewarm();
        eagerPrewarmFired = true;
    }

    try {
        const chData = await fetchJson<SegDataResponse>(`/api/seg/data/${reciter}/${chapter}`);
        if (get(selectedReciter) !== reciter || get(selectedChapter) !== chapter) return;
        if (chData.error) return;

        // by_surah reciters need the audio-proxy wrap for CORS so Web Audio
        // can route the chapter MP3 through `MediaElementAudioSourceNode`.
        // The canonical `audioUrl` stays unwrapped so VBR clip-URL building
        // uses it raw.
        const cbrSrc = wrapCbrSrcIfBySurah(chData.audio_url ?? '', reciter);

        const chNum = parseInt(chapter);
        // Slice segments into the per-chapter list (imperative consumers
        // still read state.segData.segments).
        const all = get(segAllData);
        const chapterSegs: Segment[] = all
            ? all.segments.filter((s) => s.chapter === chNum)
            : [];
        const chState: SegDataState = { ...chData, segments: chapterSegs };
        segData.set(chState);
        reciterVbrChapters.set(new Set(chData.reciter_vbr_chapters ?? []));
        chapterCbrKbps.set(new Map(
            Object.entries(chData.chapter_bitrate_kbps ?? {})
                .map(([k, v]) => [parseInt(k), v] as [number, number])
                .filter(([k]) => Number.isFinite(k)),
        ));
        _fetchChapterPeaksIfNeeded(reciter, chNum);

        if (chData.audio_url) {
            // Re-warm the CDN connection: the reciter-load preconnect may have
            // decayed if the user took >10s to pick a chapter (Chrome abandons
            // idle preconnects). Fire again now, just before binding the source.
            preconnectOrigins(
                Object.values(get(segAllData)?.audio_by_chapter ?? {}),
            );
            // Re-bind only when the audio URL differs from the eager prewarm
            // (rare — eagerAudioUrl came from `segAllData.audio_by_chapter`
            // which the chapter-data response matches in practice). When they
            // agree AND the prewarm already fired, the port's same-source
            // check makes setSource a no-op anyway. The redundant call is
            // harmless and keeps the post-fetch invariant.
            //
            // For VBR we still need the server-side OS page-cache warmup; the
            // segment-clip route reads from the same chapter file, so a
            // byte-Range warmup of seg[0] gets the segment-clip ffmpeg call's
            // first disk read on a warm page cache. Eager prewarm above skipped
            // for VBR — this is where the VBR path actually runs.
            segPort.setSource({
                audioUrl: chData.audio_url,
                cbrSrc,
                reciter,
                vbr: !!chData.vbr,
            });
            if (chData.vbr) {
                warmChapterStart(reciter, chData.audio_url, chNum);
                if (chapterSegs.length > 0) {
                    warmSeg(chapterSegs[0], reciter);
                }
            } else if (!eagerPrewarmFired) {
                // Fallback: eager path skipped (segAllData not loaded yet).
                segPort.prewarm();
            }
        }
    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}
