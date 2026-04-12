/**
 * Timestamps tab — unified display (analysis view): word blocks, letter rows,
 * phoneme elements, and cross-word bridge detection for ghunna/idgham.
 */

import { state, dom } from './state';
import {
    IDGHAM_GHUNNAH_START,
    stripTashkeel,
} from '../shared/arabic-text';
import { updateDisplay } from './playback';
import type { PhonemeInterval, TsWord } from '../types/domain';

// NOTE: circular dependency with playback.ts (updateDisplay for click handlers).
// Safe because updateDisplay is only called at runtime via event handlers,
// long after all module-level code has executed.

// ---------------------------------------------------------------------------
// Cross-word ghunna detection: letter + phoneme contextual validation
// ---------------------------------------------------------------------------

export function getLastBaseLetter(word: TsWord): string {
    const bare = stripTashkeel(word.text || '');
    return bare.length ? bare[bare.length - 1] ?? '' : '';
}

export function getFirstBaseLetter(word: TsWord): string {
    const bare = stripTashkeel(word.text || '');
    for (const ch of bare) {
        if (ch !== '\u0671' && ch !== '\u0627') return ch;  // skip alef wasla and alef
    }
    return bare.length ? bare[0] ?? '' : '';
}

export function hasTanween(word: TsWord): boolean {
    const text = word.text || '';
    const lastBase = stripTashkeel(text);
    const endsWithAlef = lastBase.length > 0 &&
        (lastBase[lastBase.length - 1] === '\u0627' || lastBase[lastBase.length - 1] === '\u0649');
    if (endsWithAlef) {
        return /[\u064B\u08F0]/.test(text);  // tanween fatha (standard + open) before trailing alef
    }
    const tail = text.slice(-3);
    return /[\u064C\u064D\u08F1\u08F2]/.test(tail);
}

interface BridgeInfo {
    fromPrev: number[];
    fromCurr: number[];
}

export function computeBridgeAtBoundary(prevWord: TsWord, currWord: TsWord): BridgeInfo | null {
    const fromPrev: number[] = [];
    const fromCurr: number[] = [];

    // 1. Prefix of current word: idgham ghunnah phonemes
    const currIndices = currWord.phoneme_indices || [];
    const prevEndsNoon = getLastBaseLetter(prevWord) === '\u0646';
    const prevHasTanween = hasTanween(prevWord);
    const noonOrTanween = prevEndsNoon || prevHasTanween;

    for (const pi of currIndices) {
        const iv = state.intervals[pi];
        const phone = iv?.phone;
        if (!phone) break;
        const requiredLetter = IDGHAM_GHUNNAH_START[phone];
        if (!requiredLetter) break;
        if (noonOrTanween && getFirstBaseLetter(currWord) === requiredLetter) {
            fromCurr.push(pi);
        } else {
            break;  // in-word ghunna (shaddah), not cross-word
        }
    }

    // 2. Suffix of prev word: idgham shafawi (m-tilde when meem sukun before meem)
    const prevIndices = prevWord.phoneme_indices || [];
    if (getLastBaseLetter(prevWord) === '\u0645' &&
        getFirstBaseLetter(currWord) === '\u0645') {
        for (let k = prevIndices.length - 1; k >= 0; k--) {
            const pi = prevIndices[k];
            if (pi === undefined) continue;
            const iv = state.intervals[pi];
            const phone = iv?.phone;
            if (phone === 'm\u0303') {
                fromPrev.push(pi);
            } else {
                break;
            }
        }
        fromPrev.reverse();
    }

    if (fromPrev.length === 0 && fromCurr.length === 0) return null;
    return { fromPrev, fromCurr };
}

export function createCrosswordBridge(bridgeIndices: number[]): HTMLDivElement {
    const bridge = document.createElement('div');
    bridge.className = 'crossword-bridge' + (state.tsShowPhonemes ? '' : ' hidden');

    bridgeIndices.forEach(pi => {
        const interval = state.intervals[pi];
        if (interval && !interval.geminate_end) {
            bridge.appendChild(createPhonemeElement(interval, pi));
        }
    });

    return bridge;
}

