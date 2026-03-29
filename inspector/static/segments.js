/**
 * Segments Tab — visualize VAD-aligned segment data from extract_segments.py.
 */

// State
let segData = null;          // { audio_url, summary, verse_word_counts, segments } — chapter-specific
let segAllData = null;       // { segments, audio_by_chapter, verse_word_counts } — reciter-level
let segActiveFilters = [];   // [{ field, op, value }, ...]
let segAvgSpeechRate = 0;    // computed from currently visible segments
let segAudioCtx = null;      // AudioContext for waveform decoding
let segAudioBuffer = null;   // decoded full-chapter audio buffer
let segAudioBufferUrl = '';  // URL of the currently decoded audio buffer
let segAnimId = null;        // animation frame ID for playback
let segCurrentIdx = -1;      // currently playing segment index
let segDisplayedSegments = null; // segments currently shown (may be filtered)
let segDirtyMap = new Map();     // Map<chapter, {indices: Set, structural: boolean}> — all unsaved edits
let segEditMode = null;          // null | 'trim' | 'split'
let segEditIndex = -1;           // index of segment being edited
// (merge is now button-driven, no merge selection state needed)
let segAudioBuffers = new Map();  // chapter → AudioBuffer for multi-chapter waveform support
let _segPrefetchCache = {};      // url → Promise<void> for prefetched audio
let _segContinuousPlay = false;  // true while continuous playback is active across audio files
let _segPlayEndMs = 0;           // time_end (ms) of the currently playing displayed segment
let segValidation = null;        // cached validation data for current reciter
let segAllReciters = [];         // full list from /api/seg/reciters
let segStatsData = null;         // cached stats data for current reciter
let _segFilterDebounceTimer = null; // debounce timer for filter value input
let _activeAudioSource = null;      // 'main' | 'error' | null — which audio is active
let _segIndexMap = null;         // Map<index, segment> for O(1) lookups
let _waveformObserver = null;    // IntersectionObserver for lazy waveform drawing
let _segSavedFilterView = null;  // { filters, chapter, verse, scrollTop } — saved when "Go To" from filter results
let segPeaksByAudio = null;      // {url: {duration_ms, peaks}} from server — instant waveforms
let _peaksPollTimer = null;      // setTimeout handle for peaks polling
let _scrollAbortController = null;  // AbortController for in-flight audio preloads
let _scrollDebounceTimer = null;    // 1s debounce timer for scroll-based preloading
let _scrollListeners = [];          // [{el, handler}] for cleanup

// ---------------------------------------------------------------------------
// Edit history — operation log (sent with save payload)
// ---------------------------------------------------------------------------
let segOpLog = new Map();   // Map<chapter, Array<operation>>
let _pendingOp = null;      // stashed op for multi-step edits (trim, split, ref edit)

function createOp(opType, { contextCategory = null, fixKind = 'manual' } = {}) {
    return {
        op_id: crypto.randomUUID(),
        op_type: opType,
        op_context_category: contextCategory,
        fix_kind: fixKind,
        started_at_utc: new Date().toISOString(),
        applied_at_utc: null,
        ready_at_utc: null,
        targets_before: [],
        targets_after: [],
    };
}

function snapshotSeg(seg) {
    return {
        segment_uid: seg.segment_uid || null,
        index_at_save: seg.index,
        audio_url: seg.audio_url || null,
        time_start: seg.time_start,
        time_end: seg.time_end,
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        confidence: seg.confidence ?? 0,
    };
}

function finalizeOp(chapter, op) {
    op.ready_at_utc = new Date().toISOString();
    if (!segOpLog.has(chapter)) segOpLog.set(chapter, []);
    segOpLog.get(chapter).push(op);
    _pendingOp = null;
}

// ---------------------------------------------------------------------------
// Dirty-state helpers
// ---------------------------------------------------------------------------

function markDirty(chapter, index, structural = false) {
    if (!segDirtyMap.has(chapter)) {
        segDirtyMap.set(chapter, { indices: new Set(), structural: false });
    }
    const entry = segDirtyMap.get(chapter);
    if (index !== undefined) entry.indices.add(index);
    if (structural) entry.structural = true;
    segSaveBtn.disabled = false;
}

function unmarkDirty(chapter, index) {
    const entry = segDirtyMap.get(chapter);
    if (!entry) return;
    entry.indices.delete(index);
    if (entry.indices.size === 0 && !entry.structural) {
        segDirtyMap.delete(chapter);
    }
}

function isDirty() {
    return segDirtyMap.size > 0;
}

function isIndexDirty(chapter, index) {
    const entry = segDirtyMap.get(chapter);
    return entry ? entry.indices.has(index) : false;
}

// Filter constants
const SEG_FILTER_FIELDS = [
    { value: 'duration_s',         label: 'Duration (s)',        type: 'float' },
    { value: 'num_words',          label: 'Word count',          type: 'int'   },
    { value: 'num_verses',         label: 'Verses spanned',      type: 'int'   },
    { value: 'confidence_pct',     label: 'Confidence (%)',      type: 'float' },
    { value: 'speech_rate_factor', label: 'Speech rate (× avg)', type: 'float' },
    { value: 'silence_after_ms',  label: 'Silence after (ms)',   type: 'float', neighbour: true },
];
const SEG_FILTER_OPS = ['>', '>=', '<', '<=', '='];

// DOM refs
const segReciterSelect = document.getElementById('seg-reciter-select');
const segChapterSelect = document.getElementById('seg-chapter-select');
const segVerseSelect = document.getElementById('seg-verse-select');
const segListEl = document.getElementById('seg-list');
const segAudioEl = document.getElementById('seg-audio-player');
const segPlayBtn = document.getElementById('seg-play-btn');
const segSpeedSelect = document.getElementById('seg-speed-select');
const segSaveBtn = document.getElementById('seg-save-btn');
const segUndoBtn = document.getElementById('seg-undo-btn');
const segPlayStatus = document.getElementById('seg-play-status');
const segValidationGlobalEl = document.getElementById('seg-validation-global');
const segValidationEl = document.getElementById('seg-validation');
const segStatsPanel     = document.getElementById('seg-stats-panel');
const segStatsCharts    = document.getElementById('seg-stats-charts');
const segFilterBarEl    = document.getElementById('seg-filter-bar');
const segFilterRowsEl   = document.getElementById('seg-filter-rows');
const segFilterAddBtn   = document.getElementById('seg-filter-add-btn');
const segFilterClearBtn = document.getElementById('seg-filter-clear-btn');
const segFilterCountEl  = document.getElementById('seg-filter-count');
const segFilterStatusEl = document.getElementById('seg-filter-status');

// Edit history viewer state
let segHistoryData = null;
const segHistoryView    = document.getElementById('seg-history-view');
const segHistoryBtn     = document.getElementById('seg-history-btn');
const segHistoryBackBtn = document.getElementById('seg-history-back-btn');
const segHistoryStats   = document.getElementById('seg-history-stats');
const segHistoryBatches = document.getElementById('seg-history-batches');

const EDIT_OP_LABELS = {
    trim_segment: 'Boundary adjustment', split_segment: 'Split',
    merge_segments: 'Merge', delete_segment: 'Deletion',
    edit_reference: 'Reference edit', confirm_reference: 'Reference confirmation',
    auto_fix_missing_word: 'Auto-fix missing word', ignore_issue: 'Ignored issue',
    waqf_sakt: 'Waqf sakt merge', remove_sadaqa: 'Remove Sadaqa',
};

// SearchableSelect instance for segments chapter dropdown
let segChapterSS = null;

// Init
document.addEventListener('DOMContentLoaded', async () => {
    segReciterSelect.addEventListener('change', onSegReciterChange);
    segChapterSelect.addEventListener('change', onSegChapterChange);
    segVerseSelect.addEventListener('change', applyFiltersAndRender);
    segPlayBtn.addEventListener('click', onSegPlayClick);
    segSaveBtn.addEventListener('click', onSegSaveClick);
    segUndoBtn.addEventListener('click', onSegUndoClick);
    segSpeedSelect.addEventListener('change', () => {
        const rate = parseFloat(segSpeedSelect.value);
        segAudioEl.playbackRate = rate;
        if (valCardAudio) valCardAudio.playbackRate = rate;
    });

    segAudioEl.addEventListener('play', startSegAnimation);
    segAudioEl.addEventListener('pause', stopSegAnimation);
    segAudioEl.addEventListener('ended', onSegAudioEnded);
    segAudioEl.addEventListener('timeupdate', onSegTimeUpdate);

    document.addEventListener('keydown', handleSegKeydown);

    segFilterAddBtn.addEventListener('click', addSegFilterCondition);
    segFilterClearBtn.addEventListener('click', clearAllSegFilters);

    segHistoryBtn.addEventListener('click', showHistoryView);
    segHistoryBackBtn.addEventListener('click', hideHistoryView);

    // Delegated event listeners for segment card actions — shared across main, error & history sections
    [segListEl, segValidationEl, segValidationGlobalEl, segHistoryView].forEach(el => {
        el.addEventListener('click', handleSegRowClick);
    });

    // Load display config
    try {
        const cfgResp = await fetch('/api/seg/config');
        if (cfgResp.ok) {
            const cfg = await cfgResp.json();
            const root = document.documentElement.style;
            if (cfg.seg_font_size) root.setProperty('--seg-font-size', cfg.seg_font_size);
            if (cfg.seg_word_spacing) root.setProperty('--seg-word-spacing', cfg.seg_word_spacing);
        }
    } catch (_) { /* use CSS defaults */ }

    await surahInfoReady;
    segChapterSS = new SearchableSelect(segChapterSelect);
    loadSegReciters();
});


// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadSegReciters() {
    try {
        const resp = await fetch('/api/seg/reciters');
        segAllReciters = await resp.json();
        filterAndRenderReciters();
    } catch (e) {
        console.error('Error loading seg reciters:', e);
    }
}

function filterAndRenderReciters() {
    segReciterSelect.innerHTML = '<option value="">-- select --</option>';
    clearSegDisplay();

    // Group by audio_source
    const grouped = {};  // source -> [reciter, ...]
    const uncategorized = [];

    for (const r of segAllReciters) {
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
        segReciterSelect.appendChild(optgroup);
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
        segReciterSelect.appendChild(optgroup);
    }
}

async function onSegReciterChange() {
    const reciter = segReciterSelect.value;
    segChapterSelect.innerHTML = '<option value="">-- select --</option>';
    if (segChapterSS) segChapterSS.refresh();
    segVerseSelect.innerHTML = '<option value="">All</option>';
    clearSegDisplay();
    segUndoBtn.hidden = true;
    // Hide validation, stats, and history when reciter changes
    segValidationGlobalEl.hidden = true;
    segValidationGlobalEl.innerHTML = '';
    segValidationEl.hidden = true;
    segValidationEl.innerHTML = '';
    segValidation = null;
    segStatsPanel.hidden = true;
    segStatsPanel.removeAttribute('open');
    segStatsData = null;
    segHistoryView.hidden = true;
    segHistoryBtn.hidden = true;
    segHistoryStats.innerHTML = '';
    segHistoryBatches.innerHTML = '';
    segHistoryData = null;
    if (!reciter) return;

    try {
        const resp = await fetch(`/api/seg/chapters/${reciter}`);
        const chapters = await resp.json();
        chapters.forEach(ch => {
            const opt = document.createElement('option');
            opt.value = ch;
            opt.textContent = surahOptionText(ch);
            segChapterSelect.appendChild(opt);
        });
        if (segChapterSS) segChapterSS.refresh();
    } catch (e) {
        console.error('Error loading chapters:', e);
    }

    // Fetch validation, stats, all segments, and edit history in parallel
    const [valResult, statsResult, allResult, histResult] = await Promise.allSettled([
        fetch(`/api/seg/validate/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/stats/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/all/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/edit-history/${reciter}`).then(r => r.ok ? r.json() : null),
    ]);

    if (valResult.status === 'fulfilled') {
        segValidation = valResult.value;
        renderValidationPanel(segValidation);
    } else {
        console.error('Error loading validation:', valResult.reason);
    }

    if (statsResult.status === 'fulfilled') {
        segStatsData = statsResult.value;
        if (!segStatsData.error) renderStatsPanel(segStatsData);
    } else {
        console.error('Error loading stats:', statsResult.reason);
    }

    if (allResult.status === 'fulfilled') {
        segAllData = allResult.value;
        computeSilenceAfter();
        if (segFilterBarEl) segFilterBarEl.hidden = false;
        applyFiltersAndRender();
        // Start fetching waveform peaks (non-blocking)
        _fetchPeaks(reciter);
    } else {
        console.error('Error loading all segments:', allResult.reason);
    }

    if (histResult.status === 'fulfilled' && histResult.value) {
        segHistoryData = histResult.value;
        renderEditHistoryPanel(segHistoryData);
    }
}

async function onSegChapterChange() {
    const reciter = segReciterSelect.value;
    const chapter = segChapterSelect.value;
    segVerseSelect.innerHTML = '<option value="">All</option>';

    // Clear audio/waveform state
    segAudioBuffer = null;
    segAudioBufferUrl = '';
    segAudioEl.src = '';
    segPlayBtn.disabled = true;
    stopSegAnimation();
    // Abort in-flight audio preloads (peaks and buffers persist across chapters)
    if (_scrollAbortController) _scrollAbortController.abort();

    // Stats panel: leave open/closed state as user left it

    // Update validation panel chapter filter (deferred to avoid blocking segment render)
    if (segValidation) {
        requestAnimationFrame(() => {
            const globalState = captureValPanelState(segValidationGlobalEl);
            const chState = captureValPanelState(segValidationEl);
            const ch = chapter ? parseInt(chapter) : null;
            if (ch !== null) {
                renderValidationPanel(segValidation, null, segValidationGlobalEl, 'All Chapters');
                renderValidationPanel(segValidation, ch, segValidationEl, `Chapter ${ch}`);
                restoreValPanelState(segValidationGlobalEl, globalState);
                restoreValPanelState(segValidationEl, chState);
            } else {
                segValidationGlobalEl.hidden = true;
                segValidationGlobalEl.innerHTML = '';
                renderValidationPanel(segValidation, null, segValidationEl);
                restoreValPanelState(segValidationEl, chState);
            }
        });
    }

    // Re-compute avg speech rate and re-render (chapter filter changes the set)
    applyFiltersAndRender();

    if (!reciter || !chapter) return;
    segPlayBtn.disabled = false;  // Enable early — playFromSegment loads audio on demand

    // Fetch chapter-specific audio URL + summary (reuse existing endpoint)
    try {
        const resp = await fetch(`/api/seg/data/${reciter}/${chapter}`);
        segData = await resp.json();
        if (segData.error) return;

        // Populate verse filter from segAllData (not segData.segments)
        const verses = new Set();
        (segAllData?.segments || [])
            .filter(s => s.chapter === parseInt(chapter) && s.matched_ref)
            .forEach(s => {
                const start = s.matched_ref.split('-')[0]?.split(':');
                if (start?.length >= 2) verses.add(parseInt(start[1]));
            });
        [...verses].sort((a, b) => a - b).forEach(v => {
            const opt = document.createElement('option');
            opt.value = v; opt.textContent = v;
            segVerseSelect.appendChild(opt);
        });

        // Populate segData.segments from segAllData for edit operations
        const chNum = parseInt(chapter);
        segData.segments = (segAllData?.segments || []).filter(s => s.chapter === chNum);

        // Check if all segments share the same audio URL (by_surah) or differ (by_ayah)
        const audioUrls = new Set(
            segData.segments.filter(s => s.audio_url).map(s => s.audio_url)
        );
        const singleAudio = audioUrls.size <= 1;

        if (singleAudio && segData.audio_url) {
            // by_surah: one audio per chapter — load eagerly
            segAudioEl.src = segData.audio_url;
            decodeSegAudio(segData.audio_url).then(() => {
                if (segAudioBuffer) drawAllSegWaveforms();
            });
        }

    } catch (e) {
        console.error('Error loading chapter data:', e);
    }
}

function isCrossVerse(ref) {
    if (!ref) return false;
    const parts = ref.split('-');
    if (parts.length !== 2) return false;
    const startAyah = parts[0].split(':')[1];
    const endAyah = parts[1].split(':')[1];
    return startAyah !== endAyah;
}


// ---------------------------------------------------------------------------
// Derived-property helpers for filtering
// ---------------------------------------------------------------------------

function parseSegRef(ref) {
    if (!ref) return null;
    const parts = ref.split('-');
    if (parts.length !== 2) return null;
    const s = parts[0].split(':'), e = parts[1].split(':');
    if (s.length < 3 || e.length < 3) return null;
    return { surah: +s[0], ayah_from: +s[1], word_from: +s[2], ayah_to: +e[1], word_to: +e[2] };
}

function countSegWords(ref) {
    const p = parseSegRef(ref);
    if (!p) return 0;
    if (p.ayah_from === p.ayah_to) return p.word_to - p.word_from + 1;
    // Cross-verse: use verse_word_counts
    const vwc = segAllData && segAllData.verse_word_counts;
    let total = 0;
    for (let a = p.ayah_from; a <= p.ayah_to; a++) {
        const key = `${p.surah}:${a}`;
        if (a === p.ayah_from)      total += (vwc?.[key] ?? p.word_from) - p.word_from + 1;
        else if (a === p.ayah_to)   total += p.word_to;
        else                        total += vwc?.[key] ?? 0;
    }
    return total;
}

function segDerivedProps(seg) {
    if (seg._derived && seg._derivedAvgRate === segAvgSpeechRate) return seg._derived;
    const duration_s         = (seg.time_end - seg.time_start) / 1000;
    const num_words          = countSegWords(seg.matched_ref);
    const p                  = parseSegRef(seg.matched_ref);
    const num_verses         = p ? p.ayah_to - p.ayah_from + 1 : 0;
    const confidence_pct     = (seg.confidence || 0) * 100;
    const rate               = duration_s > 0 && num_words > 0 ? num_words / duration_s : 0;
    const speech_rate_factor = segAvgSpeechRate > 0 ? rate / segAvgSpeechRate : 0;
    const silence_after_ms = seg.silence_after_ms;
    seg._derived = { duration_s, num_words, num_verses, confidence_pct, speech_rate_factor, silence_after_ms };
    seg._derivedAvgRate = segAvgSpeechRate;
    return seg._derived;
}

function computeAvgSpeechRate(segs) {
    const rates = (segs || [])
        .filter(s => s.matched_ref)
        .map(s => {
            const d = (s.time_end - s.time_start) / 1000;
            const w = countSegWords(s.matched_ref);
            return d > 0 && w > 0 ? w / d : 0;
        }).filter(r => r > 0);
    segAvgSpeechRate = rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : 0;
}

function computeSilenceAfter() {
    if (!segAllData) return;
    const pad = segAllData.pad_ms || 0;
    const segs = segAllData.segments;
    for (let i = 0; i < segs.length; i++) {
        const next = segs[i + 1];
        const sameEntry = next && segs[i].audio_url === next.audio_url
                               && segs[i].entry_idx === next.entry_idx;
        if (sameEntry) {
            segs[i].silence_after_ms = (next.time_start - segs[i].time_end) + 2 * pad;
            segs[i].silence_after_raw_ms = next.time_start - segs[i].time_end;
        } else {
            segs[i].silence_after_ms = null;
            segs[i].silence_after_raw_ms = null;
        }
    }
}

function _compareFilter(actual, op, value) {
    if (actual == null) return false;
    switch (op) {
        case '>':  return actual >  value;
        case '>=': return actual >= value;
        case '<':  return actual <  value;
        case '<=': return actual <= value;
        case '=':  return actual === value;
        default:   return true;
    }
}


// ---------------------------------------------------------------------------
// Filter application
// ---------------------------------------------------------------------------

