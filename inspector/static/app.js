/**
 * Alignment Viewer - Timestamps Tab
 * Loads pre-computed word/phone timestamps from JSONL data.
 * Selection: Reciter (optgroups) → Chapter → Verse.
 * Audio: plays per-verse audio (by_ayah) or full surah audio seeked to offset.
 */

// ── Shared globals (available to segments.js and audio.js) ──────────────
let surahInfo = {};
const surahInfoReady = fetch('/api/surah-info').then(r => r.json()).then(data => { surahInfo = data; });

function surahOptionText(num) {
    const info = surahInfo[String(num)];
    if (!info) return String(num);
    const ar = info.name_ar.replace(/^سُورَةُ\s*/, '');
    return `${num} ${info.name_en} ${ar}`;
}

/**
 * SearchableSelect — lightweight filterable wrapper around a native <select>.
 * Hides the <select>, shows a text input + dropdown overlay.
 * Fires native 'change' event on the hidden select so existing handlers work.
 */
class SearchableSelect {
    constructor(selectEl) {
        this.select = selectEl;
        this.options = [];  // [{value, text}, ...]

        // Wrapper
        this.wrapper = document.createElement('div');
        this.wrapper.className = 'ss-wrapper';
        selectEl.parentNode.insertBefore(this.wrapper, selectEl);
        this.wrapper.appendChild(selectEl);
        selectEl.style.display = 'none';

        // Text input
        this.input = document.createElement('input');
        this.input.type = 'text';
        this.input.className = 'ss-input';
        this.input.placeholder = '--';
        this.wrapper.appendChild(this.input);

        // Dropdown
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'ss-dropdown';
        this.dropdown.hidden = true;
        this.wrapper.appendChild(this.dropdown);

        this.highlightIdx = -1;
        this.filtered = [];

        this.input.addEventListener('focus', () => this._open());
        this.input.addEventListener('input', () => this._filter());
        this.input.addEventListener('keydown', e => this._onKey(e));
        document.addEventListener('click', e => {
            if (!this.wrapper.contains(e.target)) this._close();
        });

        this.refresh();
    }

    refresh() {
        this.options = [];
        for (const opt of this.select.options) {
            if (!opt.value) continue;  // skip placeholder
            this.options.push({ value: opt.value, text: opt.textContent });
        }
        // Sync displayed text to current select value
        const cur = this.select.value;
        const match = this.options.find(o => o.value === cur);
        this.input.value = match ? match.text : '';
        this._close();
    }

    _open() {
        this.input.value = '';
        this._filter();
        this.dropdown.hidden = false;
    }

    _close() {
        this.dropdown.hidden = true;
        this.highlightIdx = -1;
        // Restore display text to current selection
        const cur = this.select.value;
        const match = this.options.find(o => o.value === cur);
        this.input.value = match ? match.text : '';
    }

    _filter() {
        const q = this.input.value.toLowerCase();
        this.filtered = q ? this.options.filter(o => o.text.toLowerCase().includes(q)) : [...this.options];
        this.highlightIdx = -1;
        this._render();
    }

    _render() {
        this.dropdown.innerHTML = '';
        this.filtered.forEach((opt, i) => {
            const div = document.createElement('div');
            div.className = 'ss-option' + (i === this.highlightIdx ? ' ss-highlight' : '');
            div.textContent = opt.text;
            div.addEventListener('mousedown', e => { e.preventDefault(); this._pick(opt); });
            this.dropdown.appendChild(div);
        });
    }

    _pick(opt) {
        this.select.value = opt.value;
        this.input.value = opt.text;
        this._close();
        this.select.dispatchEvent(new Event('change'));
    }

    _onKey(e) {
        if (this.dropdown.hidden) {
            if (e.key === 'ArrowDown' || e.key === 'Enter') { this._open(); e.preventDefault(); }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.highlightIdx = Math.min(this.highlightIdx + 1, this.filtered.length - 1);
            this._render();
            this._scrollToHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.highlightIdx = Math.max(this.highlightIdx - 1, 0);
            this._render();
            this._scrollToHighlight();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (this.highlightIdx >= 0 && this.highlightIdx < this.filtered.length) {
                this._pick(this.filtered[this.highlightIdx]);
            }
        } else if (e.key === 'Escape') {
            this._close();
        }
    }

    _scrollToHighlight() {
        const el = this.dropdown.children[this.highlightIdx];
        if (el) el.scrollIntoView({ block: 'nearest' });
    }
}

// State
let currentData = null;
let intervals = [];
let words = [];
let audioContext = null;
let waveformData = null;
let fullAudioBuffer = null;  // decoded full surah AudioBuffer
const audioBufferCache = new Map();  // URL → decoded AudioBuffer (A-3 fix)
let waveformSnapshot = null;  // offscreen canvas for static waveform (A-1 fix)

// Cached DOM element refs — populated by buildUnifiedDisplay/buildPhonemeLabels (A-2 fix)
let cachedBlocks = [];
let cachedPhonemes = [];
let cachedLetterEls = [];
let cachedLabels = [];
let prevActiveWordIdx = -1;   // for guarded scrollIntoView (A-4 fix)
let prevActivePhonemeIdx = -1;

// Segment offset state
let tsSegOffset = 0;   // segment start in seconds (absolute in surah audio)
let tsSegEnd = 0;      // segment end in seconds

// All reciters (cached for optgroup rendering)
let tsAllReciters = [];

// Animation view state
let tsViewMode = 'analysis';   // 'analysis' | 'animation'
let tsGranularity = 'words';   // 'words' | 'characters'
let animWordCache = null;
let animCharCache = null;
let lastAnimIdx = -1;

// DOM Elements
const audio = document.getElementById('audio-player');
const canvas = document.getElementById('waveform-canvas');
const ctx = canvas.getContext('2d');
const tsReciterSelect = document.getElementById('ts-reciter-select');
const tsChapterSelect = document.getElementById('ts-chapter-select');
const tsSegmentSelect = document.getElementById('ts-segment-select');
const phonemeLabels = document.getElementById('phoneme-labels');
const unifiedDisplay = document.getElementById('unified-display');
const randomBtn = document.getElementById('random-btn');
const randomReciterBtn = document.getElementById('random-reciter-btn');
const tsPrevBtn = document.getElementById('ts-prev-btn');
const tsNextBtn = document.getElementById('ts-next-btn');
const animDisplay = document.getElementById('animation-display');
const modeToggle = document.getElementById('ts-mode-toggle');
const modeBtnA = document.getElementById('ts-mode-btn-a');
const modeBtnB = document.getElementById('ts-mode-btn-b');
const tsValidationEl = document.getElementById('ts-validation');
const tsSpeedSelect = document.getElementById('ts-speed-select');
let tsValidationData = null;

