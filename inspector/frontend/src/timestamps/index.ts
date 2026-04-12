// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Timestamps tab — init, dropdowns, data loading, event wiring.
 * This is the entry point: main.js imports './timestamps/index'.
 *
 * DOMContentLoaded initialises DOM refs (state.dom), sets up all event
 * listeners, restores localStorage preferences, and loads reciters.
 */

import { SearchableSelect } from '../shared/searchable-select';
import { surahInfoReady, surahOptionText } from '../shared/surah-info';
import { LS_KEYS } from '../shared/constants';

import { state, dom } from './state';
import { setupCanvas, decodeWaveform, cacheWaveformSnapshot, handleCanvasClick } from './waveform';
import { buildUnifiedDisplay, buildPhonemeLabels } from './unified-display';
import { switchView, switchGranularity, rebuildAnimationView } from './animation';
import { _loadAudioAndPlay, navigateVerse, toggleAutoMode, startAnimation, stopAnimation, updateDisplay } from './playback';
import { handleKeydown } from './keyboard';
import { renderTsValidationPanel } from './validation';

// ---------------------------------------------------------------------------
// Segment-relative time helpers (used by waveform, playback, animation, keyboard)
// ---------------------------------------------------------------------------

export function getSegRelTime() {
    return dom.audio.currentTime - state.tsSegOffset;
}

export function getSegDuration() {
    return (state.tsSegEnd - state.tsSegOffset) || dom.audio.duration || 1;
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
    // Populate dom refs
    dom.audio = document.getElementById('audio-player');
    dom.canvas = document.getElementById('waveform-canvas');
    dom.ctx = dom.canvas.getContext('2d');
    dom.tsReciterSelect = document.getElementById('ts-reciter-select');
    dom.tsChapterSelect = document.getElementById('ts-chapter-select');
    dom.tsSegmentSelect = document.getElementById('ts-segment-select');
    dom.phonemeLabels = document.getElementById('phoneme-labels');
    dom.unifiedDisplay = document.getElementById('unified-display');
    dom.randomBtn = document.getElementById('random-btn');
    dom.randomReciterBtn = document.getElementById('random-reciter-btn');
    dom.tsPrevBtn = document.getElementById('ts-prev-btn');
    dom.tsNextBtn = document.getElementById('ts-next-btn');
    dom.animDisplay = document.getElementById('animation-display');
    dom.modeBtnA = document.getElementById('ts-mode-btn-a');
    dom.modeBtnB = document.getElementById('ts-mode-btn-b');
    dom.tsValidationEl = document.getElementById('ts-validation');
    dom.tsSpeedSelect = document.getElementById('ts-speed-select');
    dom.autoNextBtn = document.getElementById('ts-auto-next');
    dom.autoRandomBtn = document.getElementById('ts-auto-random');

    setupCanvas();
    setupEventListeners();

    // Restore ts speed before first audio load
    const _savedTsSpeed = localStorage.getItem(LS_KEYS.TS_SPEED);
    if (_savedTsSpeed) dom.tsSpeedSelect.value = _savedTsSpeed;

    // Restore view mode + sub-settings immediately (no dependency on reciters)
    const _savedTsView = localStorage.getItem(LS_KEYS.TS_VIEW_MODE);
    if (_savedTsView) {
        switchView(_savedTsView);
        if (_savedTsView === 'analysis') {
            const _savedLetters = localStorage.getItem(LS_KEYS.TS_SHOW_LETTERS);
            const _savedPhonemes = localStorage.getItem(LS_KEYS.TS_SHOW_PHONEMES);
            if (_savedLetters !== null) {
                state.tsShowLetters = _savedLetters === 'true';
                dom.modeBtnA.classList.toggle('active', state.tsShowLetters);
            }
            if (_savedPhonemes !== null) {
                state.tsShowPhonemes = _savedPhonemes === 'true';
                dom.modeBtnB.classList.toggle('active', state.tsShowPhonemes);
            }
        } else {
            const _savedGran = localStorage.getItem(LS_KEYS.TS_GRANULARITY);
            if (_savedGran) switchGranularity(_savedGran);
        }
    }

    await surahInfoReady;
    state.tsChapterSS = new SearchableSelect(dom.tsChapterSelect);
    loadTsReciters();
    fetch('/api/ts/config').then(r => r.json()).then(cfg => {
        const root = document.documentElement.style;
        root.setProperty('--unified-display-max-height', cfg.unified_display_max_height + 'px');
        root.setProperty('--anim-highlight-color', cfg.anim_highlight_color);
        const wordDur = cfg.anim_transition_easing === 'none' ? '0s' : cfg.anim_word_transition_duration + 's';
        const charDur = cfg.anim_transition_easing === 'none' ? '0s' : cfg.anim_char_transition_duration + 's';
        const easing = cfg.anim_transition_easing === 'none' ? 'linear' : cfg.anim_transition_easing;
        root.setProperty('--anim-word-transition', 'opacity ' + wordDur + ' ' + easing);
        root.setProperty('--anim-char-transition', 'opacity ' + charDur + ' ' + easing);
        root.setProperty('--anim-word-spacing', cfg.anim_word_spacing);
        root.setProperty('--anim-line-height', cfg.anim_line_height);
        root.setProperty('--anim-font-size', cfg.anim_font_size);
        root.setProperty('--analysis-word-font-size', cfg.analysis_word_font_size);
        root.setProperty('--analysis-letter-font-size', cfg.analysis_letter_font_size);
    });
});

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

