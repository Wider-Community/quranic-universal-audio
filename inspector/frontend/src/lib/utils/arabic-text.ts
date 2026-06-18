/**
 * Shared Arabic text utilities — tashkeel stripping, character grouping,
 * letter-equivalence helpers shared across timestamps and animation tabs.
 */

export const TASHKEEL = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED\u08F0-\u08F2]/g;

export const ZWSP = '\u2060';        // Word Joiner
export const DAGGER_ALEF = '\u0670'; // Superscript Alef
export const CHAR_EQUIVALENTS = new Map<string, string>([
    ['\u0649', '\u064A'],  // Alef Maksura -> Yaa
    ['\u064A', '\u0649'],  // Yaa -> Alef Maksura
]);

export function stripTashkeel(text: string): string {
    return text.replace(TASHKEEL, '');
}

/** Check if codepoint is a Unicode combining mark (category M). */
export function isCombiningMark(cp: number): boolean {
    if (cp >= 0x0300 && cp <= 0x036F) return true;
    if (cp >= 0x0610 && cp <= 0x061A) return true;
    if (cp >= 0x064B && cp <= 0x065F) return true;
    if (cp === 0x0670) return true;
    if (cp >= 0x06D6 && cp <= 0x06DC) return true;
    if (cp >= 0x06DF && cp <= 0x06E4) return true;
    if (cp >= 0x06E7 && cp <= 0x06E8) return true;
    if (cp >= 0x06EA && cp <= 0x06ED) return true;
    if (cp >= 0x08D3 && cp <= 0x08FF) return true;
    if (cp >= 0xFE20 && cp <= 0xFE2F) return true;
    return false;
}

/** Extract first non-combining base character after NFD normalization. */
export function firstBase(s: string): string {
    const nfd = s.normalize('NFD');
    for (const ch of nfd) {
        const cp = ch.codePointAt(0);
        if (cp !== undefined && !isCombiningMark(cp)) return ch;
    }
    return s[0] || '';
}

/** Fuzzy match between an MFA letter char and a display char group. */
export function charsMatch(mfaChar: string, displayChar: string): boolean {
    const stripped = displayChar.replace(/\u0640/g, '');
    if (mfaChar === stripped || stripped.includes(mfaChar) || mfaChar.includes(stripped))
        return true;
    if (CHAR_EQUIVALENTS.get(mfaChar) === stripped)
        return true;
    const mb = firstBase(mfaChar), db = firstBase(stripped);
    if (mb && db && (mb === db || CHAR_EQUIVALENTS.get(mb) === db))
        return true;
    return false;
}

/**
 * "Small-letter" combining marks — combining codepoints that nonetheless carry
 * their OWN MFA timing (they are letters in the published alphabet), so each must
 * start its own grapheme cell to highlight independently rather than ride a base.
 * Small hamza (U+0654), hamza below (U+0655), dagger alef (U+0670), and the
 * superscript small letters waw / yeh / yaa / noon (U+06E5–U+06E8).
 */
export const SMALL_LETTER_MARKS = new Set([
    0x0654, 0x0655, 0x0670, 0x06e5, 0x06e6, 0x06e7, 0x06e8,
]);

/**
 * Split text into character groups (base char + combining marks).
 * Port of quranic_universal_aligner/src/ui/segments.py:split_into_char_groups().
 *
 * A {@link SMALL_LETTER_MARKS} mark starts its own group (it is independently
 * timed); every other combining mark rides the current base; tatweel and the
 * word joiner absorb into the current group.
 */
export function splitIntoCharGroups(text: string): string[] {
    const groups: string[] = [];
    let current = '';
    for (const ch of text) {
        const cp = ch.codePointAt(0);
        if (cp === undefined) continue;
        if (cp === 0x0640 || cp === 0x2060) {
            current += ch;
        } else if (SMALL_LETTER_MARKS.has(cp)) {
            if (current) groups.push(current);
            current = ch;
        } else if (isCombiningMark(cp)) {
            current += ch;
        } else {
            if (current) groups.push(current);
            current = ch;
        }
    }
    if (current) groups.push(current);
    return groups;
}

/** Arabic-Indic digits ٠..٩ (U+0660–U+0669); index = Western digit value. */
export const ARABIC_DIGITS: readonly string[] = [
    '٠', '١', '٢', '٣', '٤',
    '٥', '٦', '٧', '٨', '٩',
];

/** Convert a non-negative integer to Arabic-Indic numerals (e.g. 12 → ١٢).
 *  Mirrors `tabs/segments/utils/data/references.ts::_toArabicNumeral`; lives
 *  here so the shared recitation-animation lib stays free of `tabs/*` imports. */
export function toArabicNumeral(n: number): string {
    return String(n)
        .split('')
        .map((d) => ARABIC_DIGITS[+d] ?? d)
        .join('');
}