let tsShowLetters = true;
let tsShowPhonemes = false;

// Auto-play toggles
let tsAutoMode = null; // null | 'next' | 'random'
let tsAutoAdvancing = false; // guard against re-entry from timeupdate
const autoNextBtn = document.getElementById('ts-auto-next');
const autoRandomBtn = document.getElementById('ts-auto-random');

// Track active tab
let activeTab = 'timestamps';

// SearchableSelect instance for timestamps chapter dropdown
let tsChapterSS = null;

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    setupCanvas();
    setupEventListeners();
    setupTabSwitching();
    await surahInfoReady;
    tsChapterSS = new SearchableSelect(tsChapterSelect);
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

function setupCanvas() {
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = 200;
}

function setupTabSwitching() {
    const panels = ['timestamps', 'segments', 'audio', 'requests'];
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeTab = btn.dataset.tab;
            panels.forEach(p => {
                document.getElementById(p + '-panel').hidden = (activeTab !== p);
            });
            // Pause audio from other tabs
            if (activeTab !== 'timestamps') audio.pause();
            if (activeTab !== 'segments') {
                const segAudio = document.getElementById('seg-audio-player');
                if (segAudio) segAudio.pause();
                if (typeof valCardAudio !== 'undefined' && valCardAudio) valCardAudio.pause();
            }
            if (activeTab !== 'audio') {
                const audPlayer = document.getElementById('aud-player');
                if (audPlayer) audPlayer.pause();
            }
        });
    });
}

function setupEventListeners() {
    randomBtn.addEventListener('click', () => loadRandomTimestamp());
    randomReciterBtn.addEventListener('click', () => loadRandomTimestamp(tsReciterSelect.value || null));
    tsPrevBtn.addEventListener('click', () => navigateVerse(-1));
    tsNextBtn.addEventListener('click', () => navigateVerse(+1));
    tsReciterSelect.addEventListener('change', onTsReciterChange);
    tsChapterSelect.addEventListener('change', onTsChapterChange);
    tsSegmentSelect.addEventListener('change', onTsVerseChange);
    canvas.addEventListener('click', handleCanvasClick);
    tsSpeedSelect.addEventListener('change', () => {
        audio.playbackRate = parseFloat(tsSpeedSelect.value);
    });

    audio.addEventListener('loadedmetadata', () => {
        audio.playbackRate = parseFloat(tsSpeedSelect.value);
        buildPhonemeLabels();
        cacheWaveformSnapshot();
    });

    audio.addEventListener('play', startAnimation);
    audio.addEventListener('pause', stopAnimation);
    audio.addEventListener('ended', stopAnimation);

    // Auto-stop at segment end + auto-advance
    audio.addEventListener('timeupdate', () => {
        if (tsSegEnd > 0 && audio.currentTime >= tsSegEnd) {
            audio.pause();
            audio.currentTime = tsSegEnd;
            if (!tsAutoAdvancing && tsAutoMode === 'next') {
                tsAutoAdvancing = true;
                navigateVerse(+1);
            } else if (!tsAutoAdvancing && tsAutoMode === 'random') {
                tsAutoAdvancing = true;
                loadRandomTimestamp();
            }
        }
        if (audio.paused) {
            updateDisplay();
        }
    });

    // Auto-play toggle buttons
    autoNextBtn.addEventListener('click', () => toggleAutoMode('next'));
    autoRandomBtn.addEventListener('click', () => toggleAutoMode('random'));

    document.addEventListener('keydown', handleKeydown);

    window.addEventListener('resize', () => {
        setupCanvas();
        cacheWaveformSnapshot();
    });

    // Unified mode toggle (context-sensitive: Letters/Phonemes in analysis, Words/Characters in animation)
    modeBtnA.addEventListener('click', () => {
        if (tsViewMode === 'analysis') {
            tsShowLetters = !tsShowLetters;
            modeBtnA.classList.toggle('active', tsShowLetters);
            unifiedDisplay.querySelectorAll('.mega-letters').forEach(el => {
                el.classList.toggle('hidden', !tsShowLetters);
            });
        } else {
            modeBtnA.classList.add('active');
            modeBtnB.classList.remove('active');
            switchGranularity('words');
        }
    });
    modeBtnB.addEventListener('click', () => {
        if (tsViewMode === 'analysis') {
            tsShowPhonemes = !tsShowPhonemes;
            modeBtnB.classList.toggle('active', tsShowPhonemes);
            unifiedDisplay.querySelectorAll('.mega-phonemes').forEach(el => {
                el.classList.toggle('hidden', !tsShowPhonemes);
            });
            unifiedDisplay.querySelectorAll('.crossword-bridge').forEach(el => {
                el.classList.toggle('hidden', !tsShowPhonemes);
            });
        } else {
            modeBtnB.classList.add('active');
            modeBtnA.classList.remove('active');
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
// Segment-relative time helpers
// ---------------------------------------------------------------------------

function getSegRelTime() {
    return audio.currentTime - tsSegOffset;
}

function getSegDuration() {
    return (tsSegEnd - tsSegOffset) || audio.duration || 1;
}

// ---------------------------------------------------------------------------
// Selection flow: Reciter → Chapter → Segment
// ---------------------------------------------------------------------------

async function loadTsReciters() {
    try {
        const resp = await fetch('/api/ts/reciters');
        tsAllReciters = await resp.json();
        renderTsReciters();
    } catch (e) {
        console.error('Error loading ts reciters:', e);
    }
}

function renderTsReciters() {
    tsReciterSelect.innerHTML = '<option value="">-- select --</option>';

    // Group by audio_source
    const grouped = {};  // source -> [reciter, ...]
    const uncategorized = [];

    for (const r of tsAllReciters) {
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
        tsReciterSelect.appendChild(optgroup);
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
        tsReciterSelect.appendChild(optgroup);
    }
}

async function onTsReciterChange() {
    const reciter = tsReciterSelect.value;
    tsChapterSelect.innerHTML = '<option value="">-- select --</option>';
    if (tsChapterSS) tsChapterSS.refresh();
    tsSegmentSelect.innerHTML = '<option value="">--</option>';
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
                tsChapterSelect.appendChild(opt);
            });
            if (tsChapterSS) tsChapterSS.refresh();
        }
        if (valResult.status === 'fulfilled' && !valResult.value.error) {
            tsValidationData = valResult.value;
            renderTsValidationPanel(tsValidationData);
        }
    } catch (e) {
        console.error('Error loading ts reciter data:', e);
    }
}