function applyFiltersAndRender() {
    if (!segAllData) return;
    const chapter = segChapterSelect.value;

    // Check if any filter conditions are active
    const activeValid = segActiveFilters.filter(f => f.value !== null);

    // No chapter and no filters — prompt user instead of loading everything
    if (!chapter && activeValid.length === 0) {
        segDisplayedSegments = [];
        segListEl.innerHTML = '<div class="seg-loading">Select a chapter or add a filter to view segments</div>';
        if (segFilterStatusEl) segFilterStatusEl.textContent = '';
        return;
    }

    let segs = segAllData.segments;

    // 1. Chapter filter (optional — show all chapters when filters are active)
    if (chapter) {
        segs = segs.filter(s => s.chapter === parseInt(chapter));
    }

    // 2. Verse filter (only meaningful when chapter is set)
    const verse = segVerseSelect.value;
    if (verse && chapter) {
        const prefix = `${chapter}:${verse}:`;
        segs = segs.filter(s => s.matched_ref && s.matched_ref.startsWith(prefix));
    }

    // 3. Compute avg speech rate from current chapter/global set (before condition filter)
    computeAvgSpeechRate(segs);

    // 4. Active filter conditions (AND logic; skip conditions with null value)
    // Clear stale neighbour tags
    segAllData.segments.forEach(s => delete s._isNeighbour);

    if (activeValid.length > 0) {
        // First pass: find segments matching ALL filters
        const matched = segs.filter(seg =>
            activeValid.every(f => {
                const actual = segDerivedProps(seg)[f.field];
                return _compareFilter(actual, f.op, f.value);
            })
        );

        // Second pass: if any neighbour-type filter is active, expand with next segment
        const hasNeighbourFilter = activeValid.some(f =>
            SEG_FILTER_FIELDS.find(fd => fd.value === f.field)?.neighbour
        );

        if (hasNeighbourFilter) {
            const posMap = new Map(segs.map((s, i) => [s, i]));
            const resultSet = new Set(matched);
            matched.forEach(seg => {
                const idx = posMap.get(seg);
                const next = segs[idx + 1];
                if (next && next.audio_url === seg.audio_url) {
                    next._isNeighbour = true;
                    resultSet.add(next);
                }
            });
            segs = segs.filter(seg => resultSet.has(seg));

            // Sort by silence duration (shortest first), keeping pairs grouped
            const groups = [];
            for (let i = 0; i < segs.length; i++) {
                if (!segs[i]._isNeighbour) {
                    const group = [segs[i]];
                    if (segs[i + 1] && segs[i + 1]._isNeighbour) {
                        group.push(segs[++i]);
                    }
                    groups.push(group);
                }
            }
            groups.sort((a, b) => (a[0].silence_after_ms ?? Infinity) - (b[0].silence_after_ms ?? Infinity));
            segs = groups.flat();
        } else {
            segs = matched;
        }
    }

    // Update status counter
    const total = chapter
        ? segAllData.segments.filter(s => s.chapter === parseInt(chapter)).length
        : segAllData.segments.length;
    if (segFilterStatusEl) {
        segFilterStatusEl.textContent = (activeValid.length > 0 || verse)
            ? `${segs.length} / ${total}` : '';
    }

    segDisplayedSegments = segs;
    _segIndexMap = new Map(segs.map(s => [`${s.chapter}:${s.index}`, s]));

    // Clear stale "Back to filter results" state when user re-activates filters
    if (activeValid.length > 0 && _segSavedFilterView) {
        _segSavedFilterView = null;
    }

    renderSegList(segDisplayedSegments);
}

/**
 * Get the current chapter's segments from segData (preferred) or segAllData.
 * Falls back gracefully if segData hasn't loaded yet.
 */
function _getChapterSegs() {
    if (segData?.segments?.length) return segData.segments;
    const ch = parseInt(segChapterSelect.value);
    if (ch && segAllData?.segments) return segAllData.segments.filter(s => s.chapter === ch);
    return [];
}

/**
 * Sync segData.segments (chapter-specific edits) back into segAllData.segments.
 * Called after structural changes (split/merge/delete/trim) before re-render.
 */
function syncChapterSegsToAll() {
    if (!segAllData || !segData || !segData.segments) return;
    const chapter = parseInt(segChapterSelect.value);
    if (!chapter) return;
    const other = segAllData.segments.filter(s => s.chapter !== chapter);
    const updated = segData.segments.map(s => ({ ...s, chapter }));
    // Re-insert in chapter order
    const insertIdx = other.findIndex(s => s.chapter > chapter);
    if (insertIdx === -1) {
        segAllData.segments = [...other, ...updated];
    } else {
        segAllData.segments = [
            ...other.slice(0, insertIdx),
            ...updated,
            ...other.slice(insertIdx),
        ];
    }
    segAllData._byChapter = null; segAllData._byChapterIndex = null;  // invalidate chapter lookup cache
}


// ---------------------------------------------------------------------------
// Audio decoding
// ---------------------------------------------------------------------------

async function decodeSegAudio(url) {
    // Mark as loading to prevent scroll preload from double-fetching
    const ch = parseInt(segChapterSelect.value);
    if (ch) segAudioBuffers.set(ch, null);  // sentinel
    try {
        if (!segAudioCtx) {
            segAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        const resp = await fetch(url);
        const buf = await resp.arrayBuffer();
        segAudioBuffer = await segAudioCtx.decodeAudioData(buf);
        segAudioBufferUrl = url;
        // Also cache in per-chapter map
        if (ch) segAudioBuffers.set(ch, segAudioBuffer);
    } catch (e) {
        console.error('Seg audio decode failed:', e);
        segAudioBuffer = null;
        segAudioBufferUrl = '';
        // Remove sentinel so scroll preload can retry
        if (ch && segAudioBuffers.get(ch) === null) segAudioBuffers.delete(ch);
    }
}

/** Decode and cache audio buffer for a specific chapter. Returns the AudioBuffer or null. */
async function ensureChapterAudioBuffer(chapter) {
    const cached = segAudioBuffers.get(chapter);
    if (cached) return cached;  // actual buffer (not null sentinel)
    if (segAudioBuffers.has(chapter)) return null;  // null sentinel = loading in progress, don't duplicate
    const url = segAllData?.audio_by_chapter?.[chapter];
    if (!url) return null;
    try {
        if (!segAudioCtx) {
            segAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        const resp = await fetch(url);
        const buf = await resp.arrayBuffer();
        const decoded = await segAudioCtx.decodeAudioData(buf);
        segAudioBuffers.set(chapter, decoded);
        return decoded;
    } catch (e) {
        console.error(`Audio decode failed for chapter ${chapter}:`, e);
        return null;
    }
}

function _ensureWaveformObserver() {
    if (_waveformObserver) return _waveformObserver;
    _waveformObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const canvas = entry.target;
            const row = canvas.closest('.seg-row');
            if (!row) return;
            const idx = parseInt(row.dataset.segIndex);
            const chapter = parseInt(row.dataset.segChapter);

            // Resolve segment. For history cards, prefer the stored snapshot data
            // (the segment at this index may have different times now).
            let seg;
            if (row.dataset.histTimeStart) {
                seg = {
                    time_start: parseInt(row.dataset.histTimeStart),
                    time_end: parseInt(row.dataset.histTimeEnd),
                    audio_url: row.dataset.histAudioUrl || '',
                    chapter,
                };
            } else {
                seg = (_segIndexMap ? _segIndexMap.get(`${chapter}:${idx}`) : null) || (chapter ? getSegByChapterIndex(chapter, idx) : null);
            }
            if (!seg) return;

            // Peaks fast path — draw from pre-computed peaks without audio download
            if (segPeaksByAudio) {
                const audioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';
                const peaksEntry = segPeaksByAudio[audioUrl];
                if (peaksEntry?.peaks?.length > 0) {
                    drawSegmentWaveformFromPeaks(canvas, seg.time_start, seg.time_end,
                                                  peaksEntry.peaks, peaksEntry.duration_ms);
                    _waveformObserver.unobserve(canvas);
                    canvas.removeAttribute('data-needs-waveform');
                    return;
                }
            }

            // Draw from already-cached audio buffers only — never start fetches here.
            // Audio downloading is handled by the debounced scroll preloader to avoid
            // firing requests for segments that merely scroll through the viewport.
            const currentChapter = parseInt(segChapterSelect.value);
            let buffer = null;

            const chapterAudio = segAllData?.audio_by_chapter?.[String(chapter)] || '';
            const segIsByAyah = seg.audio_url && seg.audio_url !== chapterAudio;

            if (segIsByAyah) {
                // By-ayah: use buffer only if already cached
                buffer = segAudioBuffers.get(seg.audio_url) || null;
                if (!buffer) return;  // scroll preloader will handle downloading
            } else if (chapter && chapter !== currentChapter) {
                // Error card from different chapter
                buffer = segAudioBuffers.get(chapter) || null;
                if (!buffer) return;
            } else {
                // Same-chapter by-surah
                buffer = segAudioBuffer;
                if (!buffer) return;
            }

            // Temporarily swap buffer for drawing if needed
            const savedBuffer = segAudioBuffer;
            segAudioBuffer = buffer;
            drawSegmentWaveform(canvas, seg.time_start, seg.time_end);
            segAudioBuffer = savedBuffer;

            _waveformObserver.unobserve(canvas);
            canvas.removeAttribute('data-needs-waveform');
        });
    }, { rootMargin: '200px' });
    return _waveformObserver;
}

function drawAllSegWaveforms() {
    if (!segAudioBuffer || !segDisplayedSegments) return;
    const observer = _ensureWaveformObserver();
    segListEl.querySelectorAll('canvas[data-needs-waveform]').forEach(canvas => {
        observer.unobserve(canvas);
        observer.observe(canvas);
    });
}


// ---------------------------------------------------------------------------
// Peaks loading + polling
// ---------------------------------------------------------------------------

function _fetchPeaks(reciter, chapters) {
    if (_peaksPollTimer) { clearTimeout(_peaksPollTimer); _peaksPollTimer = null; }
    let url = `/api/seg/peaks/${reciter}`;
    if (chapters && chapters.length > 0) url += `?chapters=${chapters.join(',')}`;
    fetch(url).then(r => r.json()).then(data => {
        if (!segAllData) return;  // reciter changed
        if (!segPeaksByAudio) segPeaksByAudio = {};
        Object.assign(segPeaksByAudio, data.peaks || {});
        _redrawPeaksWaveforms();
        if (!data.complete) {
            _peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

function _redrawPeaksWaveforms() {
    const observer = _ensureWaveformObserver();
    [segListEl, segValidationEl, segValidationGlobalEl, segHistoryView].forEach(container => {
        if (!container) return;
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => {
            // Unobserve then re-observe to force a fresh intersection check
            observer.unobserve(c);
            observer.observe(c);
        });
    });
}


// ---------------------------------------------------------------------------
// Debounced viewport-based audio preloading
// ---------------------------------------------------------------------------

function _attachScrollPreload(container) {
    if (!container) return;
    if (_scrollListeners.some(sl => sl.el === container)) return;  // already tracked

    const handler = () => {
        // Abort in-flight preloads
        if (_scrollAbortController) _scrollAbortController.abort();
        clearTimeout(_scrollDebounceTimer);
        _scrollDebounceTimer = setTimeout(_onScrollSettled, 1000);
    };
    container.addEventListener('scroll', handler, { passive: true });
    _scrollListeners.push({ el: container, handler });

    // Initial preload after short delay (only if not already scheduled)
    if (!_scrollDebounceTimer) {
        _scrollDebounceTimer = setTimeout(_onScrollSettled, 500);
    }
}

function _teardownScrollPreloading() {
    if (_scrollAbortController) { _scrollAbortController.abort(); _scrollAbortController = null; }
    clearTimeout(_scrollDebounceTimer);
    _scrollDebounceTimer = null;
    _scrollListeners.forEach(({ el, handler }) => {
        el.removeEventListener('scroll', handler);
    });
    _scrollListeners = [];
}

function _detachScrollPreload(container) {
    const idx = _scrollListeners.findIndex(sl => sl.el === container);
    if (idx !== -1) {
        container.removeEventListener('scroll', _scrollListeners[idx].handler);
        _scrollListeners.splice(idx, 1);
    }
}

function _onScrollSettled() {
    const segs = _getViewportSegments();
    if (segs.length === 0) return;

    _scrollAbortController = new AbortController();
    const signal = _scrollAbortController.signal;

    // Batch with concurrency limit of 4
    const queue = [...segs];
    let active = 0;
    const MAX_CONCURRENT = 4;

    function next() {
        while (active < MAX_CONCURRENT && queue.length > 0) {
            if (signal.aborted) return;
            const item = queue.shift();
            active++;
            _preloadAudioForSeg(item, signal).finally(() => {
                active--;
                next();
            });
        }
    }
    next();
}

function _getViewportSegments() {
    const results = [];
    const seen = new Set();

    // Check all active scroll containers
    const containers = [segListEl];
    document.querySelectorAll('.val-cards-container').forEach(c => {
        if (!c.hidden && c.children.length > 0) containers.push(c);
    });

    for (const container of containers) {
        if (!container) continue;
        const cRect = container.getBoundingClientRect();
        const rows = container.querySelectorAll('.seg-row');
        let belowCount = 0;

        for (const row of rows) {
            const rRect = row.getBoundingClientRect();
            const inView = rRect.bottom > cRect.top && rRect.top < cRect.bottom;
            const justBelow = rRect.top >= cRect.bottom;

            if (inView || (justBelow && belowCount < 3)) {
                if (justBelow) belowCount++;
                const seg = resolveSegFromRow(row);
                if (!seg) continue;
                const audioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(seg.chapter)] || '';
                const chapterAudio = segAllData?.audio_by_chapter?.[String(seg.chapter)] || '';
                const isByAyah = seg.audio_url && seg.audio_url !== chapterAudio;
                if (!audioUrl || seen.has(audioUrl)) continue;
                // Skip if already cached or being loaded (null sentinel)
                const cacheKey = isByAyah ? audioUrl : seg.chapter;
                if (segAudioBuffers.has(cacheKey)) continue;
                // Also skip by_surah if the eager decode already loaded it
                if (!isByAyah && segAudioBuffer && segAudioBufferUrl === audioUrl) continue;
                seen.add(audioUrl);
                results.push({ seg, audioUrl, chapter: seg.chapter, isByAyah });
            } else if (rRect.top > cRect.bottom && belowCount >= 3) {
                break;  // past buffer zone
            }
        }
    }
    return results;
}

async function _preloadAudioForSeg({ seg, audioUrl, chapter, isByAyah }, signal) {
    if (signal.aborted) return;
    try {
        if (!segAudioCtx) {
            segAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        const resp = await fetch(audioUrl, { signal });
        if (signal.aborted) return;
        const buf = await resp.arrayBuffer();
        if (signal.aborted) return;
        const decoded = await segAudioCtx.decodeAudioData(buf);
        if (signal.aborted) return;
        if (isByAyah) {
            segAudioBuffers.set(audioUrl, decoded);
        } else {
            segAudioBuffers.set(chapter, decoded);
            // For by_surah: also set the global buffer so waveform drawing works
            // (don't touch segAudioEl — the eager load in onSegChapterChange handles that)
            const currentChapter = parseInt(segChapterSelect.value);
            if (chapter === currentChapter && !segAudioBuffer) {
                segAudioBuffer = decoded;
                segAudioBufferUrl = audioUrl;
            }
        }
        // Trigger waveform drawing for canvases that now have a buffer available
        _redrawPeaksWaveforms();
    } catch (e) {
        if (e.name !== 'AbortError') {
            console.warn('Audio preload failed:', audioUrl, e);
        }
    }
}


// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function clearSegDisplay() {
    if (_waveformObserver) { _waveformObserver.disconnect(); _waveformObserver = null; }
    _segIndexMap = null;
    segAllData = null;
    segAudioBuffers.clear();
    segActiveFilters = [];
    segAvgSpeechRate = 0;
    if (segFilterBarEl) { segFilterBarEl.hidden = true; segFilterRowsEl.innerHTML = ''; }
    if (segFilterCountEl) segFilterCountEl.textContent = '';
    if (segFilterClearBtn) segFilterClearBtn.hidden = true;
    if (segFilterStatusEl) segFilterStatusEl.textContent = '';
    segData = null;
    segAudioBuffer = null;
    segAudioBufferUrl = '';
    segDisplayedSegments = null;
    segCurrentIdx = -1;
    segDirtyMap.clear();
    segOpLog.clear();
    _pendingOp = null;
    segEditMode = null;
    segEditIndex = -1;
    segStatsData = null;
    if (segStatsPanel) { segStatsPanel.hidden = true; segStatsCharts.innerHTML = ''; }
    segHistoryData = null;
    segHistoryBtn.hidden = true;
    segHistoryView.hidden = true;
    segHistoryStats.innerHTML = '';
    segHistoryBatches.innerHTML = '';
    _segPrefetchCache = {};
    _segContinuousPlay = false;
    _segPlayEndMs = 0;
    segPeaksByAudio = null;
    if (_peaksPollTimer) { clearTimeout(_peaksPollTimer); _peaksPollTimer = null; }
    _teardownScrollPreloading();
    segListEl.innerHTML = '';
    segPlayBtn.disabled = true;
    segSaveBtn.disabled = true;
    segPlayStatus.textContent = '';
    stopSegAnimation();
}

// ---------------------------------------------------------------------------
// Unified event delegation
// ---------------------------------------------------------------------------

/** Resolve a segment object from a .seg-row element. History cards use stored snapshot data; others try index map then global lookup. */
function resolveSegFromRow(row) {
    if (!row) return null;
    const idx = parseInt(row.dataset.segIndex);
    const chapter = parseInt(row.dataset.segChapter);
    // History cards: always use stored snapshot data (indices may have changed since save)
    if (row.dataset.histTimeStart !== undefined) {
        return {
            chapter, index: idx,
            time_start: parseFloat(row.dataset.histTimeStart),
            time_end: parseFloat(row.dataset.histTimeEnd),
            audio_url: row.dataset.histAudioUrl || '',
            matched_ref: '', matched_text: '', confidence: 0,
        };
    }
    // Try the fast index map (populated for main section displayed segments)
    const fromMap = _segIndexMap?.get(`${chapter}:${idx}`);
    if (fromMap) return fromMap;
    // Fall back to global chapter/index lookup (error section cards)
    if (chapter) return getSegByChapterIndex(chapter, idx);
    return null;
}

function handleSegRowClick(e) {
    // Ref edit (skip for read-only history cards)
    const refSpan = e.target.closest('.seg-text-ref');
    if (refSpan) {
        e.stopPropagation();
        const row = refSpan.closest('.seg-row');
        if (row && row.dataset.histTimeStart !== undefined) return; // read-only history card
        const seg = resolveSegFromRow(row);
        if (seg && row) startRefEdit(refSpan, seg, row);
        return;
    }
    // Play button (error cards)
    const playBtn = e.target.closest('.seg-card-play-btn');
    if (playBtn) {
        e.stopPropagation();
        const row = playBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg) playErrorCardAudio(seg, playBtn);
        return;
    }
    // Go To button (error cards + filter results)
    const gotoBtn = e.target.closest('.seg-card-goto-btn');
    if (gotoBtn) {
        e.stopPropagation();
        const row = gotoBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        // Save filter state when clicking from main list with active filters
        if (row.closest('#seg-list') && segActiveFilters.some(f => f.value !== null)) {
            _segSavedFilterView = {
                filters: JSON.parse(JSON.stringify(segActiveFilters)),
                chapter: segChapterSelect.value,
                verse: segVerseSelect.value,
                scrollTop: segListEl.scrollTop,
            };
        }
        jumpToSegment(seg.chapter, seg.index);
        return;
    }
    // Adjust button
    const adjustBtn = e.target.closest('.btn-adjust');
    if (adjustBtn) {
        e.stopPropagation();
        const row = adjustBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) enterEditWithBuffer(seg, row, 'trim');
        return;
    }
    // Split button
    const splitBtn = e.target.closest('.btn-split');
    if (splitBtn) {
        e.stopPropagation();
        const row = splitBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) enterEditWithBuffer(seg, row, 'split');
        return;
    }
    // Merge prev/next buttons
    const mergePrev = e.target.closest('.btn-merge-prev');
    if (mergePrev) {
        e.stopPropagation();
        const row = mergePrev.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg) mergeAdjacent(seg, 'prev');
        return;
    }
    const mergeNext = e.target.closest('.btn-merge-next');
    if (mergeNext) {
        e.stopPropagation();
        const row = mergeNext.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg) mergeAdjacent(seg, 'next');
        return;
    }
    // Delete button
    const deleteBtn = e.target.closest('.btn-delete');
    if (deleteBtn) {
        e.stopPropagation();
        const row = deleteBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg) deleteSegment(seg, row);
        return;
    }
    // Row click to play (ignore if clicking on actions)
    const row = e.target.closest('.seg-row');
    if (row && !e.target.closest('.seg-actions')) {
        if (segEditMode) return;
        if (segListEl.contains(row)) {
            const idx = parseInt(row.dataset.segIndex);
            playFromSegment(idx, parseInt(row.dataset.segChapter));
        } else {
            // Error section card — play via error card handler
            const seg = resolveSegFromRow(row);
            const playBtn = row.querySelector('.seg-card-play-btn');
            if (seg && playBtn) playErrorCardAudio(seg, playBtn);
        }
    }
}

/**
 * Render a single segment card (.seg-row) usable in both main and error sections.
 * @param {object} seg — segment object
 * @param {object} options
 *   - showChapter: prefix index with chapter number (error cards)
 *   - showPlayBtn: show play button in actions (error cards)
 *   - showGotoBtn: show Go To button in actions (error cards)
 *   - isContext: dimmed non-editable context card
 *   - contextLabel: label for context cards (e.g. 'Previous', 'Next')
 *   - missingWordSegIndices: Set of indices with missing words (main section)
 */