function setupEventListeners() {
    dom.randomBtn.addEventListener('click', () => loadRandomTimestamp());
    dom.randomReciterBtn.addEventListener('click', () => loadRandomTimestamp(dom.tsReciterSelect.value || null));
    dom.tsPrevBtn.addEventListener('click', () => navigateVerse(-1));
    dom.tsNextBtn.addEventListener('click', () => navigateVerse(+1));
    dom.tsReciterSelect.addEventListener('change', onTsReciterChange);
    dom.tsChapterSelect.addEventListener('change', onTsChapterChange);
    dom.tsSegmentSelect.addEventListener('change', onTsVerseChange);
    dom.canvas.addEventListener('click', handleCanvasClick);
    dom.tsSpeedSelect.addEventListener('change', () => {
        dom.audio.playbackRate = parseFloat(dom.tsSpeedSelect.value);
        localStorage.setItem(LS_KEYS.TS_SPEED, dom.tsSpeedSelect.value);
    });

    dom.audio.addEventListener('loadedmetadata', () => {
        dom.audio.playbackRate = parseFloat(dom.tsSpeedSelect.value);
        buildPhonemeLabels();
        cacheWaveformSnapshot();
    });

    dom.audio.addEventListener('error', () => {
        const err = dom.audio.error;
        const code = err ? err.code : 0;
        const msgs = { 1: 'aborted', 2: 'network error', 3: 'decode error', 4: 'unsupported format' };
        console.error('Audio load error:', msgs[code] || `code ${code}`, dom.audio.src);
        // Clean up pending listener
        if (state._currentOnMeta) {
            dom.audio.removeEventListener('loadedmetadata', state._currentOnMeta);
            state._currentOnMeta = null;
        }
        state.tsAutoAdvancing = false;
    });

    dom.audio.addEventListener('play', startAnimation);
    dom.audio.addEventListener('pause', stopAnimation);
    dom.audio.addEventListener('ended', stopAnimation);

    // Auto-stop at segment end + auto-advance
    dom.audio.addEventListener('timeupdate', () => {
        if (state.tsSegEnd > 0 && dom.audio.currentTime >= state.tsSegEnd) {
            dom.audio.pause();
            dom.audio.currentTime = state.tsSegEnd;
            if (!state.tsAutoAdvancing && state.tsAutoMode === 'next') {
                state.tsAutoAdvancing = true;
                navigateVerse(+1);
            } else if (!state.tsAutoAdvancing && state.tsAutoMode === 'random') {
                state.tsAutoAdvancing = true;
                loadRandomTimestamp();
            }
        }
        if (dom.audio.paused) {
            updateDisplay();
        }
    });

    // Auto-play toggle buttons
    dom.autoNextBtn.addEventListener('click', () => toggleAutoMode('next'));
    dom.autoRandomBtn.addEventListener('click', () => toggleAutoMode('random'));

    document.addEventListener('keydown', handleKeydown);

    let _resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(_resizeTimer);
        _resizeTimer = setTimeout(() => {
            setupCanvas();
            cacheWaveformSnapshot();
        }, 150);
    });

    // Unified mode toggle (context-sensitive: Letters/Phonemes in analysis, Words/Characters in animation)
    dom.modeBtnA.addEventListener('click', () => {
        if (state.tsViewMode === 'analysis') {
            state.tsShowLetters = !state.tsShowLetters;
            dom.modeBtnA.classList.toggle('active', state.tsShowLetters);
            localStorage.setItem(LS_KEYS.TS_SHOW_LETTERS, state.tsShowLetters);
            dom.unifiedDisplay.querySelectorAll('.mega-letters').forEach(el => {
                el.classList.toggle('hidden', !state.tsShowLetters);
            });
        } else {
            dom.modeBtnA.classList.add('active');
            dom.modeBtnB.classList.remove('active');
            switchGranularity('words');
        }
    });
    dom.modeBtnB.addEventListener('click', () => {
        if (state.tsViewMode === 'analysis') {
            state.tsShowPhonemes = !state.tsShowPhonemes;
            dom.modeBtnB.classList.toggle('active', state.tsShowPhonemes);
            localStorage.setItem(LS_KEYS.TS_SHOW_PHONEMES, state.tsShowPhonemes);
            dom.unifiedDisplay.querySelectorAll('.mega-phonemes').forEach(el => {
                el.classList.toggle('hidden', !state.tsShowPhonemes);
            });
            dom.unifiedDisplay.querySelectorAll('.crossword-bridge').forEach(el => {
                el.classList.toggle('hidden', !state.tsShowPhonemes);
            });
        } else {
            dom.modeBtnB.classList.add('active');
            dom.modeBtnA.classList.remove('active');
            switchGranularity('characters');
        }
    });

    // View toggle (Analysis / Animation)
    document.querySelectorAll('.ts-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.ts-view-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            switchView(btn.dataset.view);
        });
    });
}

