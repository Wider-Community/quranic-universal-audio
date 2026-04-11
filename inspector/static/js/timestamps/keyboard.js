/**
 * Timestamps tab — keyboard shortcut handler.
 */

import { state, dom } from './state.js';
import { LS_KEYS } from '../shared/constants.js';
import { getActiveTab } from '../main.js';
import { getSegRelTime } from './index.js';
import { loadRandomTimestamp } from './index.js';
import { updateDisplay } from './playback.js';
import { navigateVerse } from './playback.js';
import { switchView } from './animation.js';

// NOTE: circular dependency with index.js (getSegRelTime, loadRandomTimestamp).
// Safe because this function is only called at runtime via keydown events,
// long after all module-level code has executed.

export function handleKeydown(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (getActiveTab() !== 'timestamps') return;

    switch (e.code) {
        case 'Space':
            e.preventDefault();
            if (dom.audio.paused) {
                // If at/past segment end, restart from segment start
                if (state.tsSegEnd > 0 && dom.audio.currentTime >= state.tsSegEnd) {
                    dom.audio.currentTime = state.tsSegOffset;
                }
                dom.audio.play();
            } else {
                dom.audio.pause();
            }
            break;

        case 'ArrowLeft':
            e.preventDefault();
            dom.audio.currentTime = Math.max(state.tsSegOffset, dom.audio.currentTime - 3);
            updateDisplay();
            break;

        case 'ArrowRight':
            e.preventDefault();
            dom.audio.currentTime = Math.min(state.tsSegEnd || dom.audio.duration, dom.audio.currentTime + 3);
            updateDisplay();
            break;

        case 'ArrowUp': {
            e.preventDefault();
            const time = dom.audio.currentTime - state.tsSegOffset;
            let prevStart = null;
            for (let i = state.words.length - 1; i >= 0; i--) {
                if (state.words[i].start < time - 0.01) {
                    prevStart = state.words[i].start;
                    break;
                }
            }
            if (prevStart !== null) {
                dom.audio.currentTime = prevStart + state.tsSegOffset;
            } else {
                dom.audio.currentTime = state.tsSegOffset;
            }
            updateDisplay();
            break;
        }

        case 'ArrowDown': {
            e.preventDefault();
            const time = dom.audio.currentTime - state.tsSegOffset;
            let nextStart = null;
            for (let i = 0; i < state.words.length; i++) {
                if (state.words[i].start > time + 0.01) {
                    nextStart = state.words[i].start;
                    break;
                }
            }
            if (nextStart !== null) {
                dom.audio.currentTime = nextStart + state.tsSegOffset;
            } else {
                dom.audio.currentTime = state.tsSegEnd || dom.audio.duration;
            }
            updateDisplay();
            break;
        }

        case 'Period': // > speed up
        case 'Comma': { // < speed down
            e.preventDefault();
            const opts = Array.from(dom.tsSpeedSelect.options).map(o => parseFloat(o.value));
            const curRate = parseFloat(dom.tsSpeedSelect.value);
            const curIdx = opts.findIndex(s => Math.abs(s - curRate) < 0.01);
            const idx = curIdx === -1 ? opts.indexOf(1) : curIdx;
            const newIdx = e.code === 'Period'
                ? Math.min(idx + 1, opts.length - 1)
                : Math.max(idx - 1, 0);
            dom.tsSpeedSelect.value = opts[newIdx];
            dom.audio.playbackRate = opts[newIdx];
            localStorage.setItem(LS_KEYS.TS_SPEED, dom.tsSpeedSelect.value);
            break;
        }

        case 'KeyJ': {
            e.preventDefault();
            if (state.tsViewMode === 'animation') {
                const cache = state.tsGranularity === 'characters' ? state.animCharCache : state.animWordCache;
                if (cache && state.lastAnimIdx >= 0 && state.lastAnimIdx < cache.length) {
                    cache[state.lastAnimIdx].el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            } else {
                const activeBlock = dom.unifiedDisplay.querySelector('.mega-block.active');
                if (activeBlock) {
                    activeBlock.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
            break;
        }

        case 'KeyR':
            if (e.shiftKey) {
                loadRandomTimestamp();              // any reciter
            } else {
                loadRandomTimestamp(dom.tsReciterSelect.value || null); // current reciter
            }
            break;

        case 'KeyA': {
            e.preventDefault();
            const newMode = state.tsViewMode === 'analysis' ? 'animation' : 'analysis';
            switchView(newMode);
            document.querySelectorAll('.ts-view-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.view === newMode);
            });
            break;
        }

        case 'KeyL':
            e.preventDefault();
            dom.modeBtnA.click();
            break;

        case 'KeyP':
            e.preventDefault();
            dom.modeBtnB.click();
            break;

        case 'BracketLeft':
            navigateVerse(-1);
            break;

        case 'BracketRight':
            navigateVerse(+1);
            break;
    }
}