function renderSegCard(seg, options = {}) {
    const {
        showChapter = false,
        showPlayBtn = false,
        showGotoBtn = false,
        isContext = false,
        contextLabel = '',
        missingWordSegIndices = null,
        readOnly = false,
    } = options;

    const row = document.createElement('div');
    row.className = 'seg-row' + (!readOnly && isIndexDirty(seg.chapter || parseInt(segChapterSelect.value), seg.index) ? ' dirty' : '') + (isContext ? ' seg-row-context' : '');
    row.dataset.segIndex = seg.index;
    row.dataset.segChapter = seg.chapter;

    // For history cards: store time/audio data directly so the waveform observer
    // can draw even when the segment no longer exists at this index.
    if (readOnly) {
        row.dataset.histTimeStart = seg.time_start;
        row.dataset.histTimeEnd = seg.time_end;
        if (seg.audio_url) row.dataset.histAudioUrl = seg.audio_url;
    }

    // Canvas for waveform
    const canvas = document.createElement('canvas');
    canvas.width = 300;
    canvas.height = 60;
    canvas.setAttribute('data-needs-waveform', '');
    row.appendChild(canvas);

    // Text box
    const textBox = document.createElement('div');
    const confClass = getConfClass(seg);
    textBox.className = `seg-text ${confClass}`;

    // Header row: index + ref (clickable) + confidence
    const header = document.createElement('div');
    header.className = 'seg-text-header';

    const indexSpan = document.createElement('span');
    indexSpan.className = 'seg-text-index';
    indexSpan.textContent = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const refSpan = document.createElement('span');
    refSpan.className = 'seg-text-ref';
    refSpan.textContent = formatRef(seg.matched_ref);

    const confSpan = document.createElement('span');
    confSpan.className = `seg-text-conf ${confClass}`;
    confSpan.textContent = seg.matched_ref ? (seg.confidence * 100).toFixed(1) + '%' : 'FAIL';

    header.append(indexSpan, refSpan, confSpan);
    textBox.appendChild(header);

    // Context label (for context cards)
    if (contextLabel) {
        const lbl = document.createElement('div');
        lbl.className = 'seg-text-label';
        lbl.textContent = contextLabel;
        textBox.appendChild(lbl);
    }

    // Arabic text
    const body = document.createElement('div');
    body.className = 'seg-text-body';
    body.textContent = seg.display_text || seg.matched_text || '(alignment failed)';
    textBox.appendChild(body);

    // Time info + missing words tag
    const timeInfo = document.createElement('div');
    timeInfo.className = 'seg-text-time';
    timeInfo.textContent = `${formatTimeMs(seg.time_start)} - ${formatTimeMs(seg.time_end)} (${((seg.time_end - seg.time_start) / 1000).toFixed(1)}s)`;
    if (missingWordSegIndices && missingWordSegIndices.has(seg.index)) {
        const tag = document.createElement('span');
        tag.className = 'seg-tag seg-tag-missing';
        tag.textContent = 'Missing words';
        timeInfo.appendChild(tag);
    }
    textBox.appendChild(timeInfo);

    // Play button (allowed even on read-only history cards)
    if (!isContext && showPlayBtn) {
        const actions = row.querySelector('.seg-actions') || document.createElement('div');
        actions.className = 'seg-actions';
        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.textContent = '\u25B6';
        playBtn.title = 'Play segment audio';
        actions.appendChild(playBtn);
        if (!actions.parentNode) textBox.appendChild(actions);
    }

    // Editing action buttons (skip for read-only history cards)
    if (!isContext && !readOnly) {
        const actions = textBox.querySelector('.seg-actions') || document.createElement('div');
        actions.className = 'seg-actions';

        const trimBtn = document.createElement('button');
        trimBtn.className = 'btn btn-sm btn-adjust';
        trimBtn.textContent = 'Adjust';

        const splitBtn = document.createElement('button');
        splitBtn.className = 'btn btn-sm btn-split';
        splitBtn.textContent = 'Split';

        const mergePrevBtn = document.createElement('button');
        mergePrevBtn.className = 'btn btn-sm btn-merge-prev';
        mergePrevBtn.textContent = 'Merge \u2191';

        const mergeNextBtn = document.createElement('button');
        mergeNextBtn.className = 'btn btn-sm btn-merge-next';
        mergeNextBtn.textContent = 'Merge \u2193';

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-delete';
        deleteBtn.textContent = 'Delete';

        actions.append(trimBtn, splitBtn, mergePrevBtn, mergeNextBtn, deleteBtn);

        if (showGotoBtn) {
            const gotoBtn = document.createElement('button');
            gotoBtn.className = 'btn btn-sm seg-card-goto-btn';
            gotoBtn.textContent = 'Go to';
            actions.appendChild(gotoBtn);
        }

        if (!actions.parentNode) textBox.appendChild(actions);
    }

    row.appendChild(textBox);
    return row;
}

function renderSegList(segments) {
    // Invalidate cached row references (DOM nodes are about to be replaced)
    _prevHighlightedRow = null; _prevHighlightedIdx = -1;
    _prevPlayheadRow = null; _currentPlayheadRow = null; _prevPlayheadIdx = -1;
    segListEl.innerHTML = '';
    if (!segments || segments.length === 0) {
        segListEl.innerHTML = '<div class="seg-loading">No segments to display</div>';
        return;
    }

    // Build set of segment indices with missing words (from server validation data)
    const missingWordSegIndices = new Set();
    if (segValidation && segValidation.missing_words) {
        const chapter = parseInt(segChapterSelect.value) || 0;
        segValidation.missing_words.forEach(mw => {
            if (mw.chapter === chapter && mw.seg_indices) {
                mw.seg_indices.forEach(idx => missingWordSegIndices.add(idx));
            }
        });
    }

    const fragment = document.createDocumentFragment();
    const observer = _ensureWaveformObserver();

    segments.forEach((seg, displayIdx) => {
        const row = renderSegCard(seg, {
            missingWordSegIndices,
        });

        // Neighbour styling and silence gap indicator
        if (seg._isNeighbour) row.classList.add('seg-neighbour');

        fragment.appendChild(row);

        // Silence gap badge between consecutive segments
        if (seg.silence_after_ms != null) {
            const nextDisplayed = segments[displayIdx + 1];
            if (nextDisplayed && nextDisplayed.index === seg.index + 1) {
                const wrapper = document.createElement('div');
                wrapper.className = 'seg-silence-gap-wrapper';
                const gapDiv = document.createElement('div');
                gapDiv.className = 'seg-silence-gap';
                gapDiv.textContent = `\u23F8 ${Math.round(seg.silence_after_ms)}ms (raw: ${Math.round(seg.silence_after_raw_ms)}ms)`;
                wrapper.appendChild(gapDiv);
                fragment.appendChild(wrapper);
            }
        }
    });

    segListEl.appendChild(fragment);

    // Observe canvases for lazy waveform drawing
    segListEl.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));

    // Attach scroll-based audio preloading
    _attachScrollPreload(segListEl);
}

function getConfClass(seg) {
    if (!seg.matched_ref) return 'conf-fail';
    if (seg.confidence >= 0.80) return 'conf-high';
    if (seg.confidence >= 0.60) return 'conf-mid';
    return 'conf-low';
}


// ---------------------------------------------------------------------------
// Waveform drawing
// ---------------------------------------------------------------------------

function drawSegmentWaveformFromPeaks(canvas, startMs, endMs, peaks, totalDurationMs) {
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    if (!peaks || peaks.length === 0 || totalDurationMs <= 0) return;

    // Slice peaks for this segment's time range
    const startIdx = Math.floor((startMs / totalDurationMs) * peaks.length);
    const endIdx = Math.ceil((endMs / totalDurationMs) * peaks.length);
    const slice = peaks.slice(Math.max(0, startIdx), Math.min(peaks.length, endIdx));
    if (slice.length === 0) return;

    const buckets = width;
    const scale = height / 2 * 0.9;

    // Resample slice to canvas width via linear interpolation
    function sampleAt(arr, idx, component) {
        const fi = (idx / buckets) * (arr.length - 1);
        const lo = Math.floor(fi);
        const hi = Math.min(lo + 1, arr.length - 1);
        const t = fi - lo;
        return arr[lo][component] * (1 - t) + arr[hi][component] * t;
    }

    // Filled waveform
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(slice, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const x = (i / buckets) * width;
        const minVal = sampleAt(slice, i, 0);
        const y = centerY - minVal * scale;
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    // Stroke outline (max envelope)
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const maxVal = sampleAt(slice, i, 1);
        const y = centerY - maxVal * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    canvas._wfCache = null;
}

function drawSegmentWaveform(canvas, startMs, endMs) {
    if (!segAudioBuffer) return;

    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;

    // Clear
    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    // Extract samples for this segment (convert ms to seconds for sample math)
    const sampleRate = segAudioBuffer.sampleRate;
    const rawData = segAudioBuffer.getChannelData(0);
    const startSample = Math.floor((startMs / 1000) * sampleRate);
    const endSample = Math.min(Math.floor((endMs / 1000) * sampleRate), rawData.length);
    const totalSamples = endSample - startSample;

    if (totalSamples <= 0) return;

    const buckets = width;
    const blockSize = Math.max(1, Math.floor(totalSamples / buckets));
    const scale = height / 2 * 0.9;

    // Draw filled waveform
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const offset = startSample + i * blockSize;
        let max = -1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val > max) max = val;
        }
        const x = (i / buckets) * width;
        const y = centerY - max * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const offset = startSample + i * blockSize;
        let min = 1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val < min) min = val;
        }
        const x = (i / buckets) * width;
        const y = centerY - min * scale;
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
        const offset = startSample + i * blockSize;
        let max = -1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val > max) max = val;
        }
        const x = (i / buckets) * width;
        const y = centerY - max * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Invalidate playhead cache so next drawSegPlayhead re-caches the fresh waveform
    canvas._wfCache = null;
}

function drawSegPlayhead(canvas, startMs, endMs, currentTimeMs) {
    // Restore cached waveform image if available (avoids recomputing from raw samples every frame)
    const ctx = canvas.getContext('2d');
    const cacheKey = `${startMs}:${endMs}`;
    if (canvas._wfCache && canvas._wfCacheKey === cacheKey) {
        ctx.putImageData(canvas._wfCache, 0, 0);
    } else {
        // Try AudioBuffer first, fall back to peaks
        if (segAudioBuffer) {
            drawSegmentWaveform(canvas, startMs, endMs);
        } else if (segPeaksByAudio && segAudioBufferUrl) {
            const pe = segPeaksByAudio[segAudioBufferUrl];
            if (pe?.peaks?.length) drawSegmentWaveformFromPeaks(canvas, startMs, endMs, pe.peaks, pe.duration_ms);
        }
        canvas._wfCache = ctx.getImageData(0, 0, canvas.width, canvas.height);
        canvas._wfCacheKey = cacheKey;
    }

    if (currentTimeMs < startMs || currentTimeMs > endMs) return;

    const width = canvas.width;
    const height = canvas.height;
    const progress = (currentTimeMs - startMs) / (endMs - startMs);
    const x = progress * width;

    // Playhead line
    ctx.strokeStyle = '#f72585';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Small triangle
    ctx.fillStyle = '#f72585';
    ctx.beginPath();
    ctx.moveTo(x - 4, 0);
    ctx.lineTo(x + 4, 0);
    ctx.lineTo(x, 6);
    ctx.closePath();
    ctx.fill();
}


// ---------------------------------------------------------------------------
// Playback
// ---------------------------------------------------------------------------

function playFromSegment(segIndex, chapterOverride) {
    if (!segAllData) return;
    stopErrorCardAudio();
    _activeAudioSource = 'main';
    const chapter = chapterOverride ?? (segChapterSelect.value ? parseInt(segChapterSelect.value) : null);
    const seg = chapter != null
        ? getSegByChapterIndex(chapter, segIndex)
        : (segDisplayedSegments ? segDisplayedSegments.find(s => s.index === segIndex) : null);
    if (!seg) return;

    // Abort in-flight scroll preloads to free browser connections for playback
    if (_scrollAbortController) _scrollAbortController.abort();

    _segContinuousPlay = true;
    _segPlayEndMs = seg.time_end;

    // Switch audio source if needed (by_ayah has different audio per verse)
    const segAudioUrl = seg.audio_url || '';
    const needsSwitch = segAudioUrl && segAudioUrl !== segAudioBufferUrl;

    if (needsSwitch) {
        segAudioEl.src = segAudioUrl;
        // Check if scroll preloader already decoded this URL
        const cached = segAudioBuffers.get(segAudioUrl);
        if (cached && cached instanceof AudioBuffer) {
            segAudioBuffer = cached;
            segAudioBufferUrl = segAudioUrl;
            drawAllSegWaveforms();
        } else {
            segAudioBuffer = null;
            segAudioBufferUrl = '';
            decodeSegAudio(segAudioUrl).then(() => {
                if (segAudioBuffer) drawAllSegWaveforms();
            });
        }
    }

    segAudioEl.playbackRate = parseFloat(segSpeedSelect.value);
    segAudioEl.currentTime = seg.time_start / 1000;
    segAudioEl.play();
    segCurrentIdx = segIndex;
    updateSegPlayStatus();

    // Prefetch next segment's audio if it differs
    _prefetchNextSegAudio(segIndex);

}

/**
 * Find the next displayed segment after the given index.
 */
function _nextDisplayedSeg(afterIndex) {
    if (!segDisplayedSegments) return null;
    const pos = segDisplayedSegments.findIndex(s => s.index === afterIndex);
    if (pos >= 0 && pos < segDisplayedSegments.length - 1) {
        return segDisplayedSegments[pos + 1];
    }
    return null;
}

/**
 * Prefetch the next segment's audio into the browser cache if it has a different URL.
 */
function _prefetchNextSegAudio(currentIndex) {
    const next = _nextDisplayedSeg(currentIndex);
    if (!next || !next.audio_url) return;
    const currentUrl = segAudioBufferUrl || (segAudioEl.src || '');
    if (next.audio_url === currentUrl) return;
    if (_segPrefetchCache[next.audio_url]) return; // already prefetching/prefetched
    // Prefetch: download into browser cache so the <audio> src switch is instant
    _segPrefetchCache[next.audio_url] = fetch(next.audio_url)
        .then(r => r.blob())
        .catch(() => {});
}

function onSegPlayClick() {
    // If error card audio is playing, pause it (don't also start main)
    if (valCardAudio && !valCardAudio.paused) {
        stopErrorCardAudio();
        return;
    }
    // Otherwise toggle main audio
    if (segAudioEl.paused) {
        if (segDisplayedSegments && segDisplayedSegments.length > 0 && segCurrentIdx < 0) {
            const first = segDisplayedSegments[0];
            playFromSegment(first.index, first.chapter);
        } else {
            _segContinuousPlay = true;
            _activeAudioSource = 'main';
            segAudioEl.playbackRate = parseFloat(segSpeedSelect.value);
            segAudioEl.play();
        }
    } else {
        _segContinuousPlay = false;
        segAudioEl.pause();
    }
}

function onSegTimeUpdate() {
    const timeMs = segAudioEl.currentTime * 1000;
    const currentSrc = segAudioEl.src || segAudioBufferUrl || '';

    // Find the last displayed segment on the *current* audio file
    let lastSegOnAudio = null;
    if (segDisplayedSegments && segDisplayedSegments.length > 0) {
        for (let i = segDisplayedSegments.length - 1; i >= 0; i--) {
            const s = segDisplayedSegments[i];
            if (!s.audio_url || s.audio_url === currentSrc) {
                lastSegOnAudio = s;
                break;
            }
        }
        // Fallback for by_surah (no per-segment audio_url)
        if (!lastSegOnAudio) lastSegOnAudio = segDisplayedSegments[segDisplayedSegments.length - 1];
    }

    // At end of last segment on this audio file: auto-advance or stop
    if (lastSegOnAudio && timeMs >= lastSegOnAudio.time_end) {
        const nextSeg = _nextDisplayedSeg(lastSegOnAudio.index);
        const isConsecutive = nextSeg && nextSeg.index === lastSegOnAudio.index + 1;
        if (_segContinuousPlay && isConsecutive && nextSeg.audio_url && nextSeg.audio_url !== currentSrc) {
            // Auto-advance to next segment on a different audio file (only if consecutive)
            playFromSegment(nextSeg.index, nextSeg.chapter);
            return;
        }
        // No more segments or same audio — stop
        segAudioEl.pause();
        stopSegAnimation();
        _segContinuousPlay = false;
        _segPlayEndMs = 0;
        return;
    }

    // Find current segment from displayed segments only (not all segments)
    const prevIdx = segCurrentIdx;
    segCurrentIdx = -1;
    if (segDisplayedSegments) {
        for (const seg of segDisplayedSegments) {
            if (timeMs >= seg.time_start && timeMs < seg.time_end) {
                if (seg.audio_url && segAudioBufferUrl && seg.audio_url !== segAudioBufferUrl) continue;
                segCurrentIdx = seg.index;
                break;
            }
        }
    }

    // Stop if we've passed the end of the active displayed segment and entered a gap
    if (segCurrentIdx === -1 && _segPlayEndMs > 0 && timeMs >= _segPlayEndMs) {
        // In continuous play on same audio, don't stop in gaps — let audio play through
        if (_segContinuousPlay && segDisplayedSegments) {
            // Find the next segment after the one that just ended
            const justEnded = segDisplayedSegments.find(s => s.time_end === _segPlayEndMs
                && (!s.audio_url || s.audio_url === currentSrc));
            if (justEnded) {
                const nextSeg2 = _nextDisplayedSeg(justEnded.index);
                if (nextSeg2 && (!nextSeg2.audio_url || nextSeg2.audio_url === currentSrc)) {
                    return; // same audio file — wait for next segment to start
                }
            }
        }
        segAudioEl.pause();
        stopSegAnimation();
        _segContinuousPlay = false;
        _segPlayEndMs = 0;
        return;
    }

    if (segCurrentIdx !== prevIdx) {
        if (segCurrentIdx >= 0) {
            const curSeg = segDisplayedSegments.find(s => s.index === segCurrentIdx);
            if (curSeg) _segPlayEndMs = curSeg.time_end;
        }
        updateSegHighlight();
        updateSegPlayStatus();
        // Prefetch next segment's audio when we enter a new segment
        if (segCurrentIdx >= 0) _prefetchNextSegAudio(segCurrentIdx);
    }
}

function startSegAnimation() {
    segPlayBtn.textContent = 'Pause';
    _activeAudioSource = 'main';
    animateSeg();
}

function stopSegAnimation() {
    // Only reset to "Play" if error card audio is also not playing
    if (!valCardAudio || valCardAudio.paused) {
        segPlayBtn.textContent = 'Play';
    }
    if (_activeAudioSource === 'main') _activeAudioSource = null;
    if (segAnimId) {
        cancelAnimationFrame(segAnimId);
        segAnimId = null;
    }
}

function onSegAudioEnded() {
    // For by_ayah: when an audio file ends, auto-advance to next segment if continuous
    if (_segContinuousPlay && segCurrentIdx >= 0) {
        const next = _nextDisplayedSeg(segCurrentIdx);
        if (next && next.audio_url) {
            playFromSegment(next.index, next.chapter);
            return;
        }
    }
    _segContinuousPlay = false;
    stopSegAnimation();
}

function animateSeg() {
    updateSegHighlight();
    drawActivePlayhead();
    segAnimId = requestAnimationFrame(animateSeg);
}

let _prevHighlightedRow = null;
let _prevHighlightedIdx = -1;

function updateSegHighlight() {
    if (segCurrentIdx === _prevHighlightedIdx) return;
    if (_prevHighlightedRow) {
        _prevHighlightedRow.classList.remove('playing');
    }
    _prevHighlightedRow = null;
    _prevHighlightedIdx = segCurrentIdx;
    if (segCurrentIdx >= 0) {
        const row = segListEl.querySelector(`.seg-row[data-seg-index="${segCurrentIdx}"]`);
        if (row) {
            row.classList.add('playing');
            _prevHighlightedRow = row;
        }
    }
}

let _prevPlayheadIdx = -1;
let _prevPlayheadRow = null;
let _currentPlayheadRow = null;

