/**
 * Timestamps tab — animation view: reveal-mode engine, granularity switching,
 * DOM building, and per-frame animation update.
 */

import { state, dom } from './state.js';
import {
    DAGGER_ALEF, ZWSP,
    isCombiningMark, charsMatch, splitIntoCharGroups,
} from '../shared/arabic-text.js';
import { LS_KEYS } from '../shared/constants.js';
import { getSegRelTime } from './index.js';
import { updateDisplay } from './playback.js';

// NOTE: circular dependency with index.js (getSegRelTime) and playback.js
// (updateDisplay for word click handlers). Safe because these functions are
// only called at runtime, long after all module-level code has executed.

// ---------------------------------------------------------------------------
// Animation view: Reveal-mode engine
// ---------------------------------------------------------------------------

/** Build animation display DOM from words array. */
export function buildAnimationDisplay() {
    dom.animDisplay.innerHTML = '';
    if (!state.words.length) return;

    let groupIdCounter = 0;

    state.words.forEach((word, wi) => {
        if (wi > 0) {
            // Space between words for natural Arabic line wrapping
            dom.animDisplay.appendChild(document.createTextNode(' '));
        }

        const wordSpan = document.createElement('span');
        wordSpan.className = 'anim-word';
        wordSpan.dataset.start = word.start;
        wordSpan.dataset.end = word.end;
        wordSpan.dataset.pos = word.location;

        const displayText = word.display_text || word.text;
        const charGroups = splitIntoCharGroups(displayText);
        const letters = word.letters || [];

        // Build char spans with ZWSP pre-processing for dagger alif
        const charSpans = charGroups.map(group => {
            const charSpan = document.createElement('span');
            charSpan.className = 'anim-char';
            charSpan.textContent = group.startsWith(DAGGER_ALEF) ? ZWSP + group : group;
            charSpan.dataset.groupId = `g${groupIdCounter++}`;
            wordSpan.appendChild(charSpan);
            return { el: charSpan, text: group };
        });

        // Fuzzy two-pointer: walk display chars + MFA letters simultaneously
        let mfaIdx = 0;
        const stamped = new Set();
        for (let di = 0; di < charSpans.length; di++) {
            if (stamped.has(di)) continue;
            const displayChar = charSpans[di].text;
            if (mfaIdx < letters.length) {
                const mfaChar = letters[mfaIdx].char || '';
                if (charsMatch(mfaChar, displayChar)) {
                    const lt = letters[mfaIdx];
                    const start = (lt.start != null) ? lt.start : word.start;
                    const end = (lt.end != null) ? lt.end : word.end;
                    charSpans[di].el.dataset.start = start;
                    charSpans[di].el.dataset.end = end;

                    // Peek ahead: combining-mark-only groups that belong to same MFA letter
                    const mfaNfd = mfaChar.normalize('NFD');
                    let peek = di + 1;
                    while (peek < charSpans.length) {
                        const peekText = charSpans[peek].text.replace(/\u0640/g, '');
                        if (!peekText || ![...peekText].every(c => isCombiningMark(c.codePointAt(0))))
                            break;
                        if (![...peekText].some(c => mfaNfd.includes(c)))
                            break;
                        charSpans[peek].el.dataset.start = start;
                        charSpans[peek].el.dataset.end = end;
                        stamped.add(peek);
                        peek++;
                    }
                    mfaIdx++;
                } else {
                    // No match -- use word timing as fallback
                    charSpans[di].el.dataset.start = word.start;
                    charSpans[di].el.dataset.end = word.end;
                }
            } else {
                // Exhausted MFA letters -- use word timing
                charSpans[di].el.dataset.start = word.start;
                charSpans[di].el.dataset.end = word.end;
            }
        }

        // If no char groups (empty display text), still create the word span
        if (!charGroups.length) {
            wordSpan.textContent = displayText;
        }

        // Click to seek
        wordSpan.addEventListener('click', () => {
            dom.audio.currentTime = word.start + state.tsSegOffset;
            updateDisplay();
        });

        dom.animDisplay.appendChild(wordSpan);
    });

    // Merge group IDs for chars with identical start+end across ALL words
    const allChars = dom.animDisplay.querySelectorAll('.anim-char');
    const timingMap = {};  // "start|end" -> groupId
    allChars.forEach(ch => {
        const key = `${ch.dataset.start}|${ch.dataset.end}`;
        if (timingMap[key]) {
            ch.dataset.groupId = timingMap[key];
        } else {
            timingMap[key] = ch.dataset.groupId;
        }
    });
}

