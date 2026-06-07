/**
 * One-call chapter loader for the recitation-animation surfaces.
 *
 * Wraps the shard fetch + per-verse assembly + chapter-absolute rebuild into a
 * single `loadChapterRecitation(reciter, chapter)` that returns the flat
 * `AnimUnit[]` + per-ayah boundaries the line animation and filmstrip consume —
 * or `null` when the reciter/chapter has no timestamps shard (caller hides the
 * section). Keeps the dashboard consumer free of any `tabs/*` import.
 *
 * Each verse's geometry + text come from its canonical occasion, but EVERY
 * occasion's recited span (loopbacks / re-dos) is folded onto the units via
 * `chapterOccasionIntervals` so the recitation locator covers the full chapter
 * audio — the highlight travels back into a re-recited verse instead of freezing
 * on the canonical span while a discarded take plays.
 *
 * Scope guard: `buildChapterRecitation` recovers chapter-absolute word times by
 * adding back each verse's per-verse offset, which is only correct for
 * `by_surah` reciters (one shared chapter file). `by_ayah` reciters have
 * per-verse files whose concatenation offsets aren't known here, so we return
 * `null` for them.
 */

import {
    type AssembledVerse,
    buildChapterRecitation,
} from '../recitation-animation/chapter-words';
import type { AnimUnit, AyahBoundary } from '../recitation-animation/types';
import {
    assembleVerseFromShard,
    chapterOccasionIntervals,
    chapterVerseRefs,
    loadChapterShard,
    loadDk,
    loadManifest,
    loadQpc,
    reciterAudioFromManifest,
} from './ts-source';

export interface ChapterRecitationData {
    units: AnimUnit[];
    ayahs: AyahBoundary[];
    /** Last word end (ms). Informational; surfaces prefer the real audio
     *  duration from the transport when they have it. */
    contentEndMs: number;
}

/**
 * Load + assemble chapter-absolute recitation data for a published reciter.
 * Returns `null` when the reciter isn't in the TS manifest, is `by_ayah`, the
 * shard has no verses, or the fetch is aborted.
 */
export async function loadChapterRecitation(
    reciter: string,
    chapter: number,
    signal?: AbortSignal,
): Promise<ChapterRecitationData | null> {
    if (!reciter || !chapter) return null;

    const manifest = await loadManifest();
    if (signal?.aborted) return null;

    const reciterAudio = reciterAudioFromManifest(manifest, reciter);
    if (!reciterAudio) return null; // reciter not advertised by the TS manifest
    if (reciterAudio.audio_category !== 'by_surah') return null; // see scope guard

    const [shard, qpc, dk] = await Promise.all([
        loadChapterShard(reciter, chapter),
        loadQpc(),
        loadDk(),
    ]);
    if (signal?.aborted) return null;

    // The animation consumes only word/letter timings — `audio_url` is unused
    // here (playback rides the shared player on canonical URLs), so pass "".
    const verses: AssembledVerse[] = [];
    for (const verseRef of chapterVerseRefs(shard)) {
        const data = assembleVerseFromShard(reciter, shard, verseRef, qpc, dk, reciterAudio, '');
        if (data) verses.push({ verseRef, data });
    }
    if (!verses.length) return null;

    // Fold every occasion's recited span (canonical + loopbacks / re-dos) onto
    // the units so the recitation locator covers the full chapter audio — the
    // highlight travels back into a re-recited verse instead of freezing on the
    // canonical-only span while the audio plays a discarded take.
    const occasionIntervals = chapterOccasionIntervals(shard);

    const built = buildChapterRecitation(reciter, chapter, verses, occasionIntervals);
    return { units: built.units, ayahs: built.ayahs, contentEndMs: built.contentEndMs };
}