// ---------------------------------------------------------------------------
// Selection flow: Reciter -> Chapter -> Segment
// ---------------------------------------------------------------------------

async function loadTsReciters() {
    try {
        const resp = await fetch('/api/ts/reciters');
        state.tsAllReciters = await resp.json();
        renderTsReciters();

        // Restore saved reciter
        const _savedTsReciter = localStorage.getItem(LS_KEYS.TS_RECITER);
        if (_savedTsReciter) {
            dom.tsReciterSelect.value = _savedTsReciter;
            if (dom.tsReciterSelect.value === _savedTsReciter) {
                await onTsReciterChange();
            }
        }
    } catch (e) {
        console.error('Error loading ts reciters:', e);
    }
}

function renderTsReciters() {
    dom.tsReciterSelect.innerHTML = '<option value="">-- select --</option>';

    // Group by audio_source
    const grouped = {};  // source -> [reciter, ...]
    const uncategorized = [];

    for (const r of state.tsAllReciters) {
        const src = r.audio_source || '';
        if (src) {
            if (!grouped[src]) grouped[src] = [];
            grouped[src].push(r);
        } else {
            uncategorized.push(r);
        }
    }

    for (const source of Object.keys(grouped).sort()) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = source;
        for (const r of grouped[source]) {
            const opt = document.createElement('option');
            opt.value = r.slug;
            opt.textContent = r.name;
            optgroup.appendChild(opt);
        }
        dom.tsReciterSelect.appendChild(optgroup);
    }

    if (uncategorized.length > 0) {
        const optgroup = document.createElement('optgroup');
        optgroup.label = '(uncategorized)';
        for (const r of uncategorized) {
            const opt = document.createElement('option');
            opt.value = r.slug;
            opt.textContent = r.name;
            optgroup.appendChild(opt);
        }
        dom.tsReciterSelect.appendChild(optgroup);
    }
}

async function onTsReciterChange() {
    const reciter = dom.tsReciterSelect.value;
    if (reciter) localStorage.setItem(LS_KEYS.TS_RECITER, reciter);
    dom.tsChapterSelect.innerHTML = '<option value="">-- select --</option>';
    if (state.tsChapterSS) state.tsChapterSS.refresh();
    dom.tsSegmentSelect.innerHTML = '<option value="">--</option>';
    clearDisplay();
    clearTsValidation();
    if (!reciter) return;

    try {
        const [chapResult, valResult] = await Promise.allSettled([
            fetch(`/api/ts/chapters/${reciter}`).then(r => r.json()),
            fetch(`/api/ts/validate/${reciter}`).then(r => r.json()),
        ]);
        if (chapResult.status === 'fulfilled') {
            chapResult.value.forEach(ch => {
                const opt = document.createElement('option');
                opt.value = ch; opt.textContent = surahOptionText(ch);
                dom.tsChapterSelect.appendChild(opt);
            });
            if (state.tsChapterSS) state.tsChapterSS.refresh();
        }
        if (valResult.status === 'fulfilled' && !valResult.value.error) {
            state.tsValidationData = valResult.value;
            renderTsValidationPanel(state.tsValidationData);
        }
    } catch (e) {
        console.error('Error loading ts reciter data:', e);
    }
}

