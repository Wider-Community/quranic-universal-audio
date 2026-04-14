/**
 * Timestamps tab — playback control: audio loading, navigation, animation
 * loop, and per-frame display update (highlighting, canvas playhead).
 */

import { createAnimationLoop } from '../lib/utils/animation';
import { updateAnimationDisplay } from './animation';
import { getSegDuration, getSegRelTime, onTsVerseChange } from './registry';
import { dom,state } from './state';
import { drawVisualizationWithPlayhead } from './waveform';

/**
 * Clean up any pending loadedmetadata listener and load+play the given audio URL.
 * Handles: empty URLs, same-source seeks, new source loads, autoplay rejection.
 */
export function _loadAudioAndPlay(url: string | null | undefined): void {
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
        const onMeta = function(): void {
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

export function navigateVerse(delta: number): void {
    const newIdx = dom.tsSegmentSelect.selectedIndex + delta;
    if (newIdx < 1 || newIdx >= dom.tsSegmentSelect.options.length) {
        state.tsAutoAdvancing = false;
        return;
    }
    dom.tsSegmentSelect.selectedIndex = newIdx;
    onTsVerseChange();
}

export function toggleAutoMode(mode: 'next' | 'random'): void {
    if (state.tsAutoMode === mode) {
        state.tsAutoMode = null;
    } else {
        state.tsAutoMode = mode;
    }
    dom.autoNextBtn.classList.toggle('active', state.tsAutoMode === 'next');
    dom.autoRandomBtn.classList.toggle('active', state.tsAutoMode === 'random');
}

// ---------------------------------------------------------------------------
// Animation loop (wraps shared/animation.ts createAnimationLoop)
// ---------------------------------------------------------------------------

// Behavior preserved verbatim: onFrame calls updateDisplay and returns void so
// the loop continues indefinitely until stopAnimation() cancels the frame.
// `state.animationId` is kept in sync (1 when running, null when stopped) so
// downstream code inspecting it continues to work. Using 1 as a sentinel
// non-null value is safe because no consumer reads the numeric id — they only
// compare truthiness.
const _tsAnimLoop = createAnimationLoop(() => {
    updateDisplay();
});

export function startAnimation(): void {
    _tsAnimLoop.start();
    state.animationId = 1;
}

export function stopAnimation(): void {
    _tsAnimLoop.stop();
    state.animationId = null;
}

/** Exposed for legacy external callers; equivalent to startAnimation(). */
export function animate(): void {
    startAnimation();
}

// ---------------------------------------------------------------------------
// Per-frame display update
// ---------------------------------------------------------------------------

export function updateDisplay(): void {
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Update animation view if active
    if (state.tsViewMode === 'animation') {
        updateAnimationDisplay(time);
    }

    // Find current phoneme
    let currentIndex = -1;
    for (let i = 0; i < state.intervals.length; i++) {
        const iv = state.intervals[i];
        if (!iv) continue;
        if (time >= iv.start && time < iv.end) {
            if (iv.geminate_end) {
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
        const w = state.words[i];
        if (!w) continue;
        if (time >= w.start && time < w.end) {
            currentWordIndex = i;
            break;
        }
    }

    // Update unified display highlighting -- use cached refs, diff-only updates
    if (currentWordIndex !== state.prevActiveWordIdx) {
        for (const block of state.cachedBlocks) {
            const wi = parseInt(block.dataset.wordIndex ?? '-1');
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
            ph.classList.toggle('active', parseInt(ph.dataset.index ?? '-1') === currentIndex);
        }
        state.cachedLabels.forEach((label, i) => {
            label.classList.toggle('active', i === currentIndex);
        });
        state.prevActivePhonemeIdx = currentIndex;
    }

    // Update letter highlighting (time-based, must check each frame)
    for (const el of state.cachedLetterEls) {
        const s = parseFloat(el.dataset.letterStart ?? '0');
        const e = parseFloat(el.dataset.letterEnd ?? '0');
        el.classList.toggle('active', time >= s && time < e);
    }

    // Redraw canvas with playhead
    drawVisualizationWithPlayhead(time / duration);
}