function clearTsValidation() {
    tsValidationData = null;
    tsValidationEl.innerHTML = '';
    tsValidationEl.hidden = true;
}

function renderTsValidationPanel(data) {
    tsValidationEl.innerHTML = '';
    if (!data) { tsValidationEl.hidden = true; return; }

    const { mfa_failures, missing_words, boundary_mismatches } = data;
    const hasAny = [mfa_failures, missing_words, boundary_mismatches].some(a => a && a.length > 0);
    if (!hasAny) { tsValidationEl.hidden = true; return; }
    tsValidationEl.hidden = false;

    const categories = [
        {
            name: 'Failed Alignments', items: mfa_failures || [],
            countClass: 'has-errors', btnClass: 'val-error',
            getLabel: i => i.label,
            getTitle: i => i.error || '',
        },
        {
            name: 'Missing Words', items: missing_words || [],
            countClass: 'has-errors', btnClass: 'val-error',
            getLabel: i => i.label,
            getTitle: i => `missing indices: ${(i.missing || []).join(', ')}`,
        },
        {
            name: 'Boundary Mismatches', items: boundary_mismatches || [],
            countClass: 'has-warnings', btnClass: 'val-warning',
            getLabel: i => i.label,
            getTitle: i => `timestamps ${i.ts_ms}ms vs segments ${i.seg_ms}ms`,
        },
    ];

    categories.forEach(cat => {
        if (!cat.items.length) return;
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        const badge = document.createElement('span');
        badge.className = `val-count ${cat.countClass}`;
        badge.textContent = cat.items.length;
        summary.textContent = cat.name + ' ';
        summary.appendChild(badge);
        details.appendChild(summary);

        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        cat.items.forEach(issue => {
            const btn = document.createElement('button');
            btn.className = `val-btn ${cat.btnClass}`;
            btn.textContent = cat.getLabel(issue);
            btn.title = cat.getTitle(issue);
            btn.addEventListener('click', () => jumpToTsVerse(issue.verse_key));
            itemsDiv.appendChild(btn);
        });
        details.appendChild(itemsDiv);
        tsValidationEl.appendChild(details);
    });
}

async function jumpToTsVerse(verseKey) {
    if (!verseKey || !verseKey.includes(':')) return;
    const chapter = verseKey.split(':')[0];

    if (tsChapterSelect.value !== chapter) {
        tsChapterSelect.value = chapter;
        if (tsChapterSS) tsChapterSS.refresh();
        await onTsChapterChange();
    }

    const opts = tsSegmentSelect.options;
    for (let i = 0; i < opts.length; i++) {
        if (opts[i].value === verseKey) {
            tsSegmentSelect.selectedIndex = i;
            break;
        }
    }
    await onTsVerseChange();
    updateNavButtons();
}

async function onTsChapterChange() {
    const reciter = tsReciterSelect.value;
    const chapter = tsChapterSelect.value;
    tsSegmentSelect.innerHTML = '<option value="">--</option>';
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
            tsSegmentSelect.appendChild(opt);
        });
    } catch (e) {
        console.error('Error loading ts verses:', e);
    }
    updateNavButtons();
}

async function onTsVerseChange() {
    const reciter = tsReciterSelect.value;
    const chapter = tsChapterSelect.value;
    const verseRef = tsSegmentSelect.value;
    if (!reciter || !chapter || verseRef === '') return;

    await loadTimestampVerse(reciter, verseRef);
}

function toggleAutoMode(mode) {
    if (tsAutoMode === mode) {
        tsAutoMode = null;
    } else {
        tsAutoMode = mode;
    }
    autoNextBtn.classList.toggle('active', tsAutoMode === 'next');
    autoRandomBtn.classList.toggle('active', tsAutoMode === 'random');
}

function navigateVerse(delta) {
    const newIdx = tsSegmentSelect.selectedIndex + delta;
    if (newIdx < 1 || newIdx >= tsSegmentSelect.options.length) {
        tsAutoAdvancing = false;
        return;
    }
    tsSegmentSelect.selectedIndex = newIdx;
    onTsVerseChange();
}

function updateNavButtons() {
    const idx = tsSegmentSelect.selectedIndex;
    const len = tsSegmentSelect.options.length;
    tsPrevBtn.disabled = (idx <= 1);           // 0 = "--" placeholder, 1 = first verse
    tsNextBtn.disabled = (idx < 1 || idx >= len - 1);
}

async function loadTimestampVerse(reciter, verseRef) {
    tsSegEnd = Infinity;  // prevent timeupdate auto-advance during load
    randomBtn.disabled = true;
    randomReciterBtn.disabled = true;
    document.body.classList.add('loading');

    try {
        const resp = await fetch(`/api/ts/data/${reciter}/${verseRef}`);
        const data = await resp.json();

        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }

        currentData = data;
        intervals = data.intervals || [];
        words = data.words || [];
        waveformData = null;

        // Set segment offset (0 for by_ayah — whole file is one verse)
        tsSegOffset = data.time_start_ms / 1000;
        tsSegEnd = data.time_end_ms / 1000;

        // Sync dropdowns if they don't match (e.g. from random)
        if (tsReciterSelect.value !== data.reciter) {
            tsReciterSelect.value = data.reciter;
            await onTsReciterChange();
        }
        if (tsChapterSelect.value !== String(data.chapter)) {
            tsChapterSelect.value = String(data.chapter);
            if (tsChapterSS) tsChapterSS.refresh();
            await onTsChapterChange();
        }
        tsSegmentSelect.value = data.verse_ref;

        // Load audio and seek to start
        const newSrc = data.audio_url;
        if (newSrc && audio.src !== newSrc && audio.src !== location.origin + newSrc) {
            audio.src = newSrc;
            audio.addEventListener('loadedmetadata', function onMeta() {
                audio.removeEventListener('loadedmetadata', onMeta);
                audio.currentTime = tsSegOffset;
                tsAutoAdvancing = false;
                audio.play();
            });
        } else {
            audio.currentTime = tsSegOffset;
            tsAutoAdvancing = false;
            audio.play();
        }

        // Decode waveform for the verse
        decodeWaveform(data.audio_url);

        // Build displays
        buildUnifiedDisplay();
        buildPhonemeLabels();
        if (tsViewMode === 'animation') {
            rebuildAnimationView();
        }

    } catch (e) {
        console.error('Error loading timestamp verse:', e);
        alert('Failed to load verse');
    } finally {
        randomBtn.disabled = false;
        randomReciterBtn.disabled = false;
        document.body.classList.remove('loading');
        updateNavButtons();
    }
}