/** Build animation cache from container elements. */
export function initAnimCache(container, selector) {
    const elements = Array.from(container.querySelectorAll(selector));
    const cache = elements.map((el, idx) => ({
        el,
        start: parseFloat(el.dataset.start),
        end: parseFloat(el.dataset.end),
        groupId: el.dataset.groupId || null,
        cacheIdx: idx,
    }));
    // Build group index: groupId -> [cacheIdx, ...]
    const groupIndex = {};
    cache.forEach(item => {
        if (item.groupId) {
            if (!groupIndex[item.groupId]) groupIndex[item.groupId] = [];
            groupIndex[item.groupId].push(item.cacheIdx);
        }
    });
    cache._groupIndex = groupIndex;
    return cache;
}

/** Apply class to element and all members of its group. */
export function applyAnimClass(cache, idx, className, add) {
    const item = cache[idx];
    if (!item) return;
    if (add) item.el.classList.add(className);
    else item.el.classList.remove(className);

    if (item.groupId && cache._groupIndex) {
        const members = cache._groupIndex[item.groupId] || [];
        members.forEach(mi => {
            if (mi !== idx) {
                if (add) cache[mi].el.classList.add(className);
                else cache[mi].el.classList.remove(className);
            }
        });
    }
}

/** Apply opacity to element and all members of its group. */
export function applyAnimOpacity(cache, idx, opacity) {
    const item = cache[idx];
    if (!item) return;
    if (opacity === null) item.el.style.removeProperty('opacity');
    else item.el.style.opacity = opacity;

    if (item.groupId && cache._groupIndex) {
        const members = cache._groupIndex[item.groupId] || [];
        members.forEach(mi => {
            if (mi !== idx) {
                if (opacity === null) cache[mi].el.style.removeProperty('opacity');
                else cache[mi].el.style.opacity = opacity;
            }
        });
    }
}

/**
 * Apply Reveal-mode opacity: all previous visible, active highlighted, future hidden.
 * Simplified from animation-core.js applyWindowOpacity().
 */
export function applyRevealOpacity(cache, newIdx, prevIdx) {
    if (!cache || cache.length === 0) return;

    // Fast path: advancing by 1
    if (prevIdx >= 0 && newIdx === prevIdx + 1) {
        // Previous word becomes fully visible
        applyAnimOpacity(cache, prevIdx, '1');
        // New active: clear opacity (CSS .active handles it)
        applyAnimOpacity(cache, newIdx, null);
        return;
    }

    // Full recompute
    for (let i = 0; i < cache.length; i++) {
        if (i < newIdx) {
            applyAnimOpacity(cache, i, '1');  // Previous: visible
        } else if (i === newIdx) {
            applyAnimOpacity(cache, i, null);  // Active: CSS handles
        } else {
            applyAnimOpacity(cache, i, '0');  // Future: hidden
        }
    }

    // Reconcile group opacities
    if (cache._groupIndex) {
        for (const gid of Object.keys(cache._groupIndex)) {
            const members = cache._groupIndex[gid];
            if (members.length <= 1) continue;
            let anyActive = false;
            let maxOp = -1;
            for (const mi of members) {
                if (cache[mi].el.classList.contains('active')) { anyActive = true; break; }
                const op = cache[mi].el.style.opacity;
                if (op !== '') {
                    const val = parseFloat(op);
                    if (!isNaN(val) && val > maxOp) maxOp = val;
                }
            }
            if (anyActive) {
                members.forEach(mi => { cache[mi].el.style.opacity = '1'; });
            } else if (maxOp > 0) {
                const s = String(maxOp);
                members.forEach(mi => { cache[mi].el.style.opacity = s; });
            }
        }
    }
}