function drawActivePlayhead() {
    if (!segAllData || !segChapterSelect.value) return;
    const chapter = parseInt(segChapterSelect.value);
    const time = segAudioEl.currentTime * 1000; // convert to ms

    const indexChanged = _prevPlayheadIdx !== segCurrentIdx;

    // Clear playhead from previously active canvas (if it changed)
    if (_prevPlayheadIdx >= 0 && indexChanged) {
        const prevRow = _prevPlayheadRow || segListEl.querySelector(`.seg-row[data-seg-index="${_prevPlayheadIdx}"]`);
        if (prevRow) {
            const canvas = prevRow.querySelector('canvas');
            const seg = getSegByChapterIndex(chapter, _prevPlayheadIdx);
            if (canvas && seg) drawSegmentWaveform(canvas, seg.time_start, seg.time_end);
        }
    }

    if (indexChanged) {
        _prevPlayheadRow = _currentPlayheadRow;
        _currentPlayheadRow = segCurrentIdx >= 0
            ? segListEl.querySelector(`.seg-row[data-seg-index="${segCurrentIdx}"]`)
            : null;
    }
    _prevPlayheadIdx = segCurrentIdx;

    // Draw playhead on current segment only
    if (segCurrentIdx >= 0) {
        const row = _currentPlayheadRow;
        if (row) {
            const canvas = row.querySelector('canvas');
            const seg = getSegByChapterIndex(chapter, segCurrentIdx);
            if (canvas && seg) drawSegPlayhead(canvas, seg.time_start, seg.time_end, time);
        }
    }
}

function updateSegPlayStatus() {
    if (segCurrentIdx >= 0 && segAllData && segChapterSelect.value) {
        const chapter = parseInt(segChapterSelect.value);
        const seg = getSegByChapterIndex(chapter, segCurrentIdx);
        if (seg) {
            segPlayStatus.textContent = `Segment #${seg.index} — ${formatTimeMs(segAudioEl.currentTime * 1000)}`;
        }
    } else {
        segPlayStatus.textContent = '';
    }
}


// ---------------------------------------------------------------------------
// Inline ref editing
// ---------------------------------------------------------------------------

function startRefEdit(refSpan, seg, row) {
    // Already editing
    if (refSpan.querySelector('input')) return;

    // Edit history: snapshot before ref edit
    _pendingOp = createOp('edit_reference');
    _pendingOp.targets_before = [snapshotSeg(seg)];

    const originalRef = seg.matched_ref || '';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'seg-text-ref-input';
    input.value = originalRef;

    refSpan.textContent = '';
    refSpan.appendChild(input);
    input.focus();
    input.select();

    let committed = false;

    function commit() {
        if (committed) return;
        committed = true;
        const newRef = input.value.trim();
        commitRefEdit(seg, newRef, row);
    }

    input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            committed = true;
            _pendingOp = null;  // discard edit history op on cancel
            refSpan.textContent = formatRef(originalRef);
        }
    });

    input.addEventListener('blur', commit);
    input.addEventListener('click', (e) => e.stopPropagation());
}

async function commitRefEdit(seg, newRef, row) {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    if (newRef === oldRef) {
        // Same ref confirmed — mark as validated (100% confidence)
        if (seg.confidence < 1.0) {
            // Edit history: confirm_reference (audit)
            if (_pendingOp) {
                _pendingOp.op_type = 'confirm_reference';
                _pendingOp.fix_kind = 'audit';
            }
            seg.confidence = 1.0;
            delete seg._derived;
            markDirty(chapter, seg.index);
            syncAllCardsForSegment(seg);
            // Edit history: finalize confirm
            if (_pendingOp) {
                _pendingOp.applied_at_utc = new Date().toISOString();
                _pendingOp.targets_after = [snapshotSeg(seg)];
                finalizeOp(chapter, _pendingOp);
            }
        } else {
            _pendingOp = null;  // no-op: ref unchanged, already 1.0
            const refSpan = row.querySelector('.seg-text-ref');
            if (refSpan) refSpan.textContent = formatRef(oldRef);
        }
        return;
    }

    // Update in-memory data
    seg.matched_ref = newRef;
    seg.confidence = 1.0;

    if (newRef) {
        // Resolve text from backend
        try {
            const resp = await fetch(`/api/seg/resolve_ref?ref=${encodeURIComponent(newRef)}`);
            const data = await resp.json();
            if (data.text) {
                seg.matched_text = data.text;
                seg.display_text = data.display_text || data.text;
            } else if (data.error) {
                console.warn('resolve_ref error:', data.error);
                seg.matched_text = '(invalid ref)';
                seg.display_text = '';
            }
        } catch (e) {
            console.error('Failed to resolve ref:', e);
            seg.matched_text = '(resolve failed)';
            seg.display_text = '';
        }
    } else {
        seg.matched_text = '';
        seg.display_text = '';
    }

    delete seg._derived;
    markDirty(chapter, seg.index);

    // Update all matching cards globally (both main and error sections)
    syncAllCardsForSegment(seg);

    // Edit history: finalize edit_reference after resolve + sync
    if (_pendingOp) {
        _pendingOp.applied_at_utc = new Date().toISOString();
        _pendingOp.targets_after = [snapshotSeg(seg)];
        finalizeOp(chapter, _pendingOp);
    }
}

/** Update a single .seg-row card in-place (works for both main and error section cards). */
function updateSegCard(row, seg) {
    row.classList.add('dirty');

    const confClass = getConfClass(seg);
    const textBox = row.querySelector('.seg-text');
    if (textBox) textBox.className = `seg-text ${confClass}`;

    const refSpan = row.querySelector('.seg-text-ref');
    if (refSpan) refSpan.textContent = formatRef(seg.matched_ref);

    const confSpan = row.querySelector('.seg-text-conf');
    if (confSpan) {
        confSpan.className = `seg-text-conf ${confClass}`;
        confSpan.textContent = seg.matched_ref ? (seg.confidence * 100).toFixed(1) + '%' : 'FAIL';
    }

    const body = row.querySelector('.seg-text-body');
    if (body) body.textContent = seg.display_text || seg.matched_text || '(alignment failed)';

    const timeInfo = row.querySelector('.seg-text-time');
    if (timeInfo) {
        // Preserve any tags (e.g. missing words)
        const tags = timeInfo.querySelectorAll('.seg-tag');
        timeInfo.textContent = `${formatTimeMs(seg.time_start)} - ${formatTimeMs(seg.time_end)} (${((seg.time_end - seg.time_start) / 1000).toFixed(1)}s)`;
        tags.forEach(t => timeInfo.appendChild(t));
    }
}

/** Sync all .seg-row cards matching this segment across the entire page. */
function syncAllCardsForSegment(seg) {
    document.querySelectorAll(
        `.seg-row[data-seg-chapter="${seg.chapter}"][data-seg-index="${seg.index}"]`
    ).forEach(row => {
        if (!row.classList.contains('seg-row-context')) {
            updateSegCard(row, seg);
        }
    });
}


// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

async function onSegSaveClick() {
    if (!isDirty()) return;

    const reciter = segReciterSelect.value;
    if (!reciter) return;

    segSaveBtn.disabled = true;
    segSaveBtn.textContent = 'Saving...';

    let savedChanges = 0;
    let savedChapters = 0;
    let allOk = true;

    try {
        for (const [ch, entry] of segDirtyMap) {
            // Always read from segAllData (canonical source)
            const chSegs = getChapterSegments(ch);
            let payload;

            // Attach edit history operations for this chapter
            const chOps = segOpLog.get(ch) || [];

            if (entry.structural) {
                // Structural change (split/merge/delete/trim) — replace entire chapter
                payload = {
                    full_replace: true,
                    segments: chSegs.map(s => ({
                        segment_uid: s.segment_uid || '',
                        time_start: s.time_start,
                        time_end: s.time_end,
                        matched_ref: s.matched_ref,
                        matched_text: s.matched_text,
                        confidence: s.confidence,
                        phonemes_asr: s.phonemes_asr || '',
                        audio_url: s.audio_url || '',
                    })),
                    operations: chOps,
                };
                savedChanges += chOps.length;
            } else {
                // Patch mode — only send changed segments
                const updates = [];
                for (const idx of entry.indices) {
                    const seg = chSegs.find(s => s.index === idx);
                    if (seg) {
                        updates.push({
                            index: seg.index,
                            segment_uid: seg.segment_uid || '',
                            matched_ref: seg.matched_ref,
                            matched_text: seg.matched_text,
                            confidence: seg.confidence,
                        });
                    }
                }
                if (updates.length === 0) continue;
                payload = { segments: updates, operations: chOps };
                savedChanges += chOps.length;
            }

            const resp = await fetch(`/api/seg/save/${reciter}/${ch}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const result = await resp.json();
            if (!result.ok) {
                segPlayStatus.textContent = `Save error (ch ${ch}): ${result.error}`;
                allOk = false;
                break;
            }
            // Remove successfully saved chapter so partial failures keep remaining entries
            segDirtyMap.delete(ch);
            segOpLog.delete(ch);
            savedChapters++;
        }

        if (allOk) {
            segDirtyMap.clear();
            segOpLog.clear();
            const msg = savedChapters > 1
                ? `Saved ${savedChanges} changes across ${savedChapters} chapters`
                : `Saved ${savedChanges} change${savedChanges !== 1 ? 's' : ''}`;
            segSaveBtn.textContent = msg;
            // Clear dirty indicators on all cards (main + error sections)
            document.querySelectorAll('.seg-row.dirty').forEach(r => r.classList.remove('dirty'));
            setTimeout(() => { segSaveBtn.textContent = 'Save'; }, 2500);
            segUndoBtn.hidden = false;
            // Delay validation refresh to let server background thread finish
            setTimeout(refreshValidation, 1500);
            // Re-fetch edit history so the History view includes the just-saved batch
            try {
                const histResp = await fetch(`/api/seg/edit-history/${reciter}`);
                if (histResp.ok) {
                    segHistoryData = await histResp.json();
                    renderEditHistoryPanel(segHistoryData);
                }
            } catch (_) { /* non-critical */ }
        } else {
            segSaveBtn.disabled = !isDirty();
            segSaveBtn.textContent = 'Save';
        }
    } catch (e) {
        console.error('Save failed:', e);
        segPlayStatus.textContent = 'Save failed';
        segSaveBtn.disabled = !isDirty();
        segSaveBtn.textContent = 'Save';
    }
}


async function onSegUndoClick() {
    const reciter = segReciterSelect.value;
    if (!reciter) return;
    if (!confirm('Undo last save? This will restore the previous version.')) return;

    segUndoBtn.disabled = true;
    segUndoBtn.textContent = 'Undoing...';

    try {
        const resp = await fetch(`/api/seg/undo/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const result = await resp.json();
        if (result.ok) {
            segUndoBtn.hidden = true;
            segUndoBtn.disabled = false;
            segUndoBtn.textContent = 'Undo Save';
            segOpLog.clear();
            _pendingOp = null;
            // Reload data for the current reciter
            onSegReciterChange();
        } else {
            segPlayStatus.textContent = `Undo error: ${result.error}`;
            segUndoBtn.disabled = false;
            segUndoBtn.textContent = 'Undo Save';
        }
    } catch (e) {
        console.error('Undo failed:', e);
        segPlayStatus.textContent = 'Undo failed';
        segUndoBtn.disabled = false;
        segUndoBtn.textContent = 'Undo Save';
    }
}


// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

const SEG_SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];

function handleSegKeydown(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (typeof activeTab !== 'undefined' && activeTab !== 'segments') return;

    switch (e.code) {
        case 'Space':
            e.preventDefault();
            onSegPlayClick();
            break;
        case 'ArrowLeft': {
            e.preventDefault();
            const el = (_activeAudioSource === 'error' && valCardAudio) ? valCardAudio : segAudioEl;
            el.currentTime = Math.max(0, el.currentTime - 3);
            break;
        }
        case 'ArrowRight': {
            e.preventDefault();
            const el = (_activeAudioSource === 'error' && valCardAudio) ? valCardAudio : segAudioEl;
            el.currentTime = Math.min(el.duration || 0, el.currentTime + 3);
            break;
        }
        case 'ArrowUp': {
            e.preventDefault();
            if (!segDisplayedSegments || segDisplayedSegments.length === 0) break;
            const curPos = segDisplayedSegments.findIndex(s => s.index === segCurrentIdx);
            const prevPos = curPos > 0 ? curPos - 1 : 0;
            const prev = segDisplayedSegments[prevPos];
            playFromSegment(prev.index, prev.chapter);
            break;
        }
        case 'ArrowDown': {
            e.preventDefault();
            if (!segDisplayedSegments || segDisplayedSegments.length === 0) break;
            const curPos = segDisplayedSegments.findIndex(s => s.index === segCurrentIdx);
            const nextPos = curPos >= 0 && curPos < segDisplayedSegments.length - 1 ? curPos + 1 : (curPos === -1 ? 0 : curPos);
            const nxt = segDisplayedSegments[nextPos];
            playFromSegment(nxt.index, nxt.chapter);
            break;
        }
        case 'Period': // > speed up
        case 'Comma': { // < speed down
            e.preventDefault();
            const opts = Array.from(segSpeedSelect.options).map(o => parseFloat(o.value));
            const curRate = parseFloat(segSpeedSelect.value);
            const curIdx = opts.findIndex(s => Math.abs(s - curRate) < 0.01);
            const idx = curIdx === -1 ? opts.indexOf(1) : curIdx;
            const newIdx = e.code === 'Period'
                ? Math.min(idx + 1, opts.length - 1)
                : Math.max(idx - 1, 0);
            segSpeedSelect.value = opts[newIdx];
            segAudioEl.playbackRate = opts[newIdx];
            if (valCardAudio) valCardAudio.playbackRate = opts[newIdx];
            break;
        }
        case 'KeyJ': {
            e.preventDefault();
            const row = segListEl.querySelector(`.seg-row[data-seg-index="${segCurrentIdx}"]`);
            if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            break;
        }
        case 'KeyS': {
            if (isDirty()) {
                e.preventDefault();
                onSegSaveClick();
            }
            break;
        }
        case 'KeyZ': {
            if (e.ctrlKey && !segUndoBtn.hidden) {
                e.preventDefault();
                onSegUndoClick();
            }
            break;
        }
        case 'Escape':
            if (segEditMode) {
                e.preventDefault();
                exitEditMode();
            } else if (_segSavedFilterView) {
                e.preventDefault();
                _restoreFilterView();
            }
            break;

        case 'Enter':
            if (segEditMode && segCurrentIdx >= 0) {
                e.preventDefault();
                const seg = segDisplayedSegments
                    ? segDisplayedSegments.find(s => s.index === segCurrentIdx)
                    : null;
                if (seg) {
                    if (segEditMode === 'trim') confirmTrim(seg);
                    else if (segEditMode === 'split') confirmSplit(seg);
                }
            }
            break;

        case 'KeyE': {
            if (segEditMode || segCurrentIdx < 0) break;
            e.preventDefault();
            const row = segListEl.querySelector(`.seg-row[data-seg-index="${segCurrentIdx}"]`);
            const seg = segDisplayedSegments
                ? segDisplayedSegments.find(s => s.index === segCurrentIdx)
                : null;
            if (row && seg) {
                const refSpan = row.querySelector('.seg-text-ref');
                if (refSpan) startRefEdit(refSpan, seg, row);
            }
            break;
        }
    }
}


// ---------------------------------------------------------------------------
// Adjust mode
// ---------------------------------------------------------------------------

/**
 * Enter trim or split mode, ensuring the audio buffer is available.
 * For error cards from different chapters, loads the chapter's audio first.
 */
async function enterEditWithBuffer(seg, row, mode) {
    if (segEditMode) return;
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const isErrorCard = !segListEl.contains(row);

    if (isErrorCard && chapter !== currentChapter) {
        // Cross-chapter error card: need to load the other chapter's audio
        const buffer = await ensureChapterAudioBuffer(chapter);
        if (!buffer) {
            segPlayStatus.textContent = 'Could not load audio for chapter ' + chapter;
            return;
        }
        // Temporarily swap segAudioBuffer for edit mode
        row._savedAudioBuffer = segAudioBuffer;
        row._savedAudioBufferUrl = segAudioBufferUrl;
        segAudioBuffer = buffer;
        segAudioBufferUrl = segAllData?.audio_by_chapter?.[chapter] || '';
    } else if (isErrorCard && !segAudioBuffer) {
        // Same chapter but no buffer yet
        const buffer = await ensureChapterAudioBuffer(chapter);
        if (buffer) {
            segAudioBuffer = buffer;
            segAudioBufferUrl = segAllData?.audio_by_chapter?.[chapter] || '';
        }
    } else if (!segAudioBuffer || (seg.audio_url && seg.audio_url !== segAudioBufferUrl)) {
        // Main section segment: no buffer, or wrong buffer for this segment's audio
        const segUrl = seg.audio_url;
        if (segUrl) {
            // by_ayah: check URL-keyed cache first (populated by IntersectionObserver)
            const cached = segAudioBuffers.get(segUrl);
            if (cached) {
                segAudioBuffer = cached;
                segAudioBufferUrl = segUrl;
            } else {
                await decodeSegAudio(segUrl);
            }
        } else {
            // by_surah: ensure chapter buffer
            const buffer = await ensureChapterAudioBuffer(chapter);
            if (buffer) {
                segAudioBuffer = buffer;
                segAudioBufferUrl = segAllData?.audio_by_chapter?.[chapter] || '';
            }
        }
    }

    // Edit history: snapshot before entering edit mode
    _pendingOp = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment');
    _pendingOp.targets_before = [snapshotSeg(seg)];

    try {
        if (mode === 'trim') enterTrimMode(seg, row);
        else if (mode === 'split') enterSplitMode(seg, row);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        _pendingOp = null;
        segEditMode = null;
        segEditIndex = -1;
        document.body.classList.remove('seg-edit-active');
        document.querySelector('.seg-row.seg-edit-target')?.classList.remove('seg-edit-target');
    }
}

function enterTrimMode(seg, row) {
    if (segEditMode) {
        console.warn('[trim] blocked: already in edit mode:', segEditMode);
        return;
    }
    segEditMode = 'trim';
    segEditIndex = seg.index;

    // Dim other rows via CSS (O(1) instead of per-element mutation)
    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    // Create edit panel
    const panel = document.createElement('div');
    panel.className = 'seg-edit-panel';
    panel.id = 'seg-edit-panel';

    // Expanded waveform canvas
    const trimCanvas = document.createElement('canvas');
    trimCanvas.width = 600;
    trimCanvas.height = 80;
    trimCanvas.id = 'seg-trim-canvas';
    panel.appendChild(trimCanvas);

    // Time inputs
    const inputRow = document.createElement('div');
    inputRow.className = 'seg-trim-inputs';
    inputRow.innerHTML = `
        <label>Start (ms): <input type="number" id="trim-start" value="${seg.time_start}" step="10" min="0"></label>
        <label>End (ms): <input type="number" id="trim-end" value="${seg.time_end}" step="10" min="0"></label>
        <span class="seg-trim-duration" id="trim-duration">Duration: ${((seg.time_end - seg.time_start) / 1000).toFixed(2)}s</span>
    `;
    panel.appendChild(inputRow);

    // Buttons
    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    btnRow.innerHTML = `
        <button class="btn btn-sm btn-confirm" id="trim-confirm">Apply</button>
        <button class="btn btn-sm btn-cancel" id="trim-cancel">Cancel</button>
        <button class="btn btn-sm btn-preview" id="trim-preview">Preview</button>
        <span class="seg-trim-status" id="trim-status"></span>
    `;
    panel.appendChild(btnRow);

    row.after(panel);

    // Compute context window: extend to adjacent segment boundaries (or audio edges)
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const chapterSegs = (chapter === currentChapter) ? _getChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevEnd = segIdx > 0 ? chapterSegs[segIdx - 1].time_end : 0;
    const nextStart = segIdx >= 0 && segIdx < chapterSegs.length - 1
        ? chapterSegs[segIdx + 1].time_start
        : (segAudioBuffer ? segAudioBuffer.duration * 1000 : seg.time_end + 1000);
    const windowStart = prevEnd;
    const windowEnd = nextStart;
    trimCanvas._trimWindow = { windowStart, windowEnd, currentStart: seg.time_start, currentEnd: seg.time_end };

    drawTrimWaveform(trimCanvas);
    setupTrimDragHandles(trimCanvas, seg);

    document.getElementById('trim-start').addEventListener('input', () => {
        const val = parseInt(document.getElementById('trim-start').value);
        if (!isNaN(val)) {
            trimCanvas._trimWindow.currentStart = val;
            drawTrimWaveform(trimCanvas);
            updateTrimDuration();
        }
    });
    document.getElementById('trim-end').addEventListener('input', () => {
        const val = parseInt(document.getElementById('trim-end').value);
        if (!isNaN(val)) {
            trimCanvas._trimWindow.currentEnd = val;
            drawTrimWaveform(trimCanvas);
            updateTrimDuration();
        }
    });

    document.getElementById('trim-confirm').addEventListener('click', () => confirmTrim(seg));
    document.getElementById('trim-cancel').addEventListener('click', exitEditMode);
    document.getElementById('trim-preview').addEventListener('click', previewTrimAudio);
}

function drawTrimWaveform(canvas) {
    if (!segAudioBuffer) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const tw = canvas._trimWindow;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    // Draw waveform for the full window
    const sampleRate = segAudioBuffer.sampleRate;
    const rawData = segAudioBuffer.getChannelData(0);
    const startSample = Math.floor((tw.windowStart / 1000) * sampleRate);
    const endSample = Math.min(Math.floor((tw.windowEnd / 1000) * sampleRate), rawData.length);
    const totalSamples = endSample - startSample;
    if (totalSamples <= 0) return;

    const buckets = width;
    const blockSize = Math.max(1, Math.floor(totalSamples / buckets));
    const scale = height / 2 * 0.9;

    // Filled waveform
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const offset = startSample + i * blockSize;
        let max = -1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val > max) max = val;
        }
        const x = (i / buckets) * width;
        const y = centerY - max * scale;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const offset = startSample + i * blockSize;
        let min = 1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val < min) min = val;
        }
        const x = (i / buckets) * width;
        const y = centerY - min * scale;
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.stroke();

    // Dim outside the trim region
    const startX = ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;
    const endX = ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;

    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(0, 0, startX, height);
    ctx.fillRect(endX, 0, width - endX, height);

    // Start handle (green)
    ctx.strokeStyle = '#4caf50';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();
    // Handle grip
    ctx.fillStyle = '#4caf50';
    ctx.fillRect(startX - 4, height / 2 - 10, 8, 20);

    // End handle (red)
    ctx.strokeStyle = '#f44336';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(endX, 0);
    ctx.lineTo(endX, height);
    ctx.stroke();
    ctx.fillStyle = '#f44336';
    ctx.fillRect(endX - 4, height / 2 - 10, 8, 20);
}