// ---------------------------------------------------------------------------
// Unified display building
// ---------------------------------------------------------------------------

export function buildUnifiedDisplay(): void {
    dom.unifiedDisplay.innerHTML = '';

    // Build a map: for each interval, which word owns it
    const intervalToWord = new Array<number>(state.intervals.length).fill(-1);
    state.words.forEach((word, wi) => {
        if (word.phoneme_indices) {
            word.phoneme_indices.forEach(pi => {
                intervalToWord[pi] = wi;
            });
        }
    });

    // Helper to populate cached DOM refs after building display
    function _cacheDisplayRefs(): void {
        state.cachedBlocks = Array.from(dom.unifiedDisplay.querySelectorAll<HTMLElement>('.mega-block'));
        state.cachedPhonemes = Array.from(dom.unifiedDisplay.querySelectorAll<HTMLElement>('.mega-phoneme'));
        state.cachedLetterEls = Array.from(dom.unifiedDisplay.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)'));
        state.prevActiveWordIdx = -1;
        state.prevActivePhonemeIdx = -1;
    }

    // If no words yet, just show phonemes flat
    if (!state.words.length) {
        state.intervals.forEach((interval, index) => {
            if (interval.geminate_end) return;
            const phonEl = createPhonemeElement(interval, index);
            phonEl.classList.add('standalone');
            dom.unifiedDisplay.appendChild(phonEl);
        });
        _cacheDisplayRefs();
        return;
    }

    // If no intervals (phones), render words directly
    if (!state.intervals.length && state.words.length) {
        state.words.forEach((word, wi) => {
            const block = document.createElement('div');
            block.className = 'mega-block';
            block.dataset.wordIndex = String(wi);

            const wordEl = document.createElement('div');
            wordEl.className = 'mega-word';
            wordEl.dir = 'rtl';
            wordEl.textContent = word.display_text || word.text;
            block.appendChild(wordEl);

            const letterRow = createLetterRow(word);
            if (letterRow) block.appendChild(letterRow);

            block.addEventListener('click', () => {
                dom.audio.currentTime = word.start + state.tsSegOffset;
                updateDisplay();
            });

            dom.unifiedDisplay.appendChild(block);
        });
        _cacheDisplayRefs();
        return;
    }

    // Pre-compute bridges for all word boundaries
    const bridges: Array<BridgeInfo | null | undefined> = [];
    for (let wi = 1; wi < state.words.length; wi++) {
        const prev = state.words[wi - 1];
        const curr = state.words[wi];
        bridges[wi] = (prev && curr) ? computeBridgeAtBoundary(prev, curr) : null;
    }

    // Collect all phoneme indices to exclude per word (moved to bridges)
    const excludeFromWord: Set<number>[] = state.words.map(() => new Set<number>());
    for (let wi = 1; wi < state.words.length; wi++) {
        const b = bridges[wi];
        if (!b) continue;
        const exPrev = excludeFromWord[wi - 1];
        const exCurr = excludeFromWord[wi];
        if (exPrev) b.fromPrev.forEach(pi => exPrev.add(pi));
        if (exCurr) b.fromCurr.forEach(pi => exCurr.add(pi));
    }

    // Walk through intervals, grouping by word
    let i = 0;
    const renderedWords = new Set<number>();
    while (i < state.intervals.length) {
        const wi = intervalToWord[i] ?? -1;

        if (wi === -1) {
            i++;
            continue;
        }

        if (renderedWords.has(wi)) {
            i++;
            continue;
        }
        renderedWords.add(wi);

        const word = state.words[wi];
        if (!word) { i++; continue; }

        // Render bridge BEFORE this word's block (if any)
        const b = bridges[wi];
        if (wi > 0 && b) {
            const allBridgeIndices = [...b.fromPrev, ...b.fromCurr];
            if (allBridgeIndices.length > 0) {
                dom.unifiedDisplay.appendChild(createCrosswordBridge(allBridgeIndices));
            }
        }

        // Build mega-block
        const block = document.createElement('div');
        block.className = 'mega-block';
        block.dataset.wordIndex = String(wi);

        const wordEl = document.createElement('div');
        wordEl.className = 'mega-word';
        wordEl.dir = 'rtl';
        wordEl.textContent = word.display_text || word.text;
        block.appendChild(wordEl);

        const letterRow = createLetterRow(word);
        if (letterRow) block.appendChild(letterRow);

        // Phoneme row -- exclude phonemes moved to bridges
        const phoneRow = document.createElement('div');
        phoneRow.className = 'mega-phonemes' + (state.tsShowPhonemes ? '' : ' hidden');

        const indices = word.phoneme_indices || [];
        const excluded = excludeFromWord[wi] ?? new Set<number>();
        indices.forEach(pi => {
            if (excluded.has(pi)) return;
            const interval = state.intervals[pi];
            if (interval && !interval.geminate_end) {
                phoneRow.appendChild(createPhonemeElement(interval, pi));
            }
        });

        block.appendChild(phoneRow);

        block.addEventListener('click', () => {
            dom.audio.currentTime = word.start + state.tsSegOffset;
            updateDisplay();
        });

        dom.unifiedDisplay.appendChild(block);

        while (i < state.intervals.length && intervalToWord[i] === wi) {
            i++;
        }
    }

    _cacheDisplayRefs();
}

