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
import { segPort } from '../../stores/playback';
import { clearSegPrefetchCache, stopSegAnimation } from '../playback/playback';
import { _fetchChapterPeaksIfNeeded } from '../waveform/utils';
import { _isCurrentReciterBySurah } from './reciter';

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
    segPort.setSource(null);
    stopSegAnimation();
    clearSegPrefetchCache();

    if (!reciter || !chapter) return;

    try {
        const chData = await fetchJson<SegDataResponse>(`/api/seg/data/${reciter}/${chapter}`);
        if (get(selectedReciter) !== reciter || get(selectedChapter) !== chapter) return;
        if (chData.error) return;

        // by_surah reciters need the audio-proxy wrap for CORS so Web Audio
        // can route the chapter MP3 through `MediaElementAudioSourceNode`.
        // Compute it here and pass to the port via `cbrSrc`; the canonical
        // `audioUrl` stays unwrapped so VBR clip-URL building uses it raw.
        const cbrSrc = (_isCurrentReciterBySurah() && chData.audio_url && !chData.audio_url.startsWith('/api/'))
            ? `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(chData.audio_url)}`
            : chData.audio_url;

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
        }
    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}