function setupTrimDragHandles(canvas, seg) {
    let dragging = null;
    const HANDLE_THRESHOLD = 12;

    canvas.addEventListener('mousedown', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const tw = canvas._trimWindow;
        const width = canvas.width;
        const startX = ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;
        const endX = ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;

        if (Math.abs(x - startX) < HANDLE_THRESHOLD) dragging = 'start';
        else if (Math.abs(x - endX) < HANDLE_THRESHOLD) dragging = 'end';
        if (dragging) canvas.style.cursor = 'col-resize';
    });

    canvas.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const tw = canvas._trimWindow;
        const width = canvas.width;
        const timeAtX = tw.windowStart + (x / width) * (tw.windowEnd - tw.windowStart);
        const snapped = Math.round(timeAtX / 10) * 10;

        if (dragging === 'start') {
            tw.currentStart = Math.max(0, Math.min(snapped, tw.currentEnd - 50));
            document.getElementById('trim-start').value = tw.currentStart;
        } else {
            tw.currentEnd = Math.max(tw.currentStart + 50, snapped);
            document.getElementById('trim-end').value = tw.currentEnd;
        }
        updateTrimDuration();
        drawTrimWaveform(canvas);
    });

    canvas.addEventListener('mouseup', () => { dragging = null; canvas.style.cursor = 'col-resize'; });
    canvas.addEventListener('mouseleave', () => { dragging = null; canvas.style.cursor = 'col-resize'; });
}

function updateTrimDuration() {
    const s = parseInt(document.getElementById('trim-start').value);
    const e = parseInt(document.getElementById('trim-end').value);
    const el = document.getElementById('trim-duration');
    if (el && !isNaN(s) && !isNaN(e)) {
        el.textContent = `Duration: ${((e - s) / 1000).toFixed(2)}s`;
    }
}

function confirmTrim(seg) {
    const trimStatus = document.getElementById('trim-status');
    const newStart = parseInt(document.getElementById('trim-start').value);
    const newEnd = parseInt(document.getElementById('trim-end').value);
    if (isNaN(newStart) || isNaN(newEnd) || newStart >= newEnd) {
        if (trimStatus) trimStatus.textContent = 'Invalid time range';
        return;
    }

    // Use chapter segments for overlap checks
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const chapterSegs = chapter === currentChapter ? _getChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevSeg = segIdx > 0 ? chapterSegs[segIdx - 1] : null;
    const nextSeg = (segIdx >= 0 && segIdx < chapterSegs.length - 1) ? chapterSegs[segIdx + 1] : null;

    // Only check overlap when segments share the same audio file
    if (prevSeg && prevSeg.audio_url === seg.audio_url && newStart < prevSeg.time_end) {
        if (trimStatus) trimStatus.textContent = 'Start overlaps with previous segment';
        return;
    }
    if (nextSeg && nextSeg.audio_url === seg.audio_url && newEnd > nextSeg.time_start) {
        if (trimStatus) trimStatus.textContent = 'End overlaps with next segment';
        return;
    }

    // Update in-memory
    seg.time_start = newStart;
    seg.time_end = newEnd;
    markDirty(chapter, undefined, true);

    // Edit history: record applied state
    const trimOp = _pendingOp;
    _pendingOp = null;  // detach so exitEditMode doesn't null it
    if (trimOp) {
        trimOp.applied_at_utc = new Date().toISOString();
        trimOp.targets_after = [snapshotSeg(seg)];
    }

    if (chapter !== currentChapter || !segData?.segments) {
        segAllData._byChapter = null; segAllData._byChapterIndex = null;
    } else {
        syncChapterSegsToAll();
    }

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();
    syncAllCardsForSegment(seg);

    // Edit history: finalize after re-render
    if (trimOp) finalizeOp(chapter, trimOp);

    segPlayStatus.textContent = 'Adjusted (unsaved)';
}

let _previewStopHandler = null;

function previewTrimAudio() {
    // Remove any previous preview handler
    if (_previewStopHandler) {
        segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    const start = parseInt(document.getElementById('trim-start').value) / 1000;
    const end = parseInt(document.getElementById('trim-end').value) / 1000;
    if (isNaN(start) || isNaN(end)) return;

    const doPlay = () => {
        segAudioEl.currentTime = start;
        segAudioEl.playbackRate = parseFloat(segSpeedSelect.value);
        segAudioEl.play();
        _previewStopHandler = () => {
            if (segAudioEl.currentTime >= end) {
                segAudioEl.pause();
                segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
                _previewStopHandler = null;
            }
        };
        segAudioEl.addEventListener('timeupdate', _previewStopHandler);
    };

    const editChapter = segChapterSelect.value ? parseInt(segChapterSelect.value) : null;
    const editSeg = editChapter != null ? getSegByChapterIndex(editChapter, segEditIndex) : null;
    const targetUrl = editSeg && editSeg.audio_url;
    if (targetUrl && !segAudioEl.src.endsWith(targetUrl)) {
        segAudioEl.src = targetUrl;
        segAudioEl.addEventListener('canplay', doPlay, { once: true });
        segAudioEl.load();
    } else {
        doPlay();
    }
}


// ---------------------------------------------------------------------------
// Split mode
// ---------------------------------------------------------------------------

function enterSplitMode(seg, row) {
    if (segEditMode) {
        console.warn('[split] blocked: already in edit mode:', segEditMode);
        return;
    }
    segEditMode = 'split';
    segEditIndex = seg.index;

    // Dim other rows via CSS (O(1) instead of per-element mutation)
    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    const panel = document.createElement('div');
    panel.className = 'seg-edit-panel';
    panel.id = 'seg-edit-panel';

    const splitCanvas = document.createElement('canvas');
    splitCanvas.width = 600;
    splitCanvas.height = 80;
    splitCanvas.id = 'seg-split-canvas';
    panel.appendChild(splitCanvas);

    const defaultSplit = Math.round((seg.time_start + seg.time_end) / 2);

    const inputRow = document.createElement('div');
    inputRow.className = 'seg-split-inputs';
    inputRow.innerHTML = `
        <label>Split at (ms): <input type="number" id="split-time" value="${defaultSplit}" step="10"
            min="${seg.time_start + 50}" max="${seg.time_end - 50}"></label>
        <span class="seg-split-info" id="split-info">
            Left: ${((defaultSplit - seg.time_start) / 1000).toFixed(2)}s |
            Right: ${((seg.time_end - defaultSplit) / 1000).toFixed(2)}s
        </span>
    `;
    panel.appendChild(inputRow);

    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    btnRow.innerHTML = `
        <button class="btn btn-sm btn-confirm" id="split-confirm">Split</button>
        <button class="btn btn-sm btn-cancel" id="split-cancel">Cancel</button>
    `;
    panel.appendChild(btnRow);

    row.after(panel);
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    splitCanvas._splitData = { seg, currentSplit: defaultSplit };
    drawSplitWaveform(splitCanvas);
    setupSplitDragHandle(splitCanvas, seg);

    document.getElementById('split-time').addEventListener('input', () => {
        const val = parseInt(document.getElementById('split-time').value);
        if (!isNaN(val)) {
            splitCanvas._splitData.currentSplit = val;
            drawSplitWaveform(splitCanvas);
            updateSplitInfo(seg, val);
        }
    });

    document.getElementById('split-confirm').addEventListener('click', () => confirmSplit(seg));
    document.getElementById('split-cancel').addEventListener('click', exitEditMode);
}

function drawSplitWaveform(canvas) {
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);
    if (!segAudioBuffer) {
        ctx.fillStyle = '#888';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No audio loaded', width / 2, height / 2);
        return;
    }
    const centerY = height / 2;
    const sd = canvas._splitData;
    const seg = sd.seg;

    const sampleRate = segAudioBuffer.sampleRate;
    const rawData = segAudioBuffer.getChannelData(0);
    const startSample = Math.floor((seg.time_start / 1000) * sampleRate);
    const endSample = Math.min(Math.floor((seg.time_end / 1000) * sampleRate), rawData.length);
    const totalSamples = endSample - startSample;
    if (totalSamples <= 0) return;

    const buckets = width;
    const blockSize = Math.max(1, Math.floor(totalSamples / buckets));
    const scale = height / 2 * 0.9;

    // Compute max/min per bucket
    const maxVals = new Float32Array(buckets);
    const minVals = new Float32Array(buckets);
    for (let i = 0; i < buckets; i++) {
        const offset = startSample + i * blockSize;
        let mx = -1.0, mn = 1.0;
        for (let j = 0; j < blockSize && offset + j < rawData.length; j++) {
            const val = rawData[offset + j];
            if (val > mx) mx = val;
            if (val < mn) mn = val;
        }
        maxVals[i] = mx;
        minVals[i] = mn;
    }

    const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * width;

    // Draw left half (blue tint)
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const y = centerY - maxVals[i] * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    for (let i = buckets - 1; i >= 0; i--) {
        const x = (i / buckets) * width;
        const y = centerY - minVals[i] * scale;
        ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    // Tint right half differently
    ctx.fillStyle = 'rgba(255, 152, 0, 0.15)';
    ctx.fillRect(splitX, 0, width - splitX, height);

    // Waveform outline
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < buckets; i++) {
        const x = (i / buckets) * width;
        const y = centerY - maxVals[i] * scale;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Split line (yellow)
    ctx.strokeStyle = '#ffeb3b';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(splitX, 0);
    ctx.lineTo(splitX, height);
    ctx.stroke();
    // Handle grip
    ctx.fillStyle = '#ffeb3b';
    ctx.beginPath();
    ctx.moveTo(splitX - 6, 0);
    ctx.lineTo(splitX + 6, 0);
    ctx.lineTo(splitX, 8);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(splitX - 6, height);
    ctx.lineTo(splitX + 6, height);
    ctx.lineTo(splitX, height - 8);
    ctx.closePath();
    ctx.fill();
}

function setupSplitDragHandle(canvas, seg) {
    let dragging = false;

    canvas.addEventListener('mousedown', (e) => {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;
        if (Math.abs(x - splitX) < 15) {
            dragging = true;
            canvas.style.cursor = 'col-resize';
        }
    });

    canvas.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
        const snapped = Math.round(timeAtX / 10) * 10;
        sd.currentSplit = Math.max(seg.time_start + 50, Math.min(snapped, seg.time_end - 50));
        document.getElementById('split-time').value = sd.currentSplit;
        updateSplitInfo(seg, sd.currentSplit);
        drawSplitWaveform(canvas);
    });

    canvas.addEventListener('mouseup', () => { dragging = false; canvas.style.cursor = 'col-resize'; });
    canvas.addEventListener('mouseleave', () => { dragging = false; canvas.style.cursor = 'col-resize'; });
}

function updateSplitInfo(seg, splitTime) {
    const el = document.getElementById('split-info');
    if (el) {
        el.textContent = `Left: ${((splitTime - seg.time_start) / 1000).toFixed(2)}s | Right: ${((seg.time_end - splitTime) / 1000).toFixed(2)}s`;
    }
}

function confirmSplit(seg) {
    const splitTime = parseInt(document.getElementById('split-time').value);
    if (isNaN(splitTime) || splitTime <= seg.time_start || splitTime >= seg.time_end) {
        segPlayStatus.textContent = 'Invalid split point';
        return;
    }

    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const useSegData = chapter === currentChapter && segData?.segments;

    const firstHalf = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        time_end: splitTime,
    };
    const secondHalf = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        index: seg.index + 1,
        time_start: splitTime,
        matched_ref: '',
        matched_text: '',
        display_text: '',
        confidence: 0,
    };

    // Edit history: record applied state with new UIDs
    const splitOp = _pendingOp;
    _pendingOp = null;  // detach so exitEditMode doesn't null it
    if (splitOp) {
        splitOp.applied_at_utc = new Date().toISOString();
        splitOp.targets_after = [snapshotSeg(firstHalf), snapshotSeg(secondHalf)];
    }

    if (useSegData) {
        const segIdx = segData.segments.findIndex(s => s.index === seg.index);
        segData.segments.splice(segIdx, 1, firstHalf, secondHalf);
        segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        segData.segments = getChapterSegments(chapter);
    } else {
        // segData unavailable or cross-chapter: operate directly on segAllData
        const globalIdx = segAllData.segments.indexOf(seg);
        if (globalIdx !== -1) {
            segAllData.segments.splice(globalIdx, 1, firstHalf, secondHalf);
        }
        let reIdx = 0;
        segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        segAllData._byChapter = null; segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();
    invalidateLoadedErrorCards();

    // Edit history: finalize after re-render
    if (splitOp) finalizeOp(chapter, splitOp);

    segPlayStatus.textContent = 'Segment split (unsaved)';
}


// ---------------------------------------------------------------------------
// Merge
// ---------------------------------------------------------------------------

/** Merge a segment with its previous or next neighbour in the same chapter. */
function mergeAdjacent(seg, direction) {
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);

    // Get chapter segments to find neighbor
    let chapterSegs;
    if (chapter === currentChapter && segData?.segments) {
        chapterSegs = segData.segments;
    } else if (segAllData?.segments) {
        chapterSegs = getChapterSegments(chapter);
    }
    if (!chapterSegs) return;

    const idx = chapterSegs.findIndex(s => s.index === seg.index);
    if (idx === -1) return;
    const otherIdx = direction === 'prev' ? idx - 1 : idx + 1;
    if (otherIdx < 0 || otherIdx >= chapterSegs.length) return;
    const other = chapterSegs[otherIdx];

    const first = direction === 'prev' ? other : seg;
    const second = direction === 'prev' ? seg : other;

    // Edit history: snapshot before merge
    const mergeOp = createOp('merge_segments');
    mergeOp.targets_before = [snapshotSeg(first), snapshotSeg(second)];

    const firstAudio = first.audio_url || '';
    const secondAudio = second.audio_url || '';
    if (firstAudio !== secondAudio) {
        const msg = 'Cannot merge segments from different audio clips. Reassign references instead.';
        segPlayStatus.textContent = msg;
        alert(msg);
        return;
    }

    // Build merged ref
    let mergedRef = '';
    const refs = [first.matched_ref, second.matched_ref].filter(Boolean);
    if (refs.length > 0) {
        const s = refs[0].includes('-') ? refs[0].split('-')[0] : refs[0];
        const e = refs[refs.length - 1].includes('-') ? refs[refs.length - 1].split('-')[1] : refs[refs.length - 1];
        mergedRef = `${s}-${e}`;
    }

    const merged = {
        ...first,
        segment_uid: crypto.randomUUID(),
        index: first.index,
        time_start: first.time_start,
        time_end: second.time_end,
        matched_ref: mergedRef,
        matched_text: [first.matched_text, second.matched_text].filter(Boolean).join(' '),
        display_text: [first.display_text, second.display_text].filter(Boolean).join(' '),
        confidence: 1.0,
    };

    // Edit history: record applied state
    mergeOp.applied_at_utc = new Date().toISOString();
    mergeOp.targets_after = [snapshotSeg(merged)];

    if (chapter === currentChapter && segData?.segments) {
        const spliceIdx = Math.min(idx, otherIdx);
        segData.segments.splice(spliceIdx, 2, merged);
        segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (segAllData?.segments) {
        const globalFirst = segAllData.segments.indexOf(first);
        const globalSecond = segAllData.segments.indexOf(second);
        const spliceStart = Math.min(globalFirst, globalSecond);
        segAllData.segments.splice(spliceStart, 2, merged);
        let reIdx = 0;
        segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        segAllData._byChapter = null; segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    if (chapter === currentChapter && segData) {
        segData.segments = getChapterSegments(chapter);
    }
    computeSilenceAfter();
    applyVerseFilterAndRender();
    invalidateLoadedErrorCards();

    // Edit history: finalize after re-render
    finalizeOp(chapter, mergeOp);

    segPlayStatus.textContent = 'Segments merged (unsaved)';
}


// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

/** Unified delete: works for both main section and error card segments. */
function deleteSegment(seg, row) {
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const label = seg.chapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    // Edit history: snapshot before confirm dialog
    const deleteOp = createOp('delete_segment');
    deleteOp.targets_before = [snapshotSeg(seg)];

    if (!confirm(`Delete segment ${label} (${formatRef(seg.matched_ref) || 'no match'})?`)) return;

    // Edit history: user confirmed deletion
    deleteOp.applied_at_utc = new Date().toISOString();
    deleteOp.targets_after = [];

    if (chapter === currentChapter && segData?.segments) {
        // Current chapter: operate on segData.segments
        const segIdx = segData.segments.findIndex(s => s.index === seg.index);
        if (segIdx === -1) return;
        segData.segments.splice(segIdx, 1);
        segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (segAllData?.segments) {
        // Cross-chapter: operate directly on segAllData
        const globalIdx = segAllData.segments.findIndex(s => s.chapter === chapter && s.index === seg.index);
        if (globalIdx === -1) return;
        segAllData.segments.splice(globalIdx, 1);
        let idx = 0;
        segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = idx++; });
        segAllData._byChapter = null; segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);


    // Remove the error card wrapper from DOM if applicable
    if (row) {
        const wrapper = row.closest('.val-card-wrapper');
        if (wrapper) wrapper.remove();
    }

    // If deleted segment's chapter matches current chapter, re-render
    if (chapter === currentChapter && segData) {
        segData.segments = getChapterSegments(chapter);
    }

    computeSilenceAfter();
    applyVerseFilterAndRender();
    invalidateLoadedErrorCards();

    // Edit history: finalize after re-render
    finalizeOp(chapter, deleteOp);

    segPlayStatus.textContent = 'Segment deleted (unsaved)';
}


// ---------------------------------------------------------------------------
// Shared edit mode
// ---------------------------------------------------------------------------

