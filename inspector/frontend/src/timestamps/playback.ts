// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Timestamps tab — playback control: audio loading, navigation, animation
 * loop, and per-frame display update (highlighting, canvas playhead).
 */

import { state, dom } from './state';
import { getSegRelTime, getSegDuration, onTsVerseChange } from './index';
import { drawVisualizationWithPlayhead } from './waveform';
import { updateAnimationDisplay } from './animation';

// NOTE: circular dependencies with index.js (getSegRelTime, getSegDuration,
// onTsVerseChange) and animation.js (updateAnimationDisplay). Safe because
// ES modules guarantee all module-level code runs before any cross-module
// function calls occur — these are only called at runtime via event handlers.

/**
 * Clean up any pending loadedmetadata listener and load+play the given audio URL.
 * Handles: empty URLs, same-source seeks, new source loads, autoplay rejection.
 */
export function _loadAudioAndPlay(url) {
    // Remove stale listener from previous load
    if (state._currentOnMeta) {
        dom.audio.removeEventListener('loadedmetadata', state._currentOnMeta);
        state._currentOnMeta = null;
    }

    if (!url) {
        dom.audio.removeAttribute('src');
        dom.audio.load();
        return;
    }

    const isSameSource = dom.audio.src === url || dom.audio.src === location.origin + url;

    if (!isSameSource) {
        const onMeta = function() {
            dom.audio.removeEventListener('loadedmetadata', onMeta);
            if (state._currentOnMeta === onMeta) state._currentOnMeta = null;
            dom.audio.currentTime = state.tsSegOffset;
            state.tsAutoAdvancing = false;
            dom.audio.play().catch(() => {});
        };
        state._currentOnMeta = onMeta;
        dom.audio.src = url;
        dom.audio.addEventListener('loadedmetadata', onMeta);
    } else {
        dom.audio.currentTime = state.tsSegOffset;
        state.tsAutoAdvancing = false;
        dom.audio.play().catch(() => {});
    }
}

export function navigateVerse(delta) {
    const newIdx = dom.tsSegmentSelect.selectedIndex + delta;
    if (newIdx < 1 || newIdx >= dom.tsSegmentSelect.options.length) {
        state.tsAutoAdvancing = false;
        return;
    }
    dom.tsSegmentSelect.selectedIndex = newIdx;
    onTsVerseChange();
}

export function toggleAutoMode(mode) {
    if (state.tsAutoMode === mode) {
        state.tsAutoMode = null;
    } else {
        state.tsAutoMode = mode;
    }
    dom.autoNextBtn.classList.toggle('active', state.tsAutoMode === 'next');
    dom.autoRandomBtn.classList.toggle('active', state.tsAutoMode === 'random');
}

// ---------------------------------------------------------------------------
// Animation loop
// ---------------------------------------------------------------------------

export function startAnimation() {
    animate();
}

export function stopAnimation() {
    if (state.animationId) {
        cancelAnimationFrame(state.animationId);
        state.animationId = null;
    }
}

export function animate() {
    updateDisplay();
    state.animationId = requestAnimationFrame(animate);
}

// ---------------------------------------------------------------------------
// Per-frame display update
// ---------------------------------------------------------------------------

export function updateDisplay() {
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Update animation view if active
    if (state.tsViewMode === 'animation') {
        updateAnimationDisplay(time);
    }

    // Find current phoneme
    let currentIndex = -1;
    for (let i = 0; i < state.intervals.length; i++) {
        if (time >= state.intervals[i].start && time < state.intervals[i].end) {
            if (state.intervals[i].geminate_end) {
                currentIndex = i - 1;
            } else {
                currentIndex = i;
            }
            break;
        }
    }

    // Find current word
    let currentWordIndex = -1;
    for (let i = 0; i < state.words.length; i++) {
        if (time >= state.words[i].start && time < state.words[i].end) {
            currentWordIndex = i;
            break;
        }
    }

    // Update unified display highlighting -- use cached refs, diff-only updates
    if (currentWordIndex !== state.prevActiveWordIdx) {
        for (const block of state.cachedBlocks) {
            const wi = parseInt(block.dataset.wordIndex);
            block.classList.remove('active', 'past');
            if (wi === currentWordIndex) {
                block.classList.add('active');
                block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else if (currentWordIndex >= 0 && wi < currentWordIndex) {
                block.classList.add('past');
            }
        }
        state.prevActiveWordIdx = currentWordIndex;
    }

    // Update individual phoneme highlighting -- only on change
    if (currentIndex !== state.prevActivePhonemeIdx) {
        for (const ph of state.cachedPhonemes) {
            ph.classList.toggle('active', parseInt(ph.dataset.index) === currentIndex);
        }
        state.cachedLabels.forEach((label, i) => {
            label.classList.toggle('active', i === currentIndex);
        });
        state.prevActivePhonemeIdx = currentIndex;
    }

    // Update letter highlighting (time-based, must check each frame)
    for (const el of state.cachedLetterEls) {
        const s = parseFloat(el.dataset.letterStart);
        const e = parseFloat(el.dataset.letterEnd);
        el.classList.toggle('active', time >= s && time < e);
    }

    // Redraw canvas with playhead
    drawVisualizationWithPlayhead(time / duration);
}
