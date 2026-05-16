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
        chData.segments = chapterSegs;
        segData.set(chData);
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
            // Bind the logical source to the port. CBR plays don't actually
            // load `<audio>.src` until the first `loadCovering` (port owns
            // that). VBR clips swap src per-segment via the same path.
            segPort.setSource({
                audioUrl: chData.audio_url,
                cbrSrc,
                reciter,
                vbr: !!chData.vbr,
            });
            // Pre-warm the audio element so its `el.src = url; el.load()`
            // canplay event fires BEFORE the user clicks play. Without this,
            // the first-seg play click visibly stalls while the browser
            // fetches metadata + parses MP3 header + decoder warms; with it,
            // the eventual `loadCovering` short-circuits (fast-path 1) and
            // the play feels as instant as the "seg N → N+1" case.
            //
            // VBR is a different story — clip URLs are per-segment so a
            // chapter-level prewarm is wrong. For VBR we still need the
            // server-side OS page-cache warmup, since the segment-clip route
            // reads from the same chapter file. The byte-Range warmup of
            // seg[0] gets the segment-clip ffmpeg call's first disk read on
            // a warm page cache.
            if (chData.vbr) {
                warmChapterStart(reciter, chData.audio_url, chNum);
                if (chapterSegs.length > 0) {
                    warmSeg(chapterSegs[0], reciter);
                }
            } else {
                segPort.prewarm();
            }
        }
    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}