function exitEditMode() {
    // Discard any pending edit history op (user cancelled)
    _pendingOp = null;

    // Restore audio buffer if it was swapped for cross-chapter editing
    const panel = document.getElementById('seg-edit-panel');
    if (panel) {
        const editRow = panel.previousElementSibling;
        if (editRow?._savedAudioBuffer !== undefined) {
            segAudioBuffer = editRow._savedAudioBuffer;
            segAudioBufferUrl = editRow._savedAudioBufferUrl;
            delete editRow._savedAudioBuffer;
            delete editRow._savedAudioBufferUrl;
        }
        panel.remove();
    }

    segEditMode = null;
    segEditIndex = -1;
    // Stop any preview playback
    if (_previewStopHandler) {
        segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    // Un-dim rows (O(1) — remove container class + target marker)
    document.body.classList.remove('seg-edit-active');
    document.querySelector('.seg-row.seg-edit-target')?.classList.remove('seg-edit-target');
}

function applyVerseFilterAndRender() {
    applyFiltersAndRender();
}


// ---------------------------------------------------------------------------
// Filter bar UI
// ---------------------------------------------------------------------------

function renderFilterBar() {
    segFilterRowsEl.innerHTML = '';
    segActiveFilters.forEach((f, i) => {
        const row = document.createElement('div');
        row.className = 'seg-filter-row';

        const fieldSel = document.createElement('select');
        fieldSel.className = 'seg-filter-field';
        SEG_FILTER_FIELDS.forEach(opt => {
            const o = document.createElement('option');
            o.value = opt.value; o.textContent = opt.label; o.selected = opt.value === f.field;
            fieldSel.appendChild(o);
        });
        fieldSel.addEventListener('change', () => {
            segActiveFilters[i].field = fieldSel.value; applyFiltersAndRender();
        });

        const opSel = document.createElement('select');
        opSel.className = 'seg-filter-op';
        SEG_FILTER_OPS.forEach(op => {
            const o = document.createElement('option');
            o.value = op; o.textContent = op; o.selected = op === f.op;
            opSel.appendChild(o);
        });
        opSel.addEventListener('change', () => {
            segActiveFilters[i].op = opSel.value; applyFiltersAndRender();
        });

        const valInput = document.createElement('input');
        valInput.type = 'number'; valInput.className = 'seg-filter-value';
        valInput.value = f.value ?? ''; valInput.step = 'any'; valInput.placeholder = 'value';
        valInput.addEventListener('input', () => {
            const v = parseFloat(valInput.value);
            segActiveFilters[i].value = isNaN(v) ? null : v;
            clearTimeout(_segFilterDebounceTimer);
            _segFilterDebounceTimer = setTimeout(applyFiltersAndRender, 300);
        });

        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-sm btn-cancel seg-filter-remove';
        removeBtn.textContent = '×';
        removeBtn.addEventListener('click', () => {
            segActiveFilters.splice(i, 1);
            renderFilterBar(); updateFilterBarControls(); applyFiltersAndRender();
        });

        row.append(fieldSel, opSel, valInput, removeBtn);
        segFilterRowsEl.appendChild(row);
    });
}

function updateFilterBarControls() {
    const n = segActiveFilters.length;
    if (segFilterCountEl) segFilterCountEl.textContent = n > 0 ? `(${n})` : '';
    if (segFilterClearBtn) segFilterClearBtn.hidden = n === 0;
}

function addSegFilterCondition() {
    segActiveFilters.push({ field: 'duration_s', op: '>', value: null });
    renderFilterBar(); updateFilterBarControls();
    // Focus the value input of the new row
    segFilterRowsEl.querySelectorAll('.seg-filter-value').forEach((el, i, arr) => {
        if (i === arr.length - 1) el.focus();
    });
}

function clearAllSegFilters() {
    segActiveFilters = [];
    _segSavedFilterView = null;
    renderFilterBar(); updateFilterBarControls(); applyFiltersAndRender();
}


// ---------------------------------------------------------------------------
// Validation panel
// ---------------------------------------------------------------------------

function captureValPanelState(targetEl) {
    const state = {};
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        const cat = d.getAttribute('data-category');
        const cardsDiv = d.querySelector('.val-cards-container');
        state[cat] = {
            open: d.open,
            loaded: cardsDiv && !cardsDiv.hidden && cardsDiv.children.length > 0
        };
    });
    return state;
}

function restoreValPanelState(targetEl, state) {
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        const cat = d.getAttribute('data-category');
        const s = state[cat];
        if (!s) return;
        if (s.open) d.open = true;
        if (s.loaded) {
            const loadBtn = d.querySelector('.val-load-all-btn');
            if (loadBtn) loadBtn.click();
        }
    });
}

/** Close all accordion cards except the given one across both validation panels. */
function _collapseAccordionExcept(exceptDetails) {
    [segValidationEl, segValidationGlobalEl].forEach(panel => {
        if (!panel) return;
        panel.querySelectorAll('details[data-category]').forEach(d => {
            if (d === exceptDetails) return;
            if (d.open) d.open = false;  // toggle handler cleans up cards
        });
    });
}

function renderValidationPanel(data, chapter = null, targetEl = segValidationEl, label = null) {
    targetEl.innerHTML = '';
    if (!data) { targetEl.hidden = true; return; }

    let { errors: errs, missing_verses: mv, missing_words: mw, failed, low_confidence, oversegmented: os, cross_verse: cv, audio_bleeding: ab } = data;

    if (chapter !== null) {
        errs           = (errs           || []).filter(i => i.chapter === chapter);
        mv             = (mv             || []).filter(i => i.chapter === chapter);
        mw             = (mw             || []).filter(i => i.chapter === chapter);
        failed         = (failed         || []).filter(i => i.chapter === chapter);
        low_confidence = (low_confidence || []).filter(i => i.chapter === chapter);
        os             = (os             || []).filter(i => i.chapter === chapter);
        cv             = (cv             || []).filter(i => i.chapter === chapter);
        ab             = (ab             || []).filter(i => i.chapter === chapter);
    }
    const hasAny = (errs && errs.length > 0) || (mv && mv.length > 0) || (mw && mw.length > 0)
        || (failed && failed.length > 0) || (low_confidence && low_confidence.length > 0) || (os && os.length > 0)
        || (cv && cv.length > 0) || (ab && ab.length > 0);
    if (!hasAny) {
        targetEl.hidden = true;
        return;
    }
    targetEl.hidden = false;

    if (label) {
        const labelEl = document.createElement('div');
        labelEl.className = 'val-section-label';
        labelEl.textContent = label;
        targetEl.appendChild(labelEl);
    }

    const isGlobal = chapter === null;

    const categories = [
        {
            name: 'Failed Alignments', items: failed, type: 'failed', countClass: 'has-errors',
            getLabel: i => `${i.chapter}:#${i.seg_index}`, getTitle: i => `${i.time}`, btnClass: 'val-error',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Missing Verses', items: mv, type: 'missing_verses', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToMissingVerseContext(i.chapter, i.verse_key)
        },
        {
            name: 'Missing Words', items: mw, type: 'missing_words', countClass: 'has-errors',
            getLabel: i => {
                const indices = i.seg_indices || [];
                return indices.length > 0 ? `${i.verse_key} #${indices.join('/#')}` : i.verse_key;
            },
            getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => {
                const indices = i.seg_indices || [];
                if (indices.length > 0) jumpToSegment(i.chapter, indices[0]);
                else jumpToVerse(i.chapter, i.verse_key);
            }
        },
        {
            name: 'Structural Errors', items: errs, type: 'errors', countClass: 'has-errors',
            getLabel: i => i.verse_key, getTitle: i => i.msg, btnClass: 'val-error',
            onClick: i => jumpToVerse(i.chapter, i.verse_key)
        },
        {
            name: 'Low Confidence', items: low_confidence, type: 'low_confidence', countClass: 'has-warnings',
            getLabel: i => i.ref,
            getTitle: i => `${(i.confidence * 100).toFixed(1)}%`,
            btnClass: i => i.confidence < 0.60 ? 'val-conf-low' : 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Potentially Oversegmented', items: os, type: 'oversegmented', countClass: 'has-warnings',
            getLabel: i => i.ref, getTitle: i => i.verse_key, btnClass: 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Cross-verse', items: cv, type: 'cross_verse', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Audio Bleeding', items: ab, type: 'audio_bleeding', countClass: 'has-warnings',
            getLabel: i => `${i.entry_ref}\u2192${i.matched_verse}`,
            getTitle: i => `audio ${i.entry_ref} contains segment matching ${i.ref} (${i.time})`,
            btnClass: 'val-bleed',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        }
    ];

    categories.forEach(cat => {
        if (!cat.items || cat.items.length === 0) return;

        const details = document.createElement('details');
        details.setAttribute('data-category', cat.type);
        const summary = document.createElement('summary');
        summary.innerHTML = `${cat.name} <span class="val-count ${cat.countClass}">${cat.items.length}</span>`;

        // Load All button
        const loadBtn = document.createElement('button');
        loadBtn.className = 'val-load-all-btn';
        loadBtn.textContent = 'Load All';
        loadBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();
            const cardsDiv = details.querySelector('.val-cards-container');
            if (!cardsDiv) return;
            if (cardsDiv.children.length > 0) {
                // Hide: clear cards and detach scroll preload
                _detachScrollPreload(cardsDiv);
                cardsDiv.innerHTML = '';
                cardsDiv.hidden = true;
                loadBtn.textContent = 'Load All';
            } else {
                // Collapse all other accordions first
                _collapseAccordionExcept(details);
                renderCategoryCards(cat.type, cat.items, cardsDiv);
                cardsDiv.hidden = false;
                loadBtn.textContent = 'Hide All';
                details.open = true;
            }
        });
        summary.appendChild(loadBtn);

        details.appendChild(summary);

        // Button list
        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        cat.items.forEach(issue => {
            const btn = document.createElement('button');
            const cls = typeof cat.btnClass === 'function' ? cat.btnClass(issue) : cat.btnClass;
            btn.className = `val-btn ${cls}`;
            btn.textContent = cat.getLabel(issue);
            btn.title = cat.getTitle(issue) || '';
            btn.addEventListener('click', () => cat.onClick(issue));
            itemsDiv.appendChild(btn);
        });
        details.appendChild(itemsDiv);

        // Cards container (hidden initially)
        const cardsDiv = document.createElement('div');
        cardsDiv.className = 'val-cards-container';
        cardsDiv.hidden = true;
        details.appendChild(cardsDiv);

        // Mutual exclusivity: opening this accordion closes all others;
        // closing clears loaded cards and aborts in-flight audio fetches
        details.addEventListener('toggle', () => {
            if (details.open) {
                _collapseAccordionExcept(details);
            } else {
                const cd = details.querySelector('.val-cards-container');
                if (cd) {
                    _detachScrollPreload(cd);
                    if (cd.children.length > 0) {
                        cd.innerHTML = '';
                        cd.hidden = true;
                        const btn = details.querySelector('.val-load-all-btn');
                        if (btn) btn.textContent = 'Load All';
                    }
                }
                if (_scrollAbortController) _scrollAbortController.abort();
            }
        });

        targetEl.appendChild(details);
    });
}

async function jumpToSegment(chapter, segIndex) {
    // If jumping from filter view, temporarily clear filters to show full chapter
    const fromFilterView = !!_segSavedFilterView;
    if (fromFilterView) {
        segActiveFilters = [];
        renderFilterBar();
        updateFilterBarControls();
    }

    // Load the chapter if not already loaded
    if (segChapterSelect.value !== String(chapter)) {
        segChapterSelect.value = String(chapter);
        if (segChapterSS) segChapterSS.refresh();
        await onSegChapterChange();
    } else if (fromFilterView) {
        // Same chapter but filters changed — re-render unfiltered
        applyFiltersAndRender();
    }

    // Scroll to the segment
    const row = segListEl.querySelector(`.seg-row[data-seg-index="${segIndex}"]`);
    if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('playing');
        setTimeout(() => row.classList.remove('playing'), 2000);
    }

    // Show "Back to results" banner if we came from filter view
    if (fromFilterView) {
        _showBackToResultsBanner();
    }
}

function _parseVerseFromKey(verseKey) {
    const parts = (verseKey || '').split(':');
    if (parts.length < 2) return null;
    const verse = parseInt(parts[1], 10);
    return Number.isFinite(verse) ? verse : null;
}

function findMissingVerseBoundarySegments(chapter, verseKey) {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) return { prev: null, next: null, targetVerse: null, covered: false };

    const segs = getChapterSegments(chapter);
    let prev = null;
    let prevVerse = -Infinity;
    let next = null;
    let nextVerse = Infinity;

    for (const seg of segs) {
        const parsed = parseSegRef(seg.matched_ref);
        if (!parsed) continue;

        if (parsed.ayah_from <= targetVerse && targetVerse <= parsed.ayah_to) {
            return { prev: seg, next: seg, targetVerse, covered: true };
        }

        if (parsed.ayah_to < targetVerse && parsed.ayah_to > prevVerse) {
            prev = seg;
            prevVerse = parsed.ayah_to;
        }
        if (parsed.ayah_from > targetVerse && parsed.ayah_from < nextVerse) {
            next = seg;
            nextVerse = parsed.ayah_from;
        }
    }

    return { prev, next, targetVerse, covered: false };
}