async function loadRandomTimestamp(reciter = null) {
    tsSegEnd = Infinity;  // prevent timeupdate auto-advance during load
    randomBtn.disabled = true;
    randomReciterBtn.disabled = true;
    document.body.classList.add('loading');

    try {
        const url = reciter ? `/api/ts/random/${encodeURIComponent(reciter)}` : '/api/ts/random';
        const resp = await fetch(url);
        const data = await resp.json();

        if (data.error) {
            alert('Error: ' + data.error);
            return;
        }

        currentData = data;
        intervals = data.intervals || [];
        words = data.words || [];
        waveformData = null;

        tsSegOffset = data.time_start_ms / 1000;
        tsSegEnd = data.time_end_ms / 1000;

        // Sync category toggle if random landed on a different category
        // Sync dropdowns directly — skip heavy validation calls
        const reciterChanged = tsReciterSelect.value !== data.reciter;
        const chapterChanged = tsChapterSelect.value !== String(data.chapter);

        if (reciterChanged) {
            tsReciterSelect.value = data.reciter;
            clearTsValidation();
        }

        // Populate chapter + verse dropdowns in parallel (lightweight APIs only)
        const fetches = [];
        if (reciterChanged) fetches.push(
            fetch(`/api/ts/chapters/${encodeURIComponent(data.reciter)}`).then(r => r.json()).then(chapters => {
                tsChapterSelect.innerHTML = '<option value="">-- select --</option>';
                chapters.forEach(ch => {
                    const opt = document.createElement('option');
                    opt.value = ch; opt.textContent = surahOptionText(ch);
                    tsChapterSelect.appendChild(opt);
                });
                tsChapterSelect.value = String(data.chapter);
                if (tsChapterSS) tsChapterSS.refresh();
            })
        );
        if (reciterChanged || chapterChanged) fetches.push(
            fetch(`/api/ts/verses/${encodeURIComponent(data.reciter)}/${data.chapter}`).then(r => r.json()).then(vData => {
                tsSegmentSelect.innerHTML = '<option value="">--</option>';
                (vData.verses || []).forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v.ref; opt.textContent = v.ref.split(':')[1];
                    opt.dataset.audioUrl = v.audio_url || '';
                    tsSegmentSelect.appendChild(opt);
                });
            })
        );
        await Promise.all(fetches);
        tsSegmentSelect.value = data.verse_ref;

        const newSrc = data.audio_url;
        if (newSrc) {
            audio.src = newSrc;
            audio.addEventListener('loadedmetadata', function onMeta() {
                audio.removeEventListener('loadedmetadata', onMeta);
                audio.currentTime = tsSegOffset;
                tsAutoAdvancing = false;
                audio.play();
            });
        }

        decodeWaveform(data.audio_url);
        buildUnifiedDisplay();
        buildPhonemeLabels();
        if (tsViewMode === 'animation') {
            rebuildAnimationView();
        }

    } catch (e) {
        console.error('Error loading random timestamp:', e);
    } finally {
        randomBtn.disabled = false;
        randomReciterBtn.disabled = false;
        document.body.classList.remove('loading');
        updateNavButtons();
    }
}

