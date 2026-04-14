/**
 * Timestamps tab — keyboard shortcut handler.
 */

import { safePlay } from '../lib/utils/audio';
import { LS_KEYS } from '../lib/utils/constants';
import { shouldHandleKey } from '../lib/utils/keyboard-guard';
import { cycleSpeed } from '../lib/utils/speed-control';
import { switchView } from './animation';
import { loadRandomTimestamp, navigateVerse, updateDisplay } from './registry';
import { dom,state } from './state';

export function handleKeydown(e: KeyboardEvent): void {
    if (!shouldHandleKey(e, 'timestamps')) return;

    switch (e.code) {
        case 'Space':
            e.preventDefault();
            if (dom.audio.paused) {
                // If at/past segment end, restart from segment start
                if (state.tsSegEnd > 0 && dom.audio.currentTime >= state.tsSegEnd) {
                    dom.audio.currentTime = state.tsSegOffset;
                }
                safePlay(dom.audio);
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
            let prevStart: number | null = null;
            for (let i = state.words.length - 1; i >= 0; i--) {
                const w = state.words[i];
                if (w && w.start < time - 0.01) {
                    prevStart = w.start;
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
            let nextStart: number | null = null;
            for (let i = 0; i < state.words.length; i++) {
                const w = state.words[i];
                if (w && w.start > time + 0.01) {
                    nextStart = w.start;
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
            cycleSpeed(dom.tsSpeedSelect, dom.audio, e.code === 'Period' ? 'up' : 'down', LS_KEYS.TS_SPEED);
            break;
        }

        case 'KeyJ': {
            e.preventDefault();
            if (state.tsViewMode === 'animation') {
                const cache = state.tsGranularity === 'characters' ? state.animCharCache : state.animWordCache;
                if (cache && state.lastAnimIdx >= 0 && state.lastAnimIdx < cache.length) {
                    const item = cache[state.lastAnimIdx];
                    if (item) item.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
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
            document.querySelectorAll<HTMLElement>('.ts-view-btn').forEach(b => {
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