async function jumpToMissingVerseContext(chapter, verseKey) {
    const targetVerse = _parseVerseFromKey(verseKey);
    if (!targetVerse) {
        await jumpToVerse(chapter, verseKey);
        return;
    }

    // Preserve current filter view so users can jump back after boundary navigation.
    const hasFilterView = segActiveFilters.some(f => f.value !== null) || !!segVerseSelect.value;
    if (hasFilterView) {
        _segSavedFilterView = {
            filters: JSON.parse(JSON.stringify(segActiveFilters)),
            chapter: segChapterSelect.value,
            verse: segVerseSelect.value,
            scrollTop: segListEl.scrollTop,
        };
    }

    if (segChapterSelect.value !== String(chapter)) {
        segChapterSelect.value = String(chapter);
        if (segChapterSS) segChapterSS.refresh();
        await onSegChapterChange();
    }

    if (hasFilterView) {
        segActiveFilters = [];
        renderFilterBar();
        updateFilterBarControls();
    }
    if (segVerseSelect.value) {
        segVerseSelect.value = '';
    }
    applyFiltersAndRender();

    const { prev, next, covered } = findMissingVerseBoundarySegments(chapter, verseKey);
    if (covered && prev) {
        await jumpToSegment(chapter, prev.index);
        return;
    }

    const rows = [];
    if (prev) {
        const row = segListEl.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${prev.index}"]`);
        if (row) rows.push(row);
    }
    if (next && (!prev || next.index !== prev.index)) {
        const row = segListEl.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${next.index}"]`);
        if (row) rows.push(row);
    }

    if (rows.length === 0) {
        segPlayStatus.textContent = `Could not locate boundary segments for missing verse ${verseKey}.`;
        return;
    }

    if (rows.length === 1) {
        rows[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else {
        const top = Math.min(...rows.map(r => r.offsetTop));
        const bottom = Math.max(...rows.map(r => r.offsetTop + r.offsetHeight));
        const targetTop = Math.max(0, ((top + bottom) / 2) - (segListEl.clientHeight / 2));
        segListEl.scrollTo({ top: targetTop, behavior: 'smooth' });
    }

    rows.forEach(r => r.classList.add('playing'));
    setTimeout(() => rows.forEach(r => r.classList.remove('playing')), 2000);

    if (prev && next) {
        segPlayStatus.textContent = `Missing verse ${verseKey} is between #${prev.index} and #${next.index}.`;
    } else if (prev) {
        segPlayStatus.textContent = `Missing verse ${verseKey} is after #${prev.index}.`;
    } else {
        segPlayStatus.textContent = `Missing verse ${verseKey} is before #${next.index}.`;
    }

    if (hasFilterView) {
        _showBackToResultsBanner();
    }
}



async function jumpToVerse(chapter, verseKey) {
    // Load chapter, then find the first segment matching this verse
    if (segChapterSelect.value !== String(chapter)) {
        segChapterSelect.value = String(chapter);
        if (segChapterSS) segChapterSS.refresh();
        await onSegChapterChange();
    }
    if (!segAllData) return;
    // Find first segment whose matched_ref contains this verse
    const parts = verseKey.split(':');
    const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : verseKey;
    const seg = segAllData.segments.find(s =>
        s.chapter === parseInt(chapter) && s.matched_ref && s.matched_ref.startsWith(prefix)
    );
    if (seg) {
        const row = segListEl.querySelector(`.seg-row[data-seg-index="${seg.index}"]`);
        if (row) {
            row.scrollIntoView({ behavior: 'smooth', block: 'center' });
            row.classList.add('playing');
            setTimeout(() => row.classList.remove('playing'), 2000);
        }
        return;
    }
    segPlayStatus.textContent = `No segment found for verse ${verseKey}.`;
}

async function refreshValidation() {
    const reciter = segReciterSelect.value;
    if (!reciter) return;
    try {
        const globalState = captureValPanelState(segValidationGlobalEl);
        const chState = captureValPanelState(segValidationEl);
        const valResp = await fetch(`/api/seg/validate/${reciter}`);
        segValidation = await valResp.json();
        const ch = segChapterSelect.value ? parseInt(segChapterSelect.value) : null;
        if (ch !== null) {
            renderValidationPanel(segValidation, null, segValidationGlobalEl, 'All Chapters');
            renderValidationPanel(segValidation, ch, segValidationEl, `Chapter ${ch}`);
            restoreValPanelState(segValidationGlobalEl, globalState);
            restoreValPanelState(segValidationEl, chState);
        } else {
            segValidationGlobalEl.hidden = true;
            segValidationGlobalEl.innerHTML = '';
            renderValidationPanel(segValidation, null, segValidationEl);
            restoreValPanelState(segValidationEl, chState);
        }
        // Re-render segment list to update tags
        if (segData && segData.segments) {
            applyFiltersAndRender();
        } else if (segDisplayedSegments) {
            renderSegList(segDisplayedSegments);
        }
    } catch (e) {
        console.error('Error refreshing validation:', e);
    }
}


// ---------------------------------------------------------------------------
// Filter view save / restore (Go To → Back navigation)
// ---------------------------------------------------------------------------

function _showBackToResultsBanner() {
    segListEl.querySelector('.seg-back-banner')?.remove();
    const banner = document.createElement('div');
    banner.className = 'seg-back-banner';
    banner.innerHTML = '<button class="btn btn-sm seg-back-btn">\u2190 Back to filter results</button>';
    banner.querySelector('.seg-back-btn').addEventListener('click', _restoreFilterView);
    segListEl.insertBefore(banner, segListEl.firstChild);
}

function _restoreFilterView() {
    if (!_segSavedFilterView) return;
    const saved = _segSavedFilterView;
    _segSavedFilterView = null;

    // Restore filter conditions
    segActiveFilters = saved.filters;
    renderFilterBar();
    updateFilterBarControls();

    // Restore chapter/verse selection
    if (saved.chapter !== segChapterSelect.value) {
        segChapterSelect.value = saved.chapter;
        if (segChapterSS) segChapterSS.refresh();
    }
    segVerseSelect.value = saved.verse;

    // Re-render with restored filters
    applyFiltersAndRender();

    // Restore scroll position after render
    requestAnimationFrame(() => {
        segListEl.scrollTop = saved.scrollTop;
    });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRef(ref) {
    // Show "s:v" instead of "s:v:1-s:v:N" when segment covers an entire verse
    if (!ref) return '(no match)';
    const vwc = (segAllData && segAllData.verse_word_counts) || (segData && segData.verse_word_counts);
    if (!vwc) return ref;
    const parts = ref.split('-');
    if (parts.length !== 2) return ref;
    const start = parts[0].split(':');
    const end = parts[1].split(':');
    if (start.length !== 3 || end.length !== 3) return ref;
    // Same sura and verse, word 1 to last word
    if (start[0] === end[0] && start[1] === end[1] && start[2] === '1') {
        const key = `${start[0]}:${start[1]}`;
        const totalWords = vwc[key];
        if (totalWords && parseInt(end[2]) === totalWords) {
            return key;
        }
    }
    return ref;
}

function formatTimeMs(ms) {
    if (!isFinite(ms)) return '0:00';
    const totalSec = ms / 1000;
    const mins = Math.floor(totalSec / 60);
    const secs = Math.floor(totalSec % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatDurationMs(ms) {
    if (!isFinite(ms) || ms === 0) return '0s';
    const seconds = ms / 1000;
    if (seconds < 60) return seconds.toFixed(1) + 's';
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}


// ---------------------------------------------------------------------------
// Error Card helpers (Load All in global validation panel)
// ---------------------------------------------------------------------------

/** Build lazily-indexed per-chapter segment lookup from segAllData */
function getChapterSegments(chapter) {
    if (!segAllData || !segAllData.segments) return [];
    if (!segAllData._byChapter) {
        segAllData._byChapter = {};
        segAllData._byChapterIndex = new Map();
        segAllData.segments.forEach(s => {
            const ch = s.chapter;
            if (!segAllData._byChapter[ch]) segAllData._byChapter[ch] = [];
            segAllData._byChapter[ch].push(s);
            segAllData._byChapterIndex.set(`${ch}:${s.index}`, s);
        });
        // Sort each chapter's segments by index
        for (const ch of Object.keys(segAllData._byChapter)) {
            segAllData._byChapter[ch].sort((a, b) => a.index - b.index);
        }
    }
    return segAllData._byChapter[chapter] || [];
}

function getSegByChapterIndex(chapter, index) {
    if (!segAllData || !segAllData.segments) return null;
    // Ensure index is built
    if (!segAllData._byChapterIndex) getChapterSegments(chapter);
    return segAllData._byChapterIndex.get(`${chapter}:${index}`) || null;
}

function getAdjacentSegments(chapter, index) {
    const segs = getChapterSegments(chapter);
    const pos = segs.findIndex(s => s.index === index);
    return {
        prev: pos > 0 ? segs[pos - 1] : null,
        next: pos >= 0 && pos < segs.length - 1 ? segs[pos + 1] : null
    };
}

/** Shared <audio> element for error card playback */
let valCardAudio = null;
let valCardPlayingBtn = null;
let valCardStopTime = null;
let valCardAnimId = null;    // rAF handle for error card waveform animation
let valCardAnimSeg = null;   // segment currently being animated

function getValCardAudio() {
    if (!valCardAudio) {
        valCardAudio = document.createElement('audio');
        valCardAudio.addEventListener('timeupdate', () => {
            if (valCardStopTime !== null && valCardAudio.currentTime >= valCardStopTime) {
                stopErrorCardAudio();
            }
        });
        valCardAudio.addEventListener('ended', () => {
            stopErrorCardAudio();
        });
        valCardAudio.addEventListener('play', () => {
            segPlayBtn.textContent = 'Pause';
            _activeAudioSource = 'error';
        });
        valCardAudio.addEventListener('pause', () => {
            if (segAudioEl.paused) segPlayBtn.textContent = 'Play';
            if (_activeAudioSource === 'error') _activeAudioSource = null;
        });
    }
    return valCardAudio;
}

function stopErrorCardAudio() {
    if (!valCardAudio) return;
    valCardAudio.pause();
    valCardStopTime = null;
    if (valCardPlayingBtn) {
        valCardPlayingBtn.textContent = '\u25B6';
        valCardPlayingBtn = null;
    }
    if (_activeAudioSource === 'error') _activeAudioSource = null;
}

function _startValCardAnimation(btn, seg) {
    if (valCardAnimId) cancelAnimationFrame(valCardAnimId);
    valCardAnimSeg = seg;

    const row = btn.closest('.seg-row');
    const canvas = row ? row.querySelector('canvas') : null;
    if (!canvas) return;

    const chapter = seg.chapter;
    const currentChapter = parseInt(segChapterSelect.value);

    function getBuffer() {
        // By-ayah: prefer URL-keyed buffer
        if (seg.audio_url) return segAudioBuffers.get(seg.audio_url) || null;
        if (chapter === currentChapter) return segAudioBuffer;
        return segAudioBuffers.get(chapter) || null;
    }

    function frame() {
        if (valCardPlayingBtn !== btn) {
            // Stopped — redraw static waveform
            const buf = getBuffer();
            if (buf && canvas) {
                const saved = segAudioBuffer;
                segAudioBuffer = buf;
                drawSegmentWaveform(canvas, seg.time_start, seg.time_end);
                segAudioBuffer = saved;
            }
            valCardAnimId = null;
            valCardAnimSeg = null;
            return;
        }
        const buf = getBuffer();
        if (buf) {
            const timeMs = getValCardAudio().currentTime * 1000;
            const saved = segAudioBuffer;
            segAudioBuffer = buf;
            drawSegPlayhead(canvas, seg.time_start, seg.time_end, timeMs);
            segAudioBuffer = saved;
        }
        valCardAnimId = requestAnimationFrame(frame);
    }
    valCardAnimId = requestAnimationFrame(frame);
}

function playErrorCardAudio(seg, btn) {
    const audio = getValCardAudio();

    // If already playing this button, stop
    if (valCardPlayingBtn === btn && !audio.paused) {
        stopErrorCardAudio();
        return;
    }

    // Abort in-flight scroll preloads to free browser connections for playback
    if (_scrollAbortController) _scrollAbortController.abort();

    // Pause main audio if playing
    if (!segAudioEl.paused) {
        _segContinuousPlay = false;
        segAudioEl.pause();
    }
    _activeAudioSource = 'error';

    // Reset previous button
    if (valCardPlayingBtn) valCardPlayingBtn.textContent = '\u25B6';

    const audioUrl = seg.audio_url || (segAllData && segAllData.audio_by_chapter && segAllData.audio_by_chapter[seg.chapter]) || '';
    if (!audioUrl) return;

    const startSec = (seg.time_start || 0) / 1000;
    const endSec = (seg.time_end || 0) / 1000;

    if (audio.src !== audioUrl && audio.getAttribute('data-url') !== audioUrl) {
        audio.src = audioUrl;
        audio.setAttribute('data-url', audioUrl);
        audio.addEventListener('loadedmetadata', function onLoad() {
            audio.removeEventListener('loadedmetadata', onLoad);
            audio.currentTime = startSec;
            valCardStopTime = endSec;
            audio.playbackRate = parseFloat(segSpeedSelect.value);
            audio.play();
        });
    } else {
        audio.currentTime = startSec;
        valCardStopTime = endSec;
        audio.playbackRate = parseFloat(segSpeedSelect.value);
        audio.play();
    }

    btn.textContent = '\u23F9';
    valCardPlayingBtn = btn;
    _startValCardAnimation(btn, seg);
}

function invalidateLoadedErrorCards() {
    if (_scrollAbortController) _scrollAbortController.abort();
    document.querySelectorAll('.val-cards-container').forEach(container => {
        if (container.children.length > 0) {
            _detachScrollPreload(container);
            container.innerHTML = '';
            container.hidden = true;
            const details = container.closest('details');
            if (details) {
                const loadBtn = details.querySelector('.val-load-all-btn');
                if (loadBtn) loadBtn.textContent = 'Load All';
            }
        }
    });
}

/**
 * Render an error card for a segment — thin wrapper around renderSegCard.
 * @param {object} seg — segment from segAllData.segments
 * @param {object} options — { isContext, contextLabel }
 */
function renderErrorCard(seg, options = {}) {
    const { isContext = false, contextLabel = '' } = options;
    return renderSegCard(seg, {
        showChapter: true,
        showPlayBtn: !isContext,
        showGotoBtn: true,
        isContext,
        contextLabel,
    });
}

/**
 * Render all error cards for one validation category into a container.
 * @param {string} type — 'errors'|'missing_verses'|'missing_words'|'failed'|'low_confidence'|'cross_verse'
 * @param {Array} items — issues array for this category
 * @param {HTMLElement} container — target container div
 */
function renderCategoryCards(type, items, container) {
    container.innerHTML = '';
    if (!segAllData || !items || items.length === 0) return;

    items.forEach(issue => {
        if (type === 'missing_words') {
            // Combined card: gap label + bordering segments
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';

            const gapLabel = document.createElement('div');
            gapLabel.className = 'val-card-gap-label';
            gapLabel.textContent = issue.msg || 'Missing words between segments';
            wrapper.appendChild(gapLabel);

            const indices = issue.seg_indices || [];
            const segsInWrapper = [];
            indices.forEach(idx => {
                const seg = getSegByChapterIndex(issue.chapter, idx);
                if (seg) {
                    const card = renderErrorCard(seg);
                    wrapper.appendChild(card);
                    segsInWrapper.push({ seg, card });
                }
            });

            // Auto Fix button (only present when backend computed a fix)
            if (issue.auto_fix) {
                const fixBtn = document.createElement('button');
                fixBtn.className = 'val-autofix-btn';
                fixBtn.textContent = 'Auto Fix';
                fixBtn.title = 'Extend segment ref to cover the missing word';
                fixBtn.addEventListener('click', async () => {
                    const af = issue.auto_fix;
                    const seg = getSegByChapterIndex(issue.chapter, af.target_seg_index);
                    if (!seg) return;

                    // Snapshot state before fix
                    const oldRef = seg.matched_ref || '';
                    const oldText = seg.matched_text || '';
                    const oldDisplay = seg.display_text || '';
                    const oldConf = seg.confidence;
                    const segChapter = seg.chapter || issue.chapter;
                    const wasDirty = isIndexDirty(segChapter, seg.index);

                    // Edit history: set up auto_fix op before commitRefEdit
                    _pendingOp = createOp('auto_fix_missing_word', {
                        contextCategory: 'missing_words', fixKind: 'auto_fix'
                    });
                    _pendingOp.targets_before = [snapshotSeg(seg)];
                    const _autoFixOpId = _pendingOp.op_id;

                    const newRef = `${af.new_ref_start}-${af.new_ref_end}`;
                    const entry = segsInWrapper.find(s => s.seg === seg);
                    const card = entry?.card || wrapper;
                    await commitRefEdit(seg, newRef, card);
                    wrapper.style.opacity = '0.5';
                    fixBtn.disabled = true;
                    fixBtn.textContent = 'Fixed (save to apply)';

                    // Add Undo button
                    const undoBtn = document.createElement('button');
                    undoBtn.className = 'val-undo-btn';
                    undoBtn.textContent = 'Undo';
                    undoBtn.title = 'Revert auto-fix';
                    undoBtn.addEventListener('click', () => {
                        seg.matched_ref = oldRef;
                        seg.matched_text = oldText;
                        seg.display_text = oldDisplay;
                        seg.confidence = oldConf;
                        if (!wasDirty) unmarkDirty(segChapter, seg.index);
                        fixBtn.disabled = false;
                        fixBtn.textContent = 'Auto Fix';
                        wrapper.style.opacity = '1';
                        syncAllCardsForSegment(seg);
                        undoBtn.remove();
                        segSaveBtn.disabled = !isDirty();
                        // Edit history: remove the auto-fix op from log
                        const ops = segOpLog.get(segChapter);
                        if (ops) {
                            const idx = ops.findIndex(o => o.op_id === _autoFixOpId);
                            if (idx !== -1) ops.splice(idx, 1);
                        }
                    });
                    fixBtn.after(undoBtn);
                });
                wrapper.appendChild(fixBtn);
            }

            // Show Context button
            if (segsInWrapper.length > 0) {
                addContextToggle(wrapper, segsInWrapper);
            }

            container.appendChild(wrapper);
        } else if (type === 'missing_verses') {
            // Missing verse context: show boundary cards around where the verse should appear.
            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';

            const msgLabel = document.createElement('div');
            msgLabel.className = 'val-card-issue-label';
            msgLabel.textContent = issue.msg ? `${issue.verse_key} — ${issue.msg}` : issue.verse_key;
            wrapper.appendChild(msgLabel);

            const { prev, next } = findMissingVerseBoundarySegments(issue.chapter, issue.verse_key);
            const segsInWrapper = [];

            if (prev) {
                const prevCard = renderErrorCard(prev, { contextLabel: 'Previous verse boundary' });
                wrapper.appendChild(prevCard);
                segsInWrapper.push({ seg: prev, card: prevCard });
            }
            if (next && (!prev || next.index !== prev.index)) {
                const nextCard = renderErrorCard(next, { contextLabel: 'Next verse boundary' });
                wrapper.appendChild(nextCard);
                segsInWrapper.push({ seg: next, card: nextCard });
            }

            if (segsInWrapper.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'seg-loading';
                empty.textContent = 'No boundary segments found for this missing verse.';
                wrapper.appendChild(empty);
            } else {
                addContextToggle(wrapper, segsInWrapper);
            }

            container.appendChild(wrapper);
        } else {
            // Single segment card
            const seg = resolveIssueToSegment(type, issue);
            if (!seg) return;

            const wrapper = document.createElement('div');
            wrapper.className = 'val-card-wrapper';

            if (issue.msg) {
                const msgLabel = document.createElement('div');
                msgLabel.className = 'val-card-issue-label';
                msgLabel.textContent = issue.msg;
                wrapper.appendChild(msgLabel);
            }

            const card = renderErrorCard(seg);
            wrapper.appendChild(card);

            // Ignore button for low confidence, oversegmented, and cross-verse segments
            // For oversegmented/cross_verse, always show (confidence=1.0 items are filtered server-side)
            // For low_confidence, only show when confidence is still below 1.0
            if ((type === 'oversegmented' || type === 'cross_verse') ||
                (type === 'low_confidence' && seg.confidence < 1.0)) {
                const ignoreBtn = document.createElement('button');
                ignoreBtn.className = 'val-autofix-btn';
                // If confidence is already 1.0 (e.g., set by another panel or after index renumber),
                // show as already-ignored to avoid a no-op click
                if (seg.confidence >= 1.0) {
                    ignoreBtn.disabled = true;
                    ignoreBtn.textContent = 'Ignored';
                    wrapper.style.opacity = '0.5';
                } else {
                    ignoreBtn.textContent = 'Ignore';
                    ignoreBtn.title = 'Set confidence to 100% (dismiss this issue)';
                }
                ignoreBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (seg.confidence >= 1.0) return;
                    const segChapter = seg.chapter || parseInt(segChapterSelect.value);

                    // Edit history: snapshot before modification
                    let ignoreOp;
                    try {
                        ignoreOp = createOp('ignore_issue', {
                            contextCategory: type, fixKind: 'ignore'
                        });
                        ignoreOp.targets_before = [snapshotSeg(seg)];
                        ignoreOp.applied_at_utc = ignoreOp.started_at_utc;
                    } catch (err) {
                        console.warn('Ignore: edit history snapshot failed:', err);
                    }

                    seg.confidence = 1.0;
                    delete seg._derived;
                    markDirty(segChapter, seg.index);
                    syncAllCardsForSegment(seg);

                    // Edit history: finalize
                    if (ignoreOp) {
                        try {
                            ignoreOp.targets_after = [snapshotSeg(seg)];
                            finalizeOp(segChapter, ignoreOp);
                        } catch (err) {
                            console.warn('Ignore: edit history finalize failed:', err);
                        }
                    }

                    ignoreBtn.disabled = true;
                    ignoreBtn.textContent = 'Ignored';
                    wrapper.style.opacity = '0.5';
                });
                wrapper.appendChild(ignoreBtn);
            }

            const contextDefault = type === 'failed' || type === 'oversegmented' || type === 'audio_bleeding';
            addContextToggle(wrapper, [{ seg, card }], { defaultOpen: contextDefault });
            container.appendChild(wrapper);
        }
    });

    // Observe error card canvases for lazy waveform drawing
    const observer = _ensureWaveformObserver();
    container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));

    // Attach scroll-based audio preloading for this container
    _attachScrollPreload(container);

    // Fetch peaks for chapters referenced by these error items if not yet available
    if (segPeaksByAudio) {
        const missingChapters = new Set();
        items.forEach(item => {
            const ch = item.chapter;
            if (!ch) return;
            const url = segAllData?.audio_by_chapter?.[String(ch)] || '';
            if (url && !segPeaksByAudio[url]) missingChapters.add(ch);
        });
        if (missingChapters.size > 0) {
            const reciter = segReciterSelect.value;
            if (reciter) _fetchPeaks(reciter, [...missingChapters]);
        }
    }
}

function resolveIssueToSegment(type, issue) {
    if (type === 'failed' || type === 'low_confidence' || type === 'oversegmented' || type === 'cross_verse' || type === 'audio_bleeding') {
        const seg = getSegByChapterIndex(issue.chapter, issue.seg_index);
        // After structural ops (split/merge/delete), indices are renumbered but
        // stale validation data still references old indices. Fall back to ref match.
        if (seg && issue.ref && seg.matched_ref !== issue.ref) {
            const byRef = getChapterSegments(issue.chapter).find(s => s.matched_ref === issue.ref);
            if (byRef) return byRef;
        }
        return seg;
    }
    if (type === 'errors') {
        // Try to find a segment whose matched_ref starts with the verse_key prefix
        const parts = (issue.verse_key || '').split(':');
        const prefix = parts.length >= 2 ? `${parts[0]}:${parts[1]}:` : issue.verse_key;
        const chapterSegs = getChapterSegments(issue.chapter);
        return chapterSegs.find(s => s.matched_ref && s.matched_ref.startsWith(prefix)) || chapterSegs[0] || null;
    }
    return null;
}

function addContextToggle(wrapper, segsInWrapper, { defaultOpen = false } = {}) {
    const ctxBtn = document.createElement('button');
    ctxBtn.className = 'val-context-btn';
    ctxBtn.textContent = 'Show Context';
    let contextShown = false;
    let contextEls = [];

    function showContext() {
        const first = segsInWrapper[0];
        const last = segsInWrapper[segsInWrapper.length - 1];

        const { prev } = getAdjacentSegments(first.seg.chapter, first.seg.index);
        const { next } = getAdjacentSegments(last.seg.chapter, last.seg.index);

        if (prev) {
            const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' });
            first.card.parentNode.insertBefore(prevCard, first.card);
            contextEls.push(prevCard);
        }
        if (next) {
            const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' });
            if (last.card.nextSibling) {
                last.card.parentNode.insertBefore(nextCard, last.card.nextSibling);
            } else {
                last.card.parentNode.insertBefore(nextCard, ctxBtn);
            }
            contextEls.push(nextCard);
        }
        ctxBtn.textContent = 'Hide Context';
        contextShown = true;
    }

    function hideContext() {
        contextEls.forEach(el => el.remove());
        contextEls = [];
        ctxBtn.textContent = 'Show Context';
        contextShown = false;
    }

    ctxBtn.addEventListener('click', () => {
        if (contextShown) hideContext();
        else showContext();
    });

    wrapper.appendChild(ctxBtn);

    if (defaultOpen) showContext();
}


// ---------------------------------------------------------------------------
// Segmentation Stats Panel
// ---------------------------------------------------------------------------

function renderStatsPanel(data) {
    if (!data || data.error) return;
    segStatsPanel.hidden = false;

    const vad = data.vad_params;

    // Charts
    const charts = [
        {
            key: 'pause_duration_ms', title: 'Pause Duration (ms)',
            refLine: vad.min_silence_ms, refLabel: 'threshold',
            barColor: (bin, i, bins) => bin < vad.min_silence_ms ? '#666' : '#4cc9f0',
            formatBin: v => v >= 3000 ? '3000+' : String(v),
        },
        {
            key: 'seg_duration_ms', title: 'Segment Duration (ms)',
            barColor: (bin) => bin < 1000 ? '#ff9800' : '#4cc9f0',
            formatBin: v => (v/1000).toFixed(1) + 's',
            showAllLabels: true,
        },
        {
            key: 'words_per_seg', title: 'Words Per Segment',
            barColor: (bin) => bin === 1 ? '#f44336' : '#4cc9f0',
            formatBin: v => String(v),
            showAllLabels: true,
        },
        {
            key: 'segs_per_verse', title: 'Segments Per Verse',
            barColor: () => '#4cc9f0',
            formatBin: v => v >= 8 ? '8+' : String(v),
        },
        {
            key: 'confidence', title: 'Confidence (%)',
            barColor: (bin) => bin < 60 ? '#f44336' : bin < 80 ? '#ff9800' : '#4caf50',
            formatBin: v => v >= 100 ? '100' : String(v),
        },
    ];

    segStatsCharts.innerHTML = '';
    for (const cfg of charts) {
        const dist = data.distributions[cfg.key];
        if (!dist) continue;

        const wrap = document.createElement('div');
        wrap.className = 'seg-stats-chart-wrap';

        const header = document.createElement('div');
        header.className = 'seg-stats-chart-header';

        const h4 = document.createElement('h4');
        h4.textContent = cfg.title;
        header.appendChild(h4);

        const btnGroup = document.createElement('span');
        btnGroup.className = 'seg-stats-chart-btns';

        const fsBtn = document.createElement('button');
        fsBtn.className = 'seg-stats-chart-btn';
        fsBtn.title = 'Full screen';
        fsBtn.textContent = '\u26F6';

        const saveBtn = document.createElement('button');
        saveBtn.className = 'seg-stats-chart-btn';
        saveBtn.title = 'Save PNG';
        saveBtn.textContent = '\u2B73';

        btnGroup.appendChild(fsBtn);
        btnGroup.appendChild(saveBtn);
        header.appendChild(btnGroup);
        wrap.appendChild(header);

        const canvasWrap = document.createElement('div');
        canvasWrap.style.position = 'relative';
        canvasWrap.style.width = '100%';
        canvasWrap.style.height = '160px';
        const canvas = document.createElement('canvas');
        canvasWrap.appendChild(canvas);
        wrap.appendChild(canvasWrap);

        segStatsCharts.appendChild(wrap);
        drawBarChart(canvas, dist, cfg);

        // Fullscreen
        fsBtn.addEventListener('click', () => _openChartFullscreen(dist, cfg));

        // Save
        saveBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
    }
}

function _openChartFullscreen(dist, cfg) {
    let overlay = document.getElementById('seg-stats-fullscreen');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'seg-stats-fullscreen';
        overlay.innerHTML = '<div class="seg-stats-fs-inner"><div class="seg-stats-fs-bar">' +
            '<span class="seg-stats-fs-title"></span>' +
            '<button class="seg-stats-chart-btn seg-stats-fs-save" title="Save PNG">\u2B73</button>' +
            '<button class="seg-stats-chart-btn seg-stats-fs-close" title="Close">\u2715</button>' +
            '</div><div style="flex:1;min-height:0;position:relative"><canvas></canvas></div></div>';
        document.body.appendChild(overlay);
        overlay.querySelector('.seg-stats-fs-close').addEventListener('click', () => {
            overlay.style.display = 'none';
        });
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) overlay.style.display = 'none';
        });
    }

    overlay.style.display = 'flex';
    overlay.querySelector('.seg-stats-fs-title').textContent = cfg.title;

    const canvas = overlay.querySelector('canvas');

    // Destroy any previous Chart.js instance
    if (canvas._chartInstance) {
        canvas._chartInstance.destroy();
        canvas._chartInstance = null;
    }

    requestAnimationFrame(() => {
        drawBarChart(canvas, dist, cfg);
    });

    // Re-bind save button for this chart
    const saveBtn = overlay.querySelector('.seg-stats-fs-save');
    const newBtn = saveBtn.cloneNode(true);
    saveBtn.parentNode.replaceChild(newBtn, saveBtn);
    newBtn.addEventListener('click', () => _saveChart(canvas, cfg.key));
}