function clearDisplay() {
    intervals = [];
    words = [];
    waveformData = null;
    waveformSnapshot = null;
    currentData = null;
    tsSegOffset = 0;
    tsSegEnd = 0;
    unifiedDisplay.innerHTML = '';
    phonemeLabels.innerHTML = '';
    animDisplay.innerHTML = '';
    animWordCache = null;
    animCharCache = null;
    lastAnimIdx = -1;
    cachedBlocks = [];
    cachedPhonemes = [];
    cachedLetterEls = [];
    cachedLabels = [];
    prevActiveWordIdx = -1;
    prevActivePhonemeIdx = -1;
    if (canvas.width && canvas.height) {
        ctx.fillStyle = '#0f0f23';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    updateNavButtons();
}

// ---------------------------------------------------------------------------
// Unified display (words + phonemes)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Cross-word ghunna detection: letter + phoneme contextual validation
// ---------------------------------------------------------------------------
// Instead of pure phoneme-symbol matching, we validate each ghunna phoneme
// against the Arabic letters at both sides of a word boundary. This prevents
// false positives (in-word shaddah ghunna) and enables idgham shafawi detection
// (m̃ at END of previous word).

const TASHKEEL = /[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7\u06E8\u06EA-\u06ED\u08F0-\u08F2]/g;

function stripTashkeel(text) {
    return text.replace(TASHKEEL, '');
}

function getLastBaseLetter(word) {
    const bare = stripTashkeel(word.text || '');
    return bare.length ? bare[bare.length - 1] : '';
}

function getFirstBaseLetter(word) {
    const bare = stripTashkeel(word.text || '');
    for (const ch of bare) {
        if (ch !== '\u0671' && ch !== '\u0627') return ch;  // skip ٱ and ا
    }
    return bare.length ? bare[0] : '';
}

function hasTanween(word) {
    const text = word.text || '';
    const lastBase = stripTashkeel(text);
    const endsWithAlef = lastBase.length > 0 &&
        (lastBase[lastBase.length - 1] === '\u0627' || lastBase[lastBase.length - 1] === '\u0649');
    if (endsWithAlef) {
        return /[\u064B\u08F0]/.test(text);  // tanween fatha (standard + open) before trailing alef
    }
    const tail = text.slice(-3);
    return /[\u064C\u064D\u08F1\u08F2]/.test(tail);  // tanween damma/kasra (standard + open) on last letter
}

// Idgham ghunnah phonemes at START of current word → required Arabic start letter
const IDGHAM_GHUNNAH_START = {
    'ñ': '\u0646',  // ن
    'j̃': '\u064A',  // ي
    'w̃': '\u0648',  // و
    'm̃': '\u0645',  // م
};

function computeBridgeAtBoundary(prevWord, currWord) {
    const fromPrev = [];
    const fromCurr = [];

    // 1. Prefix of current word: idgham ghunnah phonemes
    const currIndices = currWord.phoneme_indices || [];
    const prevEndsNoon = getLastBaseLetter(prevWord) === '\u0646';
    const prevHasTanween = hasTanween(prevWord);
    const noonOrTanween = prevEndsNoon || prevHasTanween;

    for (const pi of currIndices) {
        const phone = intervals[pi] && intervals[pi].phone;
        if (!phone) break;
        const requiredLetter = IDGHAM_GHUNNAH_START[phone];
        if (!requiredLetter) break;
        if (noonOrTanween && getFirstBaseLetter(currWord) === requiredLetter) {
            fromCurr.push(pi);
        } else {
            break;  // in-word ghunna (shaddah), not cross-word
        }
    }

    // 2. Suffix of prev word: idgham shafawi (m̃ when مْ before م)
    const prevIndices = prevWord.phoneme_indices || [];
    if (getLastBaseLetter(prevWord) === '\u0645' &&
        getFirstBaseLetter(currWord) === '\u0645') {
        for (let k = prevIndices.length - 1; k >= 0; k--) {
            const pi = prevIndices[k];
            const phone = intervals[pi] && intervals[pi].phone;
            if (phone === 'm̃') {
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

function createCrosswordBridge(bridgeIndices) {
    const bridge = document.createElement('div');
    bridge.className = 'crossword-bridge' + (tsShowPhonemes ? '' : ' hidden');

    bridgeIndices.forEach(pi => {
        if (intervals[pi] && !intervals[pi].geminate_end) {
            bridge.appendChild(createPhonemeElement(intervals[pi], pi));
        }
    });

    return bridge;
}

function buildUnifiedDisplay() {
    unifiedDisplay.innerHTML = '';

    // Build a map: for each interval, which word owns it
    const intervalToWord = new Array(intervals.length).fill(-1);
    words.forEach((word, wi) => {
        if (word.phoneme_indices) {
            word.phoneme_indices.forEach(pi => {
                intervalToWord[pi] = wi;
            });
        }
    });

    // Helper to populate cached DOM refs after building display
    function _cacheDisplayRefs() {
        cachedBlocks = Array.from(unifiedDisplay.querySelectorAll('.mega-block'));
        cachedPhonemes = Array.from(unifiedDisplay.querySelectorAll('.mega-phoneme'));
        cachedLetterEls = Array.from(unifiedDisplay.querySelectorAll('.mega-letter:not(.null-ts)'));
        prevActiveWordIdx = -1;
        prevActivePhonemeIdx = -1;
    }

    // If no words yet, just show phonemes flat
    if (!words.length) {
        intervals.forEach((interval, index) => {
            if (interval.geminate_end) return;
            const phonEl = createPhonemeElement(interval, index);
            phonEl.classList.add('standalone');
            unifiedDisplay.appendChild(phonEl);
        });
        _cacheDisplayRefs();
        return;
    }

    // If no intervals (phones), render words directly
    if (!intervals.length && words.length) {
        words.forEach((word, wi) => {
            const block = document.createElement('div');
            block.className = 'mega-block';
            block.dataset.wordIndex = wi;

            const wordEl = document.createElement('div');
            wordEl.className = 'mega-word';
            wordEl.dir = 'rtl';
            wordEl.textContent = word.display_text || word.text;
            block.appendChild(wordEl);

            const letterRow = createLetterRow(word);
            if (letterRow) block.appendChild(letterRow);

            block.addEventListener('click', () => {
                audio.currentTime = word.start + tsSegOffset;
                updateDisplay();
            });

            unifiedDisplay.appendChild(block);
        });
        _cacheDisplayRefs();
        return;
    }

    // Pre-compute bridges for all word boundaries
    const bridges = [];  // bridges[wi] = bridge BEFORE word wi (between wi-1 and wi)
    for (let wi = 1; wi < words.length; wi++) {
        bridges[wi] = computeBridgeAtBoundary(words[wi - 1], words[wi]);
    }

    // Collect all phoneme indices to exclude per word (moved to bridges)
    const excludeFromWord = words.map(() => new Set());
    for (let wi = 1; wi < words.length; wi++) {
        const b = bridges[wi];
        if (!b) continue;
        b.fromPrev.forEach(pi => excludeFromWord[wi - 1].add(pi));
        b.fromCurr.forEach(pi => excludeFromWord[wi].add(pi));
    }

    // Walk through intervals, grouping by word
    let i = 0;
    const renderedWords = new Set();
    while (i < intervals.length) {
        const wi = intervalToWord[i];

        if (wi === -1) {
            i++;
            continue;
        }

        if (renderedWords.has(wi)) {
            i++;
            continue;
        }
        renderedWords.add(wi);

        const word = words[wi];

        // Render bridge BEFORE this word's block (if any)
        if (wi > 0 && bridges[wi]) {
            const b = bridges[wi];
            const allBridgeIndices = [...b.fromPrev, ...b.fromCurr];
            if (allBridgeIndices.length > 0) {
                unifiedDisplay.appendChild(createCrosswordBridge(allBridgeIndices));
            }
        }

        // Build mega-block
        const block = document.createElement('div');
        block.className = 'mega-block';
        block.dataset.wordIndex = wi;

        const wordEl = document.createElement('div');
        wordEl.className = 'mega-word';
        wordEl.dir = 'rtl';
        wordEl.textContent = word.display_text || word.text;
        block.appendChild(wordEl);

        const letterRow = createLetterRow(word);
        if (letterRow) block.appendChild(letterRow);

        // Phoneme row — exclude phonemes moved to bridges
        const phoneRow = document.createElement('div');
        phoneRow.className = 'mega-phonemes' + (tsShowPhonemes ? '' : ' hidden');

        const indices = word.phoneme_indices || [];
        const excluded = excludeFromWord[wi];
        indices.forEach(pi => {
            if (excluded.has(pi)) return;
            if (intervals[pi] && !intervals[pi].geminate_end) {
                phoneRow.appendChild(createPhonemeElement(intervals[pi], pi));
            }
        });

        block.appendChild(phoneRow);

        block.addEventListener('click', () => {
            audio.currentTime = word.start + tsSegOffset;
            updateDisplay();
        });

        unifiedDisplay.appendChild(block);

        while (i < intervals.length && intervalToWord[i] === wi) {
            i++;
        }
    }

    _cacheDisplayRefs();
}

function createPhonemeElement(interval, index) {
    const el = document.createElement('span');
    el.className = 'mega-phoneme';
    el.dataset.index = index;

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
        audio.currentTime = interval.start + tsSegOffset;
        updateDisplay();
    });

    return el;
}

function createLetterRow(word) {
    const letters = word.letters || [];
    if (!letters.length) return null;

    const row = document.createElement('div');
    row.className = 'mega-letters' + (tsShowLetters ? '' : ' hidden');

    // Group consecutive letters with identical (start, end) into one box
    const groups = [];
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
            el.dataset.letterStart = group.start;
            el.dataset.letterEnd = group.end;
            el.addEventListener('click', e => {
                e.stopPropagation();
                audio.currentTime = group.start + tsSegOffset;
                updateDisplay();
            });
        }
        row.appendChild(el);
    });

    return row;
}

