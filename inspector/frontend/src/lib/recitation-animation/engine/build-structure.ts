/**
 * Pure structure builder — extracted verbatim from the timestamps-tab
 * `AnimationDisplay.buildStructure()` so the same char-grouping + MFA
 * letter-alignment + cross-word group-ID merge logic drives every animation
 * surface. No Svelte / store dependency.
 *
 * Output `AnimWord[]` is rendered declaratively; per-frame highlight updates
 * are applied imperatively via `engine/highlight.ts`.
 */

import {
    charsMatch,
    DAGGER_ALEF,
    isCombiningMark,
    splitIntoCharGroups,
    ZWSP,
} from '../../utils/arabic-text';
import { splitWaqf } from '../../utils/waqf';

/** Minimal word shape the builder needs. Both `TsWord` and `AnimUnit`
 *  (mapped) satisfy it — keeps the builder reusable across surfaces. */
export interface AnimSourceWord {
    text: string;
    display_text: string;
    start: number;
    end: number;
    letters: { char: string; start: number | null; end: number | null }[];
}

export interface AnimChar {
    text: string;
    start: number;
    end: number;
    groupId: string;
}

export interface AnimWord {
    word: AnimSourceWord;
    wordIndex: number;
    start: number;
    end: number;
    /** Display text with any surfaced waqf (stop) mark removed — what the reveal
     *  actually animates. The mark is pulled out to `waqf` so it never takes the
     *  highlight (it lights only on a pause, handled by the surface). */
    clean: string;
    /** The surfaced waqf mark stripped from `clean`, or null. */
    waqf: string | null;
    /** Characters split for character-granularity animation (from `clean`). */
    chars: AnimChar[];
    /** Whether the word has any char groups (empty display_text → render text directly). */
    hasChars: boolean;
}

export function buildAnimStructure(words: AnimSourceWord[]): AnimWord[] {
    if (!words.length) return [];

    let groupIdCounter = 0;
    const out: AnimWord[] = [];

    words.forEach((word, wi) => {
        // Pull any surfaced waqf (stop) mark out before grouping — it's a
        // combining mark riding the last letter and must never join the reveal.
        const { clean, mark } = splitWaqf(word.display_text || word.text);
        const charGroups = splitIntoCharGroups(clean);
        const letters = word.letters || [];

        // Assign initial group IDs.
        const chars: AnimChar[] = charGroups.map((group) => ({
            text: group.startsWith(DAGGER_ALEF) ? ZWSP + group : group,
            start: word.start,
            end: word.end,
            groupId: `g${groupIdCounter++}`,
        }));

        // Fuzzy two-pointer: walk display chars + MFA letters simultaneously.
        let mfaIdx = 0;
        const stamped = new Set<number>();
        for (let di = 0; di < chars.length; di++) {
            if (stamped.has(di)) continue;
            const span = chars[di];
            if (!span) continue;
            const displayChar = span.text.replace(/^\u200B/, ''); // strip ZWSP for matching
            if (mfaIdx < letters.length) {
                const lt = letters[mfaIdx];
                if (!lt) {
                    mfaIdx++;
                    continue;
                }
                const mfaChar = lt.char || '';
                if (charsMatch(mfaChar, displayChar)) {
                    const startSec = lt.start != null ? lt.start : word.start;
                    const endSec = lt.end != null ? lt.end : word.end;
                    span.start = startSec;
                    span.end = endSec;

                    // Peek ahead: combining-mark-only groups for the same MFA letter.
                    const mfaNfd = mfaChar.normalize('NFD');
                    let peek = di + 1;
                    while (peek < chars.length) {
                        const peekSpan = chars[peek];
                        if (!peekSpan) break;
                        const peekText = peekSpan.text.replace(/ـ/g, '');
                        if (
                            !peekText
                            || ![...peekText].every((c) => {
                                const cp = c.codePointAt(0);
                                return cp !== undefined && isCombiningMark(cp);
                            })
                        ) {
                            break;
                        }
                        if (![...peekText].some((c) => mfaNfd.includes(c))) break;
                        peekSpan.start = startSec;
                        peekSpan.end = endSec;
                        stamped.add(peek);
                        peek++;
                    }
                    mfaIdx++;
                }
                // else: no-match path keeps word-level timing (already set).
            }
            // else: exhausted MFA letters → word timing (already set).
        }

        out.push({
            word,
            wordIndex: wi,
            start: word.start,
            end: word.end,
            clean,
            waqf: mark,
            chars,
            hasChars: chars.length > 0,
        });
    });

    // Cross-word group-ID merge: chars sharing identical (start, end) share a
    // group so cross-boundary idgham/ghunna timing highlights together.
    const timingMap: Record<string, string> = {};
    for (const w of out) {
        for (const ch of w.chars) {
            const key = `${ch.start}|${ch.end}`;
            const existing = timingMap[key];
            if (existing) ch.groupId = existing;
            else timingMap[key] = ch.groupId;
        }
    }
    return out;
}