export function clearTsValidation() {
    state.tsValidationData = null;
    dom.tsValidationEl.innerHTML = '';
    dom.tsValidationEl.hidden = true;
}

export async function jumpToTsVerse(verseKey) {
    if (!verseKey || !verseKey.includes(':')) return;
    const chapter = verseKey.split(':')[0];

    if (dom.tsChapterSelect.value !== chapter) {
        dom.tsChapterSelect.value = chapter;
        if (state.tsChapterSS) state.tsChapterSS.refresh();
        await onTsChapterChange();
    }

    const opts = dom.tsSegmentSelect.options;
    for (let i = 0; i < opts.length; i++) {
        if (opts[i].value === verseKey) {
            dom.tsSegmentSelect.selectedIndex = i;
            break;
        }
    }
    await onTsVerseChange();
    updateNavButtons();
}

export async function onTsChapterChange() {
    const reciter = dom.tsReciterSelect.value;
    const chapter = dom.tsChapterSelect.value;
    dom.tsSegmentSelect.innerHTML = '<option value="">--</option>';
    clearDisplay();
    if (!reciter || !chapter) return;

    try {
        const resp = await fetch(`/api/ts/verses/${reciter}/${chapter}`);
        const data = await resp.json();
        if (data.error) return;

        const verses = data.verses || [];
        verses.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.ref;
            opt.textContent = v.ref.split(':')[1];
            opt.dataset.audioUrl = v.audio_url || '';
            dom.tsSegmentSelect.appendChild(opt);
        });
    } catch (e) {
        console.error('Error loading ts verses:', e);
    }
    updateNavButtons();
}

export async function onTsVerseChange() {
    const reciter = dom.tsReciterSelect.value;
    const chapter = dom.tsChapterSelect.value;
    const verseRef = dom.tsSegmentSelect.value;
    if (!reciter || !chapter || verseRef === '') return;

    await loadTimestampVerse(reciter, verseRef);
}

async function loadTimestampVerse(reciter, verseRef) {
    state.tsSegEnd = Infinity;  // prevent timeupdate auto-advance during load
    dom.randomBtn.disabled = true;
    dom.randomReciterBtn.disabled = true;
    document.body.classList.add('loading');

    try {
        const resp = await fetch(`/api/ts/data/${reciter}/${verseRef}`);
        const data = await resp.json();

        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }

        state.currentData = data;
        state.intervals = data.intervals || [];
        state.words = data.words || [];
        state.waveformData = null;

        // Set segment offset (0 for by_ayah -- whole file is one verse)
        state.tsSegOffset = data.time_start_ms / 1000;
        state.tsSegEnd = data.time_end_ms / 1000;

        // Sync dropdowns if they don't match (e.g. from random)
        if (dom.tsReciterSelect.value !== data.reciter) {
            dom.tsReciterSelect.value = data.reciter;
            await onTsReciterChange();
        }
        if (dom.tsChapterSelect.value !== String(data.chapter)) {
            dom.tsChapterSelect.value = String(data.chapter);
            if (state.tsChapterSS) state.tsChapterSS.refresh();
            await onTsChapterChange();
        }
        dom.tsSegmentSelect.value = data.verse_ref;

        // Load audio and seek to start
        _loadAudioAndPlay(data.audio_url);

        // Decode waveform for the verse
        decodeWaveform(data.audio_url);

        // Build displays
        buildUnifiedDisplay();
        buildPhonemeLabels();
        if (state.tsViewMode === 'animation') {
            rebuildAnimationView();
        }

    } catch (e) {
        console.error('Error loading timestamp verse:', e);
        alert('Failed to load verse');
    } finally {
        dom.randomBtn.disabled = false;
        dom.randomReciterBtn.disabled = false;
        document.body.classList.remove('loading');
        updateNavButtons();
    }
}