/** Update animation display at the given segment-relative time. */
export function updateAnimationDisplay(time) {
    const cache = state.tsGranularity === 'characters' ? state.animCharCache : state.animWordCache;
    if (!cache || cache.length === 0) return;

    // Fast-path tick: check current -> next -> full scan
    let newIdx = -1;
    if (state.lastAnimIdx >= 0 && state.lastAnimIdx < cache.length &&
        time >= cache[state.lastAnimIdx].start && time < cache[state.lastAnimIdx].end) {
        newIdx = state.lastAnimIdx;
    } else if (state.lastAnimIdx + 1 < cache.length &&
        time >= cache[state.lastAnimIdx + 1].start && time < cache[state.lastAnimIdx + 1].end) {
        newIdx = state.lastAnimIdx + 1;
    } else {
        for (let i = 0; i < cache.length; i++) {
            if (time >= cache[i].start && time < cache[i].end) {
                newIdx = i;
                break;
            }
        }
        // Clamp to last when past its end
        if (newIdx === -1 && cache.length > 0 && time >= cache[cache.length - 1].start) {
            newIdx = cache.length - 1;
        }
    }

    if (newIdx !== state.lastAnimIdx) {
        // Remove active from old
        if (state.lastAnimIdx >= 0 && state.lastAnimIdx < cache.length) {
            applyAnimClass(cache, state.lastAnimIdx, 'active', false);
            applyAnimClass(cache, state.lastAnimIdx, 'reached', true);
        }
        // Add active to new
        if (newIdx >= 0) {
            applyAnimClass(cache, newIdx, 'active', true);
            // First highlight: catch up skipped elements
            if (state.lastAnimIdx === -1) {
                for (let j = 0; j < newIdx; j++) {
                    applyAnimClass(cache, j, 'reached', true);
                }
            }
            applyRevealOpacity(cache, newIdx, state.lastAnimIdx);

            // Scroll active element into view
            cache[newIdx].el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        state.lastAnimIdx = newIdx;
    }
}

/** Switch between analysis and animation views. */
export function switchView(mode) {
    state.tsViewMode = mode;
    localStorage.setItem(LS_KEYS.TS_VIEW_MODE, mode);
    dom.unifiedDisplay.style.display = (mode === 'animation') ? 'none' : '';
    dom.animDisplay.hidden = (mode === 'analysis');

    if (mode === 'analysis') {
        // Reset to analysis defaults: Letters on, Phonemes off
        dom.modeBtnA.textContent = 'Letters';
        dom.modeBtnB.textContent = 'Phonemes';
        state.tsShowLetters = true;
        state.tsShowPhonemes = false;
        dom.modeBtnA.classList.add('active');
        dom.modeBtnB.classList.remove('active');
        dom.unifiedDisplay.querySelectorAll('.mega-letters').forEach(el => el.classList.remove('hidden'));
        dom.unifiedDisplay.querySelectorAll('.mega-phonemes').forEach(el => el.classList.add('hidden'));
        dom.unifiedDisplay.querySelectorAll('.crossword-bridge').forEach(el => el.classList.add('hidden'));
    } else {
        // Animation defaults: Labels = Words / Characters, Words active only
        dom.modeBtnA.textContent = 'Words';
        dom.modeBtnB.textContent = 'Letters';
        state.tsGranularity = 'words';
        dom.modeBtnA.classList.add('active');
        dom.modeBtnB.classList.remove('active');
    }

    if (mode === 'animation' && state.words.length) {
        rebuildAnimationView();
        updateAnimationDisplay(getSegRelTime());
    }
}

/** Rebuild animation view DOM and caches. */
export function rebuildAnimationView() {
    buildAnimationDisplay();
    state.animWordCache = initAnimCache(dom.animDisplay, '.anim-word');
    state.animCharCache = initAnimCache(dom.animDisplay, '.anim-char');
    state.lastAnimIdx = -1;
    dom.animDisplay.classList.toggle('anim-chars', state.tsGranularity === 'characters');
}

/** Switch between word and character granularity. */
export function switchGranularity(gran) {
    state.tsGranularity = gran;
    if (state.tsViewMode === 'animation') localStorage.setItem(LS_KEYS.TS_GRANULARITY, gran);
    // Clear all highlights
    dom.animDisplay.querySelectorAll('.anim-word, .anim-char').forEach(el => {
        el.classList.remove('active', 'reached');
        el.style.removeProperty('opacity');
    });
    // Toggle anim-chars class
    dom.animDisplay.classList.toggle('anim-chars', gran === 'characters');
    state.lastAnimIdx = -1;
    // Reapply at current position
    updateAnimationDisplay(getSegRelTime());
}