export function createPhonemeElement(interval: PhonemeInterval, index: number): HTMLSpanElement {
    const el = document.createElement('span');
    el.className = 'mega-phoneme';
    el.dataset.index = String(index);

    const phone = interval.phone;

    if (!phone || phone === '' || phone === 'sil' || phone === 'sp') {
        el.classList.add('silence');
        el.textContent = phone || '(sil)';
    } else {
        el.textContent = phone;
        if (interval.geminate_start) {
            el.classList.add('geminate');
        }
    }

    el.addEventListener('click', (e) => {
        e.stopPropagation();
        dom.audio.currentTime = interval.start + state.tsSegOffset;
        updateDisplay();
    });

    return el;
}

interface LetterGroup {
    chars: string;
    start: number | null;
    end: number | null;
    isNull: boolean;
}

export function createLetterRow(word: TsWord): HTMLDivElement | null {
    const letters = word.letters || [];
    if (!letters.length) return null;

    const row = document.createElement('div');
    row.className = 'mega-letters' + (state.tsShowLetters ? '' : ' hidden');

    // Group consecutive letters with identical (start, end) into one box
    const groups: LetterGroup[] = [];
    for (const letter of letters) {
        const isNull = letter.start == null || letter.end == null;
        const last = groups[groups.length - 1];
        if (!isNull && last && !last.isNull
            && last.start === letter.start && last.end === letter.end) {
            last.chars += letter.char;
        } else {
            groups.push({ chars: letter.char, start: letter.start,
                          end: letter.end, isNull });
        }
    }

    groups.forEach(group => {
        const el = document.createElement('span');
        el.className = 'mega-letter';
        el.textContent = group.chars;
        if (group.isNull) {
            el.classList.add('null-ts');
            el.addEventListener('click', e => e.stopPropagation());
        } else {
            el.dataset.letterStart = String(group.start);
            el.dataset.letterEnd = String(group.end);
            el.addEventListener('click', e => {
                e.stopPropagation();
                dom.audio.currentTime = (group.start ?? 0) + state.tsSegOffset;
                updateDisplay();
            });
        }
        row.appendChild(el);
    });

    return row;
}

/**
 * Clear and rebuild phoneme labels strip below the waveform.
 * NOT dead code -- called from loadedmetadata handler and on verse load.
 */
export function buildPhonemeLabels(): void {
    dom.phonemeLabels.innerHTML = '';
    state.cachedLabels = [];
}