export async function loadRandomTimestamp(reciter = null) {
    state.tsSegEnd = Infinity;  // prevent timeupdate auto-advance during load
    dom.randomBtn.disabled = true;
    dom.randomReciterBtn.disabled = true;
    document.body.classList.add('loading');

    try {
        const url = reciter ? `/api/ts/random/${encodeURIComponent(reciter)}` : '/api/ts/random';
        const resp = await fetch(url);
        const data = await resp.json();

        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }

        state.currentData = data;
        state.intervals = data.intervals || [];
        state.words = data.words || [];
        state.waveformData = null;

        state.tsSegOffset = data.time_start_ms / 1000;
        state.tsSegEnd = data.time_end_ms / 1000;

        // Sync category toggle if random landed on a different category
        // Sync dropdowns directly -- skip heavy validation calls
        const reciterChanged = dom.tsReciterSelect.value !== data.reciter;
        const chapterChanged = dom.tsChapterSelect.value !== String(data.chapter);

        if (reciterChanged) {
            dom.tsReciterSelect.value = data.reciter;
            clearTsValidation();
        }

        // Populate chapter + verse dropdowns in parallel (lightweight APIs only)
        const fetches = [];
        if (reciterChanged) fetches.push(
            fetch(`/api/ts/chapters/${encodeURIComponent(data.reciter)}`).then(r => r.json()).then(chapters => {
                dom.tsChapterSelect.innerHTML = '<option value="">-- select --</option>';
                chapters.forEach(ch => {
                    const opt = document.createElement('option');
                    opt.value = ch; opt.textContent = surahOptionText(ch);
                    dom.tsChapterSelect.appendChild(opt);
                });
                dom.tsChapterSelect.value = String(data.chapter);
                if (state.tsChapterSS) state.tsChapterSS.refresh();
            })
        );
        if (reciterChanged || chapterChanged) fetches.push(
            fetch(`/api/ts/verses/${encodeURIComponent(data.reciter)}/${data.chapter}`).then(r => r.json()).then(vData => {
                dom.tsSegmentSelect.innerHTML = '<option value="">--</option>';
                (vData.verses || []).forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v.ref; opt.textContent = v.ref.split(':')[1];
                    opt.dataset.audioUrl = v.audio_url || '';
                    dom.tsSegmentSelect.appendChild(opt);
                });
            })
        );
        await Promise.all(fetches);
        dom.tsSegmentSelect.value = data.verse_ref;

        _loadAudioAndPlay(data.audio_url);

        decodeWaveform(data.audio_url);
        buildUnifiedDisplay();
        buildPhonemeLabels();
        if (state.tsViewMode === 'animation') {
            rebuildAnimationView();
        }

    } catch (e) {
        console.error('Error loading random timestamp:', e);
    } finally {
        dom.randomBtn.disabled = false;
        dom.randomReciterBtn.disabled = false;
        document.body.classList.remove('loading');
        updateNavButtons();
    }
}

function clearDisplay() {
    state.intervals = [];
    state.words = [];
    state.waveformData = null;
    state.waveformSnapshot = null;
    state.currentData = null;
    state.tsSegOffset = 0;
    state.tsSegEnd = 0;
    dom.unifiedDisplay.innerHTML = '';
    dom.phonemeLabels.innerHTML = '';
    dom.animDisplay.innerHTML = '';
    state.animWordCache = null;
    state.animCharCache = null;
    state.lastAnimIdx = -1;
    state.cachedBlocks = [];
    state.cachedPhonemes = [];
    state.cachedLetterEls = [];
    state.cachedLabels = [];
    state.prevActiveWordIdx = -1;
    state.prevActivePhonemeIdx = -1;
    if (dom.canvas.width && dom.canvas.height) {
        dom.ctx.fillStyle = '#0f0f23';
        dom.ctx.fillRect(0, 0, dom.canvas.width, dom.canvas.height);
    }
    updateNavButtons();
}

function updateNavButtons() {
    const idx = dom.tsSegmentSelect.selectedIndex;
    const len = dom.tsSegmentSelect.options.length;
    dom.tsPrevBtn.disabled = (idx <= 1);           // 0 = "--" placeholder, 1 = first verse
    dom.tsNextBtn.disabled = (idx < 1 || idx >= len - 1);
}
