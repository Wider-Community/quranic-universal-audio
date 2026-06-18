/**
 * Pure structure builder — extracted verbatim from the timestamps-tab
 * `AnimationDisplay.buildStructure()` so the same char-grouping + MFA
 * letter-alignment + cross-word group-ID merge logic drives every animation
 * surface. No Svelte / store dependency.
 *
 * Output `AnimWord[]` is rendered declaratively; per-frame highlight updates
 * are applied imperatively via `engine/highlight.ts`.
 */

import { charsMatch, isCombiningMark, splitIntoCharGroups, ZWSP } from '../../utils/arabic-text';
import { type Decorator, splitDecorators } from '../decorators';

/** Non-recited symbols rendered in place but never highlighted (no MFA letter):
 *  rub-el-hizb (U+06DE) and the place-of-sajdah mark (U+06E9). */
const INERT_SYMBOLS = new Set([0x06de, 0x06e9]);

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
    /** A non-recited symbol (rub-el-hizb, sajdah): rendered in place, never lit. */
    inert: boolean;
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

        // One cell per grapheme cluster (base letter + all its combining marks).
        // A cluster whose base is a non-recited symbol (rub-el-hizb, sajdah) is
        // `inert`: rendered in place but never highlighted, and it takes no MFA
        // letter.
        const chars: AnimChar[] = charGroups.map((group) => {
            const base = group.codePointAt(0);
            // The dagger alef is its own cell — anchor it on an invisible word
            // joiner so the lone superscript shapes into its own run.
            return {
                text: base === 0x0670 ? ZWSP + group : group,
                start: word.start,
                end: word.end,
                groupId: `g${groupIdCounter++}`,
                inert: base !== undefined && INERT_SYMBOLS.has(base),
            };
        });

        // Walk display clusters + MFA letters in order. A matched base cluster
        // folds in the timing of any following combining-mark MFA letters (small
        // hamza, mini-yaa, dagger alef): they ride this base grapheme and share
        // its lit interval - a separate highlight span would detach the mark from
        // its letter.
        let mfaIdx = 0;
        const timed = new Set<number>();
        for (let di = 0; di < chars.length; di++) {
            const span = chars[di];
            if (!span || span.inert) continue;
            while (mfaIdx < letters.length && !letters[mfaIdx]) mfaIdx++;
            if (mfaIdx >= letters.length) break;
            const lt = letters[mfaIdx]!;
            if (!charsMatch(lt.char || '', span.text)) continue; // mismatch -> orphan pass
            span.start = lt.start != null ? lt.start : word.start;
            let endSec = lt.end != null ? lt.end : word.end;
            mfaIdx++;
            while (mfaIdx < letters.length) {
                const nxt = letters[mfaIdx];
                const cp = nxt?.char ? nxt.char.codePointAt(0) : undefined;
                // Stop at the dagger alef — it has its own cell to match it.
                if (cp === undefined || !isCombiningMark(cp) || cp === 0x0670) break;
                if (nxt!.end != null) endSec = nxt!.end;
                mfaIdx++;
            }
            span.end = endSec;
            timed.add(di);
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
