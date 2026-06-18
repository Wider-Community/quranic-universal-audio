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
    isCombiningMark,
    SMALL_LETTER_MARKS,
    splitIntoCharGroups,
    ZWSP,
} from '../../utils/arabic-text';
import { type Decorator, splitDecorators } from '../decorators';

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
    /** Display text with all non-recited decorator marks removed — what the
     *  reveal actually animates. Decorators are pulled out to `leading`/`trailing`
     *  so they never take a highlight cell (see `../decorators`). */
    clean: string;
    /** Non-recited decorators rendered before the word's letters (e.g. rub-el-hizb). */
    leading: Decorator[];
    /** Non-recited decorators rendered after the word's letters (waqf stop, sajdah). */
    trailing: Decorator[];
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
        // Pull all non-recited decorator marks (waqf stops, rub-el-hizb, sajdah)
        // out before grouping — they carry no MFA timing and must never join the
        // reveal as a highlight cell.
        const { clean, leading, trailing } = splitDecorators(word.display_text || word.text);
        const charGroups = splitIntoCharGroups(clean);
        const letters = word.letters || [];

        // Assign initial group IDs. A group that LEADS with a combining mark (a
        // small-letter mark like the dagger alef, small hamza, mini-yaa) can't
        // stand alone — anchor it on an invisible word joiner so it shapes into
        // its own zero-advance run with an independent colour, no dotted circle.
        const chars: AnimChar[] = charGroups.map((group) => {
            const firstCp = group.codePointAt(0);
            const needsJoiner =
                firstCp !== undefined
                && (SMALL_LETTER_MARKS.has(firstCp) || isCombiningMark(firstCp));
            return {
                text: needsJoiner ? ZWSP + group : group,
                start: word.start,
                end: word.end,
                groupId: `g${groupIdCounter++}`,
            };
        });

        // Fuzzy two-pointer: walk display chars + MFA letters simultaneously,
        // recording every cell that receives a real per-letter interval.
        let mfaIdx = 0;
        const timed = new Set<number>();
        for (let di = 0; di < chars.length; di++) {
            if (timed.has(di)) continue;
            const span = chars[di];
            if (!span) continue;
            const displayChar = span.text.replace(/^[\u2060\u200B]/, ''); // strip the joiner
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
                    timed.add(di);

                    // Peek ahead: combining-mark-only groups for the same MFA
                    // letter. A joiner-anchored small-letter cell breaks the run
                    // (the joiner is not combining), so it is matched on its own
                    // MFA letter instead of being absorbed here.
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
                        timed.add(peek);
                        peek++;
                    }
                    mfaIdx++;
                }
                // else: no match — leave this cell for the orphan pass below.
            }
            // else: exhausted MFA letters → orphan pass below.
        }

        // Orphan-timing safety net. A cell the matcher never stamped would keep
        // whole-word timing and stay "active" for the ENTIRE word — lighting in
        // lockstep with the real first letter (the first+last-together artifact).
        // Inherit the nearest stamped neighbour's interval instead, so an orphan
        // lights with the letter it visually rides, never the whole word. If
        // NOTHING was stamped (no MFA letters at all), leave word timing — the
        // whole word lights together, which is correct with no per-letter data.
        if (timed.size > 0) {
            for (let di = 0; di < chars.length; di++) {
                if (timed.has(di)) continue;
                const span = chars[di];
                if (!span) continue;
                let src: AnimChar | null = null;
                for (let p = di - 1; p >= 0 && !src; p--) if (timed.has(p)) src = chars[p]!;
                for (let n = di + 1; n < chars.length && !src; n++) if (timed.has(n)) src = chars[n]!;
                if (src) {
                    span.start = src.start;
                    span.end = src.end;
                }
            }
        }

        out.push({
            word,
            wordIndex: wi,
            start: word.start,
            end: word.end,
            clean,
            leading,
            trailing,
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
