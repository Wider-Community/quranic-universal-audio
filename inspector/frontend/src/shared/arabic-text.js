/**
 * Shared Arabic text utilities — used by timestamps tab for cross-word
 * ghunna detection and animation character matching.
 */

export const TASHKEEL = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED\u08F0-\u08F2]/g;

/** Idgham ghunnah phonemes at START of current word -> required Arabic start letter */
export const IDGHAM_GHUNNAH_START = {
    'ñ': '\u0646',  // ن
    'j̃': '\u064A',  // ي
    'w̃': '\u0648',  // و
    'm̃': '\u0645',  // م
};

export const ZWSP = '\u2060';        // Word Joiner
export const DAGGER_ALEF = '\u0670'; // Superscript Alef
export const CHAR_EQUIVALENTS = new Map([
    ['\u0649', '\u064A'],  // Alef Maksura -> Yaa
    ['\u064A', '\u0649'],  // Yaa -> Alef Maksura
]);

export function stripTashkeel(text) {
    return text.replace(TASHKEEL, '');
}

/** Check if codepoint is a Unicode combining mark (category M). */
export function isCombiningMark(cp) {
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
export function firstBase(s) {
    const nfd = s.normalize('NFD');
    for (const ch of nfd) {
        if (!isCombiningMark(ch.codePointAt(0))) return ch;
    }
    return s[0] || '';
}

/** Fuzzy match between an MFA letter char and a display char group. */
export function charsMatch(mfaChar, displayChar) {
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
 * Split text into character groups (base char + combining marks).
 * Port of quranic_universal_aligner/src/ui/segments.py:split_into_char_groups()
 */
export function splitIntoCharGroups(text) {
    const groups = [];
    let current = '';
    for (const ch of text) {
        const cp = ch.codePointAt(0);
        if (cp === 0x0640 || cp === 0x2060) {
            current += ch;
        } else if (cp === 0x0654 || cp === 0x0655) {
            if (current) groups.push(current);
            current = ch;
        } else if (isCombiningMark(cp) && cp !== 0x0670) {
            current += ch;
        } else {
            if (current) groups.push(current);
            current = ch;
        }
    }
    if (current) groups.push(current);
    return groups;
}
