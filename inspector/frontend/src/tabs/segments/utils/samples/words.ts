/**
 * Word-level highlight for samples whose upload carried word timings.
 *
 * `tokenizeBody` splits a row's rendered body into whitespace tokens and
 * assigns each Quran word its `surah:ayah:word` location by walking the
 * segment ref the same way the verse-marker inserter does; verse markers get
 * `null`. `activeWordLocation` picks the word under the playhead.
 */

import type { SampleWord } from '../../../../lib/types/generated/schemas';
import type { Ref } from '../../../../lib/types/view-models';
import type { VerseWordCounts } from '../data/references';
import { _normalizeRef, parseSegRef } from '../data/references';

export interface BodyToken {
    text: string;
    location: string | null;
}

const VERSE_MARKER = '۝';
const ARABIC_LETTER = /[؀-ٯ]/;

export function tokenizeBody(
    bodyText: string,
    ref: Ref | null | undefined,
    vwc: VerseWordCounts | undefined,
): BodyToken[] {
    const tokens = bodyText.split(/\s+/).filter(Boolean);
    const p = parseSegRef(_normalizeRef(ref, vwc));
    if (!p) return tokens.map((text) => ({ text, location: null }));
    let ay = p.ayah_from, w = p.word_from;
    return tokens.map((text) => {
        if (text.startsWith(VERSE_MARKER) || !ARABIC_LETTER.test(text)) {
            return { text, location: null };
        }
        const location = `${p.surah}:${ay}:${w}`;
        const total = vwc?.[`${p.surah}:${ay}`] ?? 0;
        if (total > 0 && w >= total) {
            ay++;
            w = 1;
        } else {
            w++;
        }
        return { text, location };
    });
}

/** Location of the word whose span contains `timeMs`, else `null`. */
export function activeWordLocation(words: readonly SampleWord[], timeMs: number): string | null {
    for (const word of words) {
        if (timeMs >= word.start_ms && timeMs < word.end_ms) return word.location;
    }
    return null;
}