function buildPhonemeLabels() {
    phonemeLabels.innerHTML = '';
    cachedLabels = [];
}

// ---------------------------------------------------------------------------
// Waveform decoding (segment slice)
// ---------------------------------------------------------------------------

async function decodeWaveform(url) {
    if (!url) return;
    try {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        let audioBuffer;
        if (audioBufferCache.has(url)) {
            audioBuffer = audioBufferCache.get(url);
        } else {
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
            // Evict oldest if cache exceeds 5 entries
            if (audioBufferCache.size >= 5) {
                const oldest = audioBufferCache.keys().next().value;
                audioBufferCache.delete(oldest);
            }
            audioBufferCache.set(url, audioBuffer);
        }
        fullAudioBuffer = audioBuffer;

        // Extract segment slice from the full audio
        const rawData = audioBuffer.getChannelData(0);
        const sampleRate = audioBuffer.sampleRate;
        const startSample = Math.floor(tsSegOffset * sampleRate);
        const endSample = Math.min(Math.floor(tsSegEnd * sampleRate), rawData.length);
        const sliceLength = endSample - startSample;

        if (sliceLength <= 0) {
            // Fallback: use entire buffer if no valid segment offset
            computePeaks(rawData);
            return;
        }

        const slice = rawData.subarray(startSample, endSample);
        computePeaks(slice);
    } catch (e) {
        console.error('Waveform decode failed:', e);
        waveformData = null;
    }
}

function computePeaks(rawData) {
    const buckets = canvas.width || 1200;
    const blockSize = Math.max(1, Math.floor(rawData.length / buckets));
    const peaks = new Float32Array(buckets * 2); // [min0, max0, min1, max1, ...]

    for (let i = 0; i < buckets; i++) {
        let min = 1.0, max = -1.0;
        const start = i * blockSize;
        for (let j = 0; j < blockSize; j++) {
            const val = rawData[start + j] || 0;
            if (val < min) min = val;
            if (val > max) max = val;
        }
        peaks[i * 2] = min;
        peaks[i * 2 + 1] = max;
    }

    waveformData = peaks;
    cacheWaveformSnapshot();
}

// ---------------------------------------------------------------------------
// Canvas drawing
// ---------------------------------------------------------------------------

function cacheWaveformSnapshot() {
    drawVisualization();
    if (!canvas.width || !canvas.height) return;
    if (!waveformSnapshot) {
        waveformSnapshot = document.createElement('canvas');
    }
    waveformSnapshot.width = canvas.width;
    waveformSnapshot.height = canvas.height;
    waveformSnapshot.getContext('2d').drawImage(canvas, 0, 0);
}

function drawVisualization() {
    if (!canvas.width || !canvas.height) return;

    const width = canvas.width;
    const height = canvas.height;
    const duration = getSegDuration();
    const waveH = height - 30;
    const centerY = waveH / 2;

    // Clear canvas
    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    // Draw phoneme boundaries (gray, thin)
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;

    intervals.forEach(interval => {
        const x = (interval.start / duration) * width;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, waveH);
        ctx.stroke();
    });

    // Draw word boundaries (gold, thicker)
    ctx.strokeStyle = '#f0a500';
    ctx.lineWidth = 2;

    words.forEach(word => {
        const x = (word.start / duration) * width;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, waveH);
        ctx.stroke();
    });

    // Draw waveform
    if (waveformData) {
        const buckets = waveformData.length / 2;
        const scale = waveH / 2 * 0.95;

        // Filled waveform shape
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = waveformData[i * 2 + 1];
            const y = centerY - maxVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        for (let i = buckets - 1; i >= 0; i--) {
            const x = (i / buckets) * width;
            const minVal = waveformData[i * 2];
            const y = centerY - minVal * scale;
            ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
        ctx.fill();

        // Waveform outline
        ctx.strokeStyle = '#4361ee';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = waveformData[i * 2 + 1];
            const y = centerY - maxVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const minVal = waveformData[i * 2];
            const y = centerY - minVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
    }
}

// ---------------------------------------------------------------------------
// Animation & display update
// ---------------------------------------------------------------------------

let animationId = null;

function startAnimation() {
    animate();
}

function stopAnimation() {
    if (animationId) {
        cancelAnimationFrame(animationId);
        animationId = null;
    }
}

function animate() {
    updateDisplay();
    animationId = requestAnimationFrame(animate);
}