function _saveChart(canvas, key) {
    const reciter = segReciterSelect.value;
    if (!reciter) return;

    canvas.toBlob((blob) => {
        if (!blob) return;
        const fd = new FormData();
        fd.append('name', key);
        fd.append('image', blob, key + '.png');
        fetch(`/api/seg/stats/${encodeURIComponent(reciter)}/save-chart`, {
            method: 'POST', body: fd,
        }).then(r => r.json()).then(data => {
            if (data.ok) {
                const tip = document.createElement('span');
                tip.className = 'seg-stats-saved-tip';
                tip.textContent = 'Saved';
                document.body.appendChild(tip);
                setTimeout(() => tip.remove(), 1200);
            }
        });
    }, 'image/png');
}

function _findBinIndex(bins, value) {
    // Find fractional index where value falls within bin range
    if (bins.length < 2) return 0;
    const binStep = bins[1] - bins[0];
    const frac = (value - bins[0]) / binStep;
    return Math.max(-0.5, Math.min(bins.length - 0.5, frac));
}


// ---------------------------------------------------------------------------
// Edit History Panel
// ---------------------------------------------------------------------------

// IDs of elements to hide/show when toggling history view
const _SEG_NORMAL_IDS = ['seg-stats-panel', 'seg-validation-global', 'seg-validation',
    'seg-filter-bar', 'seg-list'];

function showHistoryView() {
    // Hide normal view elements, saving their previous hidden state
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByHistory = el.hidden ? '1' : ''; el.hidden = true; }
    }
    // Hide controls + shortcuts (no id, query by class)
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { controls.dataset.hiddenByHistory = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByHistory = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }

    segHistoryView.hidden = false;
    // Observe all waveform canvases + draw arrows
    const observer = _ensureWaveformObserver();
    segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
}

function hideHistoryView() {
    stopErrorCardAudio();
    segHistoryView.hidden = true;
    // Restore normal view elements
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByHistory !== '1') el.hidden = false; delete el.dataset.hiddenByHistory; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByHistory !== '1') controls.hidden = false; delete controls.dataset.hiddenByHistory; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByHistory !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByHistory; }
}

function renderEditHistoryPanel(data) {
    if (!data || !data.batches || data.batches.length === 0) {
        segHistoryBtn.hidden = true;
        return;
    }
    segHistoryBtn.hidden = false;

    if (data.summary) renderHistorySummaryStats(data.summary);
    renderHistoryBatches(data.batches);
}

function renderHistorySummaryStats(summary) {
    segHistoryStats.innerHTML = '';
    if (!summary) return;

    // Stat cards row
    const cardsRow = document.createElement('div');
    cardsRow.className = 'seg-history-stat-cards';
    const stats = [
        { value: summary.total_operations, label: 'Operations' },
        { value: summary.total_batches, label: 'Saves' },
        { value: summary.chapters_edited, label: 'Chapters' },
    ];
    for (const s of stats) {
        const card = document.createElement('div');
        card.className = 'seg-history-stat-card';
        card.innerHTML = `<div class="seg-history-stat-value">${s.value}</div>`
            + `<div class="seg-history-stat-label">${s.label}</div>`;
        cardsRow.appendChild(card);
    }
    segHistoryStats.appendChild(cardsRow);

    // Op type pills
    if (summary.op_counts && Object.keys(summary.op_counts).length > 0) {
        const pills = document.createElement('div');
        pills.className = 'seg-history-op-pills';
        const sorted = Object.entries(summary.op_counts).sort((a, b) => b[1] - a[1]);
        for (const [opType, count] of sorted) {
            const pill = document.createElement('span');
            pill.className = 'seg-history-op-pill';
            pill.innerHTML = `${EDIT_OP_LABELS[opType] || opType} <span class="pill-count">${count}</span>`;
            pills.appendChild(pill);
        }
        segHistoryStats.appendChild(pills);
    }

    // Fix kind breakdown
    const fk = summary.fix_kind_counts || {};
    const parts = [];
    if (fk.manual) parts.push(`${fk.manual} manual`);
    if (fk.auto_fix) parts.push(`${fk.auto_fix} auto-fix`);
    if (fk.ignore) parts.push(`${fk.ignore} ignored`);
    if (fk.audit) parts.push(`${fk.audit} audit`);
    if (parts.length > 0) {
        const fkDiv = document.createElement('div');
        fkDiv.className = 'seg-history-fix-kinds';
        fkDiv.textContent = `Fix breakdown: ${parts.join(', ')}`;
        segHistoryStats.appendChild(fkDiv);
    }
}

function renderHistoryBatches(batches) {
    segHistoryBatches.innerHTML = '';

    // Reverse: most recent first
    const reversed = [...batches].reverse();

    for (const batch of reversed) {
        const wrapper = document.createElement('div');
        wrapper.className = 'seg-history-batch' + (batch.is_revert ? ' is-revert' : '');

        // Header
        const header = document.createElement('div');
        header.className = 'seg-history-batch-header';

        const time = document.createElement('span');
        time.className = 'seg-history-batch-time';
        time.textContent = _formatHistDate(batch.saved_at_utc);
        header.appendChild(time);

        // Multi-chapter auto-fix batch (e.g. remove_sadaqa across many surahs)
        const isMultiChapter = batch.chapter == null && Array.isArray(batch.chapters);

        if (batch.chapter != null) {
            const ch = document.createElement('span');
            ch.className = 'seg-history-batch-chapter';
            ch.textContent = surahOptionText(batch.chapter);
            header.appendChild(ch);
        }

        const opsCount = document.createElement('span');
        opsCount.className = 'seg-history-batch-ops-count';
        const n = (batch.operations || []).length;
        if (isMultiChapter) {
            // Compact: "Remove Sadaqa x42" instead of "42 ops"
            const opType = batch.operations[0]?.op_type;
            const label = EDIT_OP_LABELS[opType] || opType;
            opsCount.textContent = `${label} x${n}`;
        } else {
            opsCount.textContent = n === 0 ? 'revert' : `${n} op${n !== 1 ? 's' : ''}`;
        }
        header.appendChild(opsCount);

        if (isMultiChapter) {
            const fk = document.createElement('span');
            fk.className = 'seg-history-op-fix-kind';
            fk.textContent = 'auto_fix';
            header.appendChild(fk);
        }

        if (batch.is_revert) {
            const badge = document.createElement('span');
            badge.className = 'seg-history-batch-revert-badge';
            badge.textContent = 'Reverted';
            header.appendChild(badge);
        }

        // Validation delta badges
        _appendValDeltas(header, batch.validation_summary_before, batch.validation_summary_after);

        wrapper.appendChild(header);

        // Body with operations (always visible)
        if (batch.operations && batch.operations.length > 0) {
            const body = document.createElement('div');
            body.className = 'seg-history-batch-body';
            if (isMultiChapter) {
                // Compact chapter list instead of individual op cards
                const chList = document.createElement('div');
                chList.className = 'seg-history-chapter-list';
                chList.textContent = 'Chapters: ' + batch.chapters
                    .map(c => surahOptionText(c)).join(', ');
                body.appendChild(chList);
            } else {
                for (const op of batch.operations) {
                    body.appendChild(renderHistoryOp(op, batch.chapter));
                }
            }
            wrapper.appendChild(body);
        }

        segHistoryBatches.appendChild(wrapper);
    }
}

function renderHistoryOp(op, chapter) {
    const wrap = document.createElement('div');
    wrap.className = 'seg-history-op';

    // Label row
    const label = document.createElement('div');
    label.className = 'seg-history-op-label';
    const typeBadge = document.createElement('span');
    typeBadge.className = 'seg-history-op-type-badge';
    typeBadge.textContent = EDIT_OP_LABELS[op.op_type] || op.op_type;
    label.appendChild(typeBadge);
    if (op.fix_kind && op.fix_kind !== 'manual') {
        const fk = document.createElement('span');
        fk.className = 'seg-history-op-fix-kind';
        fk.textContent = op.fix_kind;
        label.appendChild(fk);
    }
    wrap.appendChild(label);

    // 3-column diff grid
    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';

    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';

    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    // SVG placeholder — drawn after DOM insertion
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('height', '1');  // resized by drawHistoryArrows
    arrowCol.appendChild(svg);

    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';

    const before = op.targets_before || [];
    const after = op.targets_after || [];

    // Render before cards
    const beforeCards = [];
    for (const snap of before) {
        const pseudoSeg = _snapToSeg(snap, chapter);
        const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true });
        beforeCol.appendChild(card);
        beforeCards.push(card);
    }

    // Render after cards (or empty placeholder for delete)
    const afterCards = [];
    if (after.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = '(deleted)';
        afterCol.appendChild(empty);
    } else {
        for (const snap of after) {
            const pseudoSeg = _snapToSeg(snap, chapter);
            const card = renderSegCard(pseudoSeg, { readOnly: true, showChapter: true, showPlayBtn: true });
            afterCol.appendChild(card);
            afterCards.push(card);
        }
    }

    // Change highlighting for 1→1 ops
    if (before.length === 1 && after.length === 1) {
        _highlightChanges(before[0], after[0], beforeCards[0], afterCards[0]);
    }

    diff.append(beforeCol, arrowCol, afterCol);
    wrap.appendChild(diff);
    return wrap;
}

function _snapToSeg(snap, chapter) {
    return {
        index: snap.index_at_save,
        chapter: chapter,
        audio_url: snap.audio_url || '',
        time_start: snap.time_start,
        time_end: snap.time_end,
        matched_ref: snap.matched_ref || '',
        matched_text: snap.matched_text || '',
        confidence: snap.confidence ?? 0,
    };
}

function _highlightChanges(beforeSnap, afterSnap, beforeCard, afterCard) {
    // Compare fields and add .seg-history-changed to after card elements
    if (beforeSnap.matched_ref !== afterSnap.matched_ref) {
        const el = afterCard.querySelector('.seg-text-ref');
        if (el) el.classList.add('seg-history-changed');
    }
    if (beforeSnap.time_start !== afterSnap.time_start || beforeSnap.time_end !== afterSnap.time_end) {
        const el = afterCard.querySelector('.seg-text-time');
        if (el) el.classList.add('seg-history-changed');
    }
    if (beforeSnap.confidence !== afterSnap.confidence) {
        const el = afterCard.querySelector('.seg-text-conf');
        if (el) el.classList.add('seg-history-changed');
    }
    if (beforeSnap.matched_text !== afterSnap.matched_text) {
        const el = afterCard.querySelector('.seg-text-body');
        if (el) el.classList.add('seg-history-changed');
    }
}

function _appendValDeltas(container, before, after) {
    if (!before || !after) return;
    const cats = ['failed', 'low_confidence', 'oversegmented', 'cross_verse', 'missing_words', 'audio_bleeding'];
    const shortLabels = {
        failed: 'fail', low_confidence: 'low conf', oversegmented: 'overseg',
        cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
    };
    for (const cat of cats) {
        const delta = (after[cat] || 0) - (before[cat] || 0);
        if (delta === 0) continue;
        const badge = document.createElement('span');
        badge.className = 'seg-history-val-delta ' + (delta < 0 ? 'improved' : 'regression');
        badge.textContent = `${shortLabels[cat]} ${delta > 0 ? '+' : ''}${delta}`;
        container.appendChild(badge);
    }
}

function _formatHistDate(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
            + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    } catch { return isoStr; }
}


// ---------------------------------------------------------------------------
// Edit History — SVG Arrows
// ---------------------------------------------------------------------------

function _ensureHistArrowDefs() {
    if (document.getElementById('hist-arrow-defs')) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('id', 'hist-arrow-defs');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.style.position = 'absolute';
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    const marker = document.createElementNS('http://www.w3.org/2000/svg', 'marker');
    marker.setAttribute('id', 'hist-arrow');
    marker.setAttribute('viewBox', '0 0 10 7');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '3.5');
    marker.setAttribute('markerWidth', '8');
    marker.setAttribute('markerHeight', '6');
    marker.setAttribute('orient', 'auto-start-reverse');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', '0 0, 10 3.5, 0 7');
    poly.setAttribute('fill', '#4cc9f0');
    marker.appendChild(poly);
    defs.appendChild(marker);
    svg.appendChild(defs);
    document.body.appendChild(svg);
}

function drawHistoryArrows(diffEl) {
    _ensureHistArrowDefs();
    const svg = diffEl.querySelector('.seg-history-arrows svg');
    if (!svg) return;

    const beforeCards = diffEl.querySelectorAll('.seg-history-before .seg-row');
    const afterCards = diffEl.querySelectorAll('.seg-history-after .seg-row');
    const afterEmpty = diffEl.querySelector('.seg-history-after .seg-history-empty');

    // Clear previous arrows
    svg.innerHTML = '';

    const arrowCol = diffEl.querySelector('.seg-history-arrows');
    const colRect = arrowCol.getBoundingClientRect();
    if (colRect.height < 1) return;  // not visible

    svg.setAttribute('height', colRect.height);
    svg.setAttribute('viewBox', `0 0 60 ${colRect.height}`);

    const midYs = (cards) => Array.from(cards).map(c => {
        const r = c.getBoundingClientRect();
        return r.top + r.height / 2 - colRect.top;
    });

    const bY = midYs(beforeCards);
    const aY = afterCards.length > 0 ? midYs(afterCards) : [];

    // Delete: arrow to X
    if (afterCards.length === 0 && afterEmpty) {
        const eRect = afterEmpty.getBoundingClientRect();
        const targetY = eRect.top + eRect.height / 2 - colRect.top;
        for (const sy of bY) {
            _drawArrowPath(svg, 4, sy, 56, targetY, true);
        }
        // X mark at target
        const xSize = 5;
        const xG = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        xG.setAttribute('stroke', '#f44336');
        xG.setAttribute('stroke-width', '2');
        const cx = 52, cy = targetY;
        const l1 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l1.setAttribute('x1', cx - xSize); l1.setAttribute('y1', cy - xSize);
        l1.setAttribute('x2', cx + xSize); l1.setAttribute('y2', cy + xSize);
        const l2 = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        l2.setAttribute('x1', cx - xSize); l2.setAttribute('y1', cy + xSize);
        l2.setAttribute('x2', cx + xSize); l2.setAttribute('y2', cy - xSize);
        xG.append(l1, l2);
        svg.appendChild(xG);
        return;
    }

    // 1→1: straight arrow
    if (bY.length === 1 && aY.length === 1) {
        _drawArrowPath(svg, 4, bY[0], 56, aY[0], false);
        return;
    }

    // 1→N (split): fan out
    if (bY.length === 1 && aY.length > 1) {
        for (const ty of aY) {
            _drawArrowPath(svg, 4, bY[0], 56, ty, false);
        }
        return;
    }

    // N→1 (merge): converge
    if (bY.length > 1 && aY.length === 1) {
        for (const sy of bY) {
            _drawArrowPath(svg, 4, sy, 56, aY[0], false);
        }
        return;
    }

    // N→M fallback: connect each pair by index
    const maxLen = Math.max(bY.length, aY.length);
    for (let i = 0; i < maxLen; i++) {
        const sy = bY[Math.min(i, bY.length - 1)];
        const ty = aY[Math.min(i, aY.length - 1)];
        _drawArrowPath(svg, 4, sy, 56, ty, false);
    }
}

function _drawArrowPath(svg, x1, y1, x2, y2, dashed) {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    // Use quadratic bezier for smooth curves when source/target differ in Y
    const midX = (x1 + x2) / 2;
    const d = Math.abs(y2 - y1) < 2
        ? `M ${x1} ${y1} L ${x2} ${y2}`
        : `M ${x1} ${y1} Q ${midX} ${y1}, ${midX} ${(y1 + y2) / 2} Q ${midX} ${y2}, ${x2} ${y2}`;
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#4cc9f0');
    path.setAttribute('stroke-width', '1.5');
    if (dashed) path.setAttribute('stroke-dasharray', '4,3');
    path.setAttribute('marker-end', 'url(#hist-arrow)');
    svg.appendChild(path);
}


function drawBarChart(canvas, dist, cfg) {
    const { bins, counts } = dist;
    const n = counts.length;
    if (n === 0) return;

    // Destroy previous instance
    if (canvas._chartInstance) {
        canvas._chartInstance.destroy();
        canvas._chartInstance = null;
    }

    const totalCount = counts.reduce((a, b) => a + b, 0);
    const labels = bins.map(b => cfg.formatBin ? cfg.formatBin(b) : String(b));
    const bgColors = bins.map((b, i) => cfg.barColor ? cfg.barColor(b, i, bins) : '#4cc9f0');
    const hoverColors = bgColors.map(c => {
        // Lighten each color for hover
        const r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
        return `rgb(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, b + 40)})`;
    });

    // Build annotation lines
    const annotations = {};

    if (cfg.refLine != null && bins.length >= 2) {
        annotations.refLine = {
            type: 'line', scaleID: 'x',
            value: _findBinIndex(bins, cfg.refLine),
            borderColor: '#f44336', borderWidth: 1.5, borderDash: [4, 3],
            label: {
                display: true, content: cfg.refLabel || '',
                position: 'start', color: '#f44336',
                font: { size: 9, family: 'monospace' },
                backgroundColor: 'rgba(15,15,35,0.7)',
            }
        };
    }

    if (dist.percentiles && bins.length >= 2) {
        const pCfg = {
            p25: { color: '#888', dash: [3, 3], label: 'P25' },
            p50: { color: '#e0e040', dash: [6, 3], label: 'Med' },
            p75: { color: '#888', dash: [3, 3], label: 'P75' },
        };
        for (const [key, val] of Object.entries(dist.percentiles)) {
            const pc = pCfg[key];
            if (!pc) continue;
            const fmtVal = cfg.formatBin ? cfg.formatBin(val) : String(val);
            annotations[key] = {
                type: 'line', scaleID: 'x',
                value: _findBinIndex(bins, val),
                borderColor: pc.color, borderWidth: 1, borderDash: pc.dash,
                label: {
                    display: true, content: `${pc.label} ${fmtVal}`,
                    position: 'start', color: pc.color,
                    font: { size: 8, family: 'monospace' },
                    backgroundColor: 'rgba(15,15,35,0.7)',
                }
            };
        }
    }

    const chart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: counts,
                backgroundColor: bgColors,
                hoverBackgroundColor: hoverColors,
                borderWidth: 0,
                borderSkipped: false,
                barPercentage: 0.92,
                categoryPercentage: 0.92,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 200 },
            layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#16213e',
                    borderColor: '#4cc9f0',
                    borderWidth: 1,
                    titleColor: '#4cc9f0',
                    bodyColor: '#e0e0e0',
                    footerColor: '#888',
                    titleFont: { family: 'monospace', size: 11 },
                    bodyFont: { family: 'monospace', size: 11 },
                    footerFont: { family: 'monospace', size: 10 },
                    padding: 6,
                    displayColors: false,
                    callbacks: {
                        title: (items) => items[0]?.label || '',
                        label: (item) => `Count: ${item.raw}`,
                        footer: (items) => {
                            const count = items[0]?.raw || 0;
                            return `${(count / totalCount * 100).toFixed(1)}%`;
                        },
                    },
                },
                annotation: { annotations },
            },
            scales: {
                x: {
                    grid: { color: '#2a2a4a', lineWidth: 0.5 },
                    ticks: {
                        color: '#888',
                        font: { family: 'monospace', size: 9 },
                        autoSkip: !cfg.showAllLabels,
                        maxRotation: 45,
                        minRotation: 0,
                    },
                    border: { color: '#2a2a4a' },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: '#1a1a3e', lineWidth: 0.5 },
                    ticks: {
                        color: '#888',
                        font: { family: 'monospace', size: 10 },
                    },
                    border: { color: '#2a2a4a' },
                },
            },
        },
    });

    canvas._chartInstance = chart;
    return chart;
}
