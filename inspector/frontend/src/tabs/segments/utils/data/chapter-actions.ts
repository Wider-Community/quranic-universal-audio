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
            // Hide cold-FUSE / cold-CDN play-click stall by warming a 64 KB
            // Range. Prefer the first seg's byte offset (covers the byte range
            // the audio element will fetch on "play first seg" — byte 0 alone
            // misses if seg[0].time_start nudges the start past 65 KB at high
            // bitrates) and fall back to byte 0 when no segs are loaded yet.
            // No-op for VBR + missing-kbps chapters.
            if (chapterSegs.length > 0) {
                warmSeg(chapterSegs[0], reciter);
            } else {
                warmChapterStart(reciter, chData.audio_url, chNum);
            }
        }
    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}