function updateDisplay() {
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Update animation view if active
    if (tsViewMode === 'animation') {
        updateAnimationDisplay(time);
    }

    // Find current phoneme
    let currentIndex = -1;
    for (let i = 0; i < intervals.length; i++) {
        if (time >= intervals[i].start && time < intervals[i].end) {
            if (intervals[i].geminate_end) {
                currentIndex = i - 1;
            } else {
                currentIndex = i;
            }
            break;
        }
    }

    // Find current word
    let currentWordIndex = -1;
    for (let i = 0; i < words.length; i++) {
        if (time >= words[i].start && time < words[i].end) {
            currentWordIndex = i;
            break;
        }
    }

    // Update unified display highlighting — use cached refs, diff-only updates
    if (currentWordIndex !== prevActiveWordIdx) {
        for (const block of cachedBlocks) {
            const wi = parseInt(block.dataset.wordIndex);
            block.classList.remove('active', 'past');
            if (wi === currentWordIndex) {
                block.classList.add('active');
                block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else if (currentWordIndex >= 0 && wi < currentWordIndex) {
                block.classList.add('past');
            }
        }
        prevActiveWordIdx = currentWordIndex;
    }

    // Update individual phoneme highlighting — only on change
    if (currentIndex !== prevActivePhonemeIdx) {
        for (const ph of cachedPhonemes) {
            ph.classList.toggle('active', parseInt(ph.dataset.index) === currentIndex);
        }
        cachedLabels.forEach((label, i) => {
            label.classList.toggle('active', i === currentIndex);
        });
        prevActivePhonemeIdx = currentIndex;
    }

    // Update letter highlighting (time-based, must check each frame)
    for (const el of cachedLetterEls) {
        const s = parseFloat(el.dataset.letterStart);
        const e = parseFloat(el.dataset.letterEnd);
        el.classList.toggle('active', time >= s && time < e);
    }

    // Redraw canvas with playhead
    drawVisualizationWithPlayhead(time / duration);
}

function drawVisualizationWithPlayhead(progress) {
    if (waveformSnapshot && waveformSnapshot.width) {
        ctx.drawImage(waveformSnapshot, 0, 0);
    } else {
        drawVisualization();
    }

    const width = canvas.width;
    const height = canvas.height - 30;
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Draw current word highlight (subtle gold)
    for (let i = 0; i < words.length; i++) {
        if (time >= words[i].start && time < words[i].end) {
            const startX = (words[i].start / duration) * width;
            const endX = (words[i].end / duration) * width;

            ctx.fillStyle = 'rgba(240, 165, 0, 0.1)';
            ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw current phoneme highlight (blue)
    for (let i = 0; i < intervals.length; i++) {
        if (time >= intervals[i].start && time < intervals[i].end) {
            const startX = (intervals[i].start / duration) * width;
            const endX = (intervals[i].end / duration) * width;

            ctx.fillStyle = 'rgba(76, 201, 240, 0.2)';
            ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw playhead
    const x = progress * width;
    ctx.strokeStyle = '#f72585';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Draw playhead triangle
    ctx.fillStyle = '#f72585';
    ctx.beginPath();
    ctx.moveTo(x - 6, 0);
    ctx.lineTo(x + 6, 0);
    ctx.lineTo(x, 10);
    ctx.closePath();
    ctx.fill();
}

// ---------------------------------------------------------------------------
// Canvas click & keyboard
// ---------------------------------------------------------------------------

function handleCanvasClick(e) {
    if (!audio.duration) return;

    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const progress = x / canvas.width;

    // Map canvas position to absolute audio time within segment bounds
    const segDuration = getSegDuration();
    const targetRelTime = progress * segDuration;
    audio.currentTime = targetRelTime + tsSegOffset;
    updateDisplay();
}

function handleKeydown(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (activeTab !== 'timestamps') return;

    switch (e.code) {
        case 'Space':
            e.preventDefault();
            if (audio.paused) {
                // If at/past segment end, restart from segment start
                if (tsSegEnd > 0 && audio.currentTime >= tsSegEnd) {
                    audio.currentTime = tsSegOffset;
                }
                audio.play();
            } else {
                audio.pause();
            }
            break;

        case 'ArrowLeft':
            e.preventDefault();
            audio.currentTime = Math.max(tsSegOffset, audio.currentTime - 3);
            updateDisplay();
            break;

        case 'ArrowRight':
            e.preventDefault();
            audio.currentTime = Math.min(tsSegEnd || audio.duration, audio.currentTime + 3);
            updateDisplay();
            break;

        case 'ArrowUp': {
            e.preventDefault();
            const time = audio.currentTime - tsSegOffset;
            let prevStart = null;
            for (let i = words.length - 1; i >= 0; i--) {
                if (words[i].start < time - 0.01) {
                    prevStart = words[i].start;
                    break;
                }
            }
            if (prevStart !== null) {
                audio.currentTime = prevStart + tsSegOffset;
            } else {
                audio.currentTime = tsSegOffset;
            }
            updateDisplay();
            break;
        }

        case 'ArrowDown': {
            e.preventDefault();
            const time = audio.currentTime - tsSegOffset;
            let nextStart = null;
            for (let i = 0; i < words.length; i++) {
                if (words[i].start > time + 0.01) {
                    nextStart = words[i].start;
                    break;
                }
            }
            if (nextStart !== null) {
                audio.currentTime = nextStart + tsSegOffset;
            } else {
                audio.currentTime = tsSegEnd || audio.duration;
            }
            updateDisplay();
            break;
        }

        case 'Period': // > speed up
        case 'Comma': { // < speed down
            e.preventDefault();
            const opts = Array.from(tsSpeedSelect.options).map(o => parseFloat(o.value));
            const curRate = parseFloat(tsSpeedSelect.value);
            const curIdx = opts.findIndex(s => Math.abs(s - curRate) < 0.01);
            const idx = curIdx === -1 ? opts.indexOf(1) : curIdx;
            const newIdx = e.code === 'Period'
                ? Math.min(idx + 1, opts.length - 1)
                : Math.max(idx - 1, 0);
            tsSpeedSelect.value = opts[newIdx];
            audio.playbackRate = opts[newIdx];
            break;
        }

        case 'KeyJ': {
            e.preventDefault();
            if (tsViewMode === 'animation') {
                const cache = tsGranularity === 'characters' ? animCharCache : animWordCache;
                if (cache && lastAnimIdx >= 0 && lastAnimIdx < cache.length) {
                    cache[lastAnimIdx].el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            } else {
                const activeBlock = unifiedDisplay.querySelector('.mega-block.active');
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
                loadRandomTimestamp(tsReciterSelect.value || null); // current reciter
            }
            break;

        case 'KeyA': {
            e.preventDefault();
            const newMode = tsViewMode === 'analysis' ? 'animation' : 'analysis';
            switchView(newMode);
            document.querySelectorAll('.ts-view-btn').forEach(b => {
                b.classList.toggle('active', b.dataset.view === newMode);
            });
            break;
        }

        case 'KeyL':
            e.preventDefault();
            modeBtnA.click();
            break;

        case 'KeyP':
            e.preventDefault();
            modeBtnB.click();
            break;

        case 'BracketLeft':
            navigateVerse(-1);
            break;

        case 'BracketRight':
            navigateVerse(+1);
            break;
    }
}

// ---------------------------------------------------------------------------
// Animation view: Reveal-mode engine
// ---------------------------------------------------------------------------

const ZWSP = '\u2060';        // Word Joiner
const DAGGER_ALEF = '\u0670'; // Superscript Alef
const CHAR_EQUIVALENTS = new Map([
    ['\u0649', '\u064A'],  // Alef Maksura → Yaa
    ['\u064A', '\u0649'],  // Yaa → Alef Maksura
]);

/** Extract first non-combining base character after NFD normalization. */
function firstBase(s) {
    const nfd = s.normalize('NFD');
    for (const ch of nfd) {
        if (!isCombiningMark(ch.codePointAt(0))) return ch;
    }
    return s[0] || '';
}

/** Fuzzy match between an MFA letter char and a display char group. */
function charsMatch(mfaChar, displayChar) {
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
 * Port of quran_multi_aligner/src/ui/segments.py:split_into_char_groups()
 */
function splitIntoCharGroups(text) {
    const groups = [];
    let current = '';
    for (const ch of text) {
        const cp = ch.codePointAt(0);
        if (cp === 0x0640 || cp === 0x2060) {
            // Tatweel / Word Joiner: fold into current group
            current += ch;
        } else if (cp === 0x0654 || cp === 0x0655) {
            // Hamza above/below: start own group
            if (current) groups.push(current);
            current = ch;
        } else if (isCombiningMark(cp) && cp !== 0x0670) {
            // Combining mark (not dagger alef): fold into current group
            current += ch;
        } else {
            if (current) groups.push(current);
            current = ch;
        }
    }
    if (current) groups.push(current);
    return groups;
}

/** Check if codepoint is a Unicode combining mark (category M). */
function isCombiningMark(cp) {
    // Arabic combining marks: U+0610-U+061A, U+064B-U+065F, U+0670,
    // U+06D6-U+06DC, U+06DF-U+06E4, U+06E7-U+06E8, U+06EA-U+06ED
    // General combining: U+0300-U+036F (combining diacriticals)
    // Also U+FE20-U+FE2F (combining half marks)
    if (cp >= 0x0300 && cp <= 0x036F) return true;
    if (cp >= 0x0610 && cp <= 0x061A) return true;
    if (cp >= 0x064B && cp <= 0x065F) return true;
    if (cp === 0x0670) return true;
    if (cp >= 0x06D6 && cp <= 0x06DC) return true;
    if (cp >= 0x06DF && cp <= 0x06E4) return true;
    if (cp >= 0x06E7 && cp <= 0x06E8) return true;
    if (cp >= 0x06EA && cp <= 0x06ED) return true;
    if (cp >= 0x08D3 && cp <= 0x08FF) return true;  // Arabic extended-A marks
    if (cp >= 0xFE20 && cp <= 0xFE2F) return true;
    return false;
}

/** Build animation display DOM from words array. */
function buildAnimationDisplay() {
    animDisplay.innerHTML = '';
    if (!words.length) return;

    let groupIdCounter = 0;

    words.forEach((word, wi) => {
        if (wi > 0) {
            // Space between words for natural Arabic line wrapping
            animDisplay.appendChild(document.createTextNode(' '));
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
                    // No match — use word timing as fallback
                    charSpans[di].el.dataset.start = word.start;
                    charSpans[di].el.dataset.end = word.end;
                }
            } else {
                // Exhausted MFA letters — use word timing
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
            audio.currentTime = word.start + tsSegOffset;
            updateDisplay();
        });

        animDisplay.appendChild(wordSpan);
    });

    // Merge group IDs for chars with identical start+end across ALL words
    const allChars = animDisplay.querySelectorAll('.anim-char');
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
function initAnimCache(container, selector) {
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
function applyAnimClass(cache, idx, className, add) {
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
function applyAnimOpacity(cache, idx, opacity) {
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
function applyRevealOpacity(cache, newIdx, prevIdx) {
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
function updateAnimationDisplay(time) {
    const cache = tsGranularity === 'characters' ? animCharCache : animWordCache;
    if (!cache || cache.length === 0) return;

    // Fast-path tick: check current -> next -> full scan
    let newIdx = -1;
    if (lastAnimIdx >= 0 && lastAnimIdx < cache.length &&
        time >= cache[lastAnimIdx].start && time < cache[lastAnimIdx].end) {
        newIdx = lastAnimIdx;
    } else if (lastAnimIdx + 1 < cache.length &&
        time >= cache[lastAnimIdx + 1].start && time < cache[lastAnimIdx + 1].end) {
        newIdx = lastAnimIdx + 1;
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

    if (newIdx !== lastAnimIdx) {
        // Remove active from old
        if (lastAnimIdx >= 0 && lastAnimIdx < cache.length) {
            applyAnimClass(cache, lastAnimIdx, 'active', false);
            applyAnimClass(cache, lastAnimIdx, 'reached', true);
        }
        // Add active to new
        if (newIdx >= 0) {
            applyAnimClass(cache, newIdx, 'active', true);
            // First highlight: catch up skipped elements
            if (lastAnimIdx === -1) {
                for (let j = 0; j < newIdx; j++) {
                    applyAnimClass(cache, j, 'reached', true);
                }
            }
            applyRevealOpacity(cache, newIdx, lastAnimIdx);

            // Scroll active element into view
            cache[newIdx].el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        lastAnimIdx = newIdx;
    }
}

/** Switch between analysis and animation views. */
function switchView(mode) {
    tsViewMode = mode;
    unifiedDisplay.style.display = (mode === 'animation') ? 'none' : '';
    animDisplay.hidden = (mode === 'analysis');

    if (mode === 'analysis') {
        // Reset to analysis defaults: Letters on, Phonemes off
        modeBtnA.textContent = 'Letters';
        modeBtnB.textContent = 'Phonemes';
        tsShowLetters = true;
        tsShowPhonemes = false;
        modeBtnA.classList.add('active');
        modeBtnB.classList.remove('active');
        unifiedDisplay.querySelectorAll('.mega-letters').forEach(el => el.classList.remove('hidden'));
        unifiedDisplay.querySelectorAll('.mega-phonemes').forEach(el => el.classList.add('hidden'));
        unifiedDisplay.querySelectorAll('.crossword-bridge').forEach(el => el.classList.add('hidden'));
    } else {
        // Animation defaults: Labels = Words / Characters, Words active only
        modeBtnA.textContent = 'Words';
        modeBtnB.textContent = 'Letters';
        tsGranularity = 'words';
        modeBtnA.classList.add('active');
        modeBtnB.classList.remove('active');
    }

    if (mode === 'animation' && words.length) {
        rebuildAnimationView();
        updateAnimationDisplay(getSegRelTime());
    }
}

/** Rebuild animation view DOM and caches. */
function rebuildAnimationView() {
    buildAnimationDisplay();
    animWordCache = initAnimCache(animDisplay, '.anim-word');
    animCharCache = initAnimCache(animDisplay, '.anim-char');
    lastAnimIdx = -1;
    animDisplay.classList.toggle('anim-chars', tsGranularity === 'characters');
}

/** Switch between word and character granularity. */
function switchGranularity(gran) {
    tsGranularity = gran;
    // Clear all highlights
    animDisplay.querySelectorAll('.anim-word, .anim-char').forEach(el => {
        el.classList.remove('active', 'reached');
        el.style.removeProperty('opacity');
    });
    // Toggle anim-chars class
    animDisplay.classList.toggle('anim-chars', gran === 'characters');
    lastAnimIdx = -1;
    // Reapply at current position
    updateAnimationDisplay(getSegRelTime());
}

// ---------------------------------------------------------------------------

function formatTime(seconds) {
    if (!isFinite(seconds)) return '0:00';

    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

