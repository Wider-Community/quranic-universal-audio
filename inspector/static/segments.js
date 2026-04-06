/**
 * Segments Tab — visualize VAD-aligned segment data from extract_segments.py.
 */

// State
let segData = null;          // { audio_url, summary, verse_word_counts, segments } — chapter-specific
let segAllData = null;       // { segments, audio_by_chapter, verse_word_counts } — reciter-level
let segActiveFilters = [];   // [{ field, op, value }, ...]
let segAnimId = null;        // animation frame ID for playback
let segCurrentIdx = -1;      // currently playing segment index
let segDisplayedSegments = null; // segments currently shown (may be filtered)
let segDirtyMap = new Map();     // Map<chapter, {indices: Set, structural: boolean}> — all unsaved edits
let segEditMode = null;          // null | 'trim' | 'split'
let segEditIndex = -1;           // index of segment being edited
// (merge is now button-driven, no merge selection state needed)
let _segPrefetchCache = {};      // url → Promise<void> for prefetched audio
let _segContinuousPlay = false;  // true while continuous playback is active across audio files
let _segAutoPlayEnabled = true;  // user preference: auto-advance through consecutive segments
let _segPlayEndMs = 0;           // time_end (ms) of the currently playing displayed segment
let segValidation = null;        // cached validation data for current reciter
let segAllReciters = [];         // full list from /api/seg/reciters
let segStatsData = null;         // cached stats data for current reciter
let _segFilterDebounceTimer = null; // debounce timer for filter value input
let _activeAudioSource = null;      // 'main' | 'error' | null — which audio is active
let _segIndexMap = null;         // Map<index, segment> for O(1) lookups
let _waveformObserver = null;    // IntersectionObserver for lazy waveform drawing
let _segSavedFilterView = null;  // { filters, chapter, verse, scrollTop } — saved when "Go To" from filter results
let _segSavedPreviewState = null; // { scrollTop } — saved when entering save preview, restored on cancel/after save
let segPeaksByAudio = null;      // {url: {duration_ms, peaks}} from server — instant waveforms
let _peaksPollTimer = null;      // setTimeout handle for peaks polling
let _cardRenderRafId = null;     // rAF handle for chunked card rendering
let _accordionOpCtx = null;      // { wrapper, direction? } — set when split/merge from accordion with context shown
let _splitChainWrapper = null;  // accordion wrapper to use for second-half ref-edit chain after split

// ---------------------------------------------------------------------------
// Edit history — operation log (sent with save payload)
// ---------------------------------------------------------------------------
let segOpLog = new Map();   // Map<chapter, Array<operation>>
let _pendingOp = null;      // stashed op for multi-step edits (trim, split, ref edit)
let _splitChainUid = null;  // after split ref-edit on first half, chain to second half's UID

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
    const snap = {
        segment_uid: seg.segment_uid || null,
        index_at_save: seg.index,
        audio_url: seg.audio_url || null,
        time_start: seg.time_start,
        time_end: seg.time_end,
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        display_text: seg.display_text || '',
        confidence: seg.confidence ?? 0,
    };
    if (seg.has_repeated_words) snap.has_repeated_words = true;
    if (seg.wrap_word_ranges) snap.wrap_word_ranges = seg.wrap_word_ranges;
    if (seg.phonemes_asr) snap.phonemes_asr = seg.phonemes_asr;
    return snap;
}

/**
 * Classify a segment snapshot into validation issue categories.
 * Returns an array of category strings (e.g. ['low_confidence', 'cross_verse']).
 */
function _classifySnapIssues(snap) {
    const issues = [];
    if (!snap || !snap.matched_ref) { if (snap) issues.push('failed'); return issues; }
    if (snap.confidence < 0.80) issues.push('low_confidence');
    if (snap.wrap_word_ranges || snap.has_repeated_words) issues.push('repetitions');
    // Cross-verse: start ayah != end ayah in canonical ref (surah:ayah:word-surah:ayah:word)
    const parts = snap.matched_ref.split('-');
    if (parts.length === 2) {
        const sp = parts[0].split(':'), ep = parts[1].split(':');
        if (sp.length >= 2 && ep.length >= 2) {
            const sAyah = parseInt(sp[1]), eAyah = parseInt(ep[1]);
            if (sAyah !== eAyah) issues.push('cross_verse');
        }
    }
    return issues;
}

/**
 * Derive per-op-group issue delta from snapshot data.
 * Uses first op's targets_before as initial state, and last-write-per-UID as final state
 * (same logic as renderHistoryGroupedOp) to avoid intermediate snapshot pollution.
 */
function _deriveOpIssueDelta(group) {
    if (!group || group.length === 0) return { resolved: [], introduced: [] };
    const primary = group[0];

    // Initial state: only the group's entry snapshots
    const beforeIssues = new Set();
    for (const snap of (primary.targets_before || []))
        _classifySnapIssues(snap).forEach(i => beforeIssues.add(i));

    // Final state: last write per UID (mirrors renderHistoryGroupedOp logic)
    const finalSnaps = new Map();
    let hasAnyAfterUid = false;
    for (const op of group) {
        for (const snap of (op.targets_after || [])) {
            if (snap.segment_uid) { finalSnaps.set(snap.segment_uid, snap); hasAnyAfterUid = true; }
        }
    }

    // Fallback for old records without segment_uid: use last op's targets_after directly
    const afterSnaps = hasAnyAfterUid
        ? [...finalSnaps.values()]
        : (group[group.length - 1].targets_after || []);

    const afterIssues = new Set();
    for (const snap of afterSnaps)
        _classifySnapIssues(snap).forEach(i => afterIssues.add(i));

    return {
        resolved:   [...beforeIssues].filter(i => !afterIssues.has(i)),
        introduced: [...afterIssues].filter(i => !beforeIssues.has(i)),
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
const segAutoPlayBtn = document.getElementById('seg-autoplay-btn');
const segSpeedSelect = document.getElementById('seg-speed-select');
const segSaveBtn = document.getElementById('seg-save-btn');
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
let _segDataStale = false;  // set true after undo-batch; triggers reload on hideHistoryView
const segHistoryView    = document.getElementById('seg-history-view');
const segHistoryBtn     = document.getElementById('seg-history-btn');
const segHistoryBackBtn = document.getElementById('seg-history-back-btn');
const segHistoryStats   = document.getElementById('seg-history-stats');
const segHistoryBatches = document.getElementById('seg-history-batches');

// History filter & sort state
let _histFilterOpTypes = new Set();
let _histFilterErrCats = new Set();
let _histSortMode = 'time'; // 'time' | 'quran'

// Split chain state — rebuilt on each history load
let _splitChains    = null;   // Map<rootOpId, chainData>
let _chainedOpIds   = null;   // Set<opId> for ops absorbed into chains
let _segSavedChains = null;   // stashed history-only chains while save preview is open
const segHistoryFilters      = document.getElementById('seg-history-filters');
const segHistoryFilterOps    = document.getElementById('seg-history-filter-ops');
const segHistoryFilterCats   = document.getElementById('seg-history-filter-cats');
const segHistoryFilterClear  = document.getElementById('seg-history-filter-clear');
const segHistorySortTime     = document.getElementById('seg-history-sort-time');
const segHistorySortQuran    = document.getElementById('seg-history-sort-quran');

// Save confirmation preview
const segSavePreview        = document.getElementById('seg-save-preview');
const segSavePreviewCancel  = document.getElementById('seg-save-preview-cancel');
const segSavePreviewConfirm = document.getElementById('seg-save-preview-confirm');
const segSavePreviewStats   = document.getElementById('seg-save-preview-stats');
const segSavePreviewBatches = document.getElementById('seg-save-preview-batches');

const EDIT_OP_LABELS = {
    trim_segment: 'Boundary adjustment', split_segment: 'Split',
    merge_segments: 'Merge', delete_segment: 'Deletion',
    edit_reference: 'Reference edit', confirm_reference: 'Reference confirmation',
    auto_fix_missing_word: 'Auto-fix missing word', ignore_issue: 'Ignored issue',
    waqf_sakt: 'Waqf sakt merge', remove_sadaqa: 'Remove Sadaqa',
};
const ERROR_CAT_LABELS = {
    failed: 'Failed', low_confidence: 'Low confidence',
    boundary_adj: 'Boundary adj.',
    cross_verse: 'Cross-verse', missing_words: 'Missing words',
    audio_bleeding: 'Audio bleeding',
    repetitions: 'Repetitions',
    muqattaat: 'Muqattaat letters',
    qalqala: 'Qalqala',
};
// Server-provided canonical category list (populated from /api/seg/config)
let _validationCategories = null;
// Default threshold % for low-confidence slider (overridden from config)
let _lcDefaultThreshold = 80;

// SearchableSelect instance for segments chapter dropdown
let segChapterSS = null;

// Init
document.addEventListener('DOMContentLoaded', async () => {
    // Restore persistent settings before wiring up handlers
    _segAutoPlayEnabled = localStorage.getItem('insp_seg_autoplay') !== 'false';
    segAutoPlayBtn.className = 'btn ' + (_segAutoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');
    const _savedSegSpeed = localStorage.getItem('insp_seg_speed');
    if (_savedSegSpeed) segSpeedSelect.value = _savedSegSpeed;

    segReciterSelect.addEventListener('change', onSegReciterChange);
    segChapterSelect.addEventListener('change', onSegChapterChange);
    segVerseSelect.addEventListener('change', applyFiltersAndRender);
    segPlayBtn.addEventListener('click', onSegPlayClick);
    segAutoPlayBtn.addEventListener('click', () => {
        _segAutoPlayEnabled = !_segAutoPlayEnabled;
        _segContinuousPlay = _segAutoPlayEnabled;
        segAutoPlayBtn.className = 'btn ' + (_segAutoPlayEnabled ? 'seg-autoplay-on' : 'seg-autoplay-off');
        localStorage.setItem('insp_seg_autoplay', _segAutoPlayEnabled);
    });
    segSaveBtn.addEventListener('click', onSegSaveClick);
    segSpeedSelect.addEventListener('change', () => {
        const rate = parseFloat(segSpeedSelect.value);
        segAudioEl.playbackRate = rate;
        if (valCardAudio) valCardAudio.playbackRate = rate;
        localStorage.setItem('insp_seg_speed', segSpeedSelect.value);
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
    segHistoryFilterClear.addEventListener('click', clearHistoryFilters);
    segHistorySortTime.addEventListener('click', () => setHistorySort('time'));
    segHistorySortQuran.addEventListener('click', () => setHistorySort('quran'));
    segSavePreviewCancel.addEventListener('click', hideSavePreview);
    segSavePreviewConfirm.addEventListener('click', confirmSaveFromPreview);

    // Delegated event listeners for segment card actions — shared across main, error, history & preview sections
    [segListEl, segValidationEl, segValidationGlobalEl, segHistoryView, segSavePreview].forEach(el => {
        el.addEventListener('click', handleSegRowClick);
        el.addEventListener('mousedown', _handleSegCanvasMousedown);
    });

    // Load display config
    try {
        const cfgResp = await fetch('/api/seg/config');
        if (cfgResp.ok) {
            const cfg = await cfgResp.json();
            const root = document.documentElement.style;
            if (cfg.seg_font_size) root.setProperty('--seg-font-size', cfg.seg_font_size);
            if (cfg.seg_word_spacing) root.setProperty('--seg-word-spacing', cfg.seg_word_spacing);
            if (cfg.trim_pad_left != null) TRIM_PAD_LEFT = cfg.trim_pad_left;
            if (cfg.trim_pad_right != null) TRIM_PAD_RIGHT = cfg.trim_pad_right;
            if (cfg.trim_dim_alpha != null) TRIM_DIM_ALPHA = cfg.trim_dim_alpha;
            if (cfg.show_boundary_phonemes != null) SHOW_BOUNDARY_PHONEMES = cfg.show_boundary_phonemes;
            if (cfg.validation_categories) _validationCategories = cfg.validation_categories;
            if (cfg.low_conf_default_threshold != null) _lcDefaultThreshold = cfg.low_conf_default_threshold;
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

        // Restore saved reciter
        const _savedSegReciter = localStorage.getItem('insp_seg_reciter');
        if (_savedSegReciter) {
            segReciterSelect.value = _savedSegReciter;
            if (segReciterSelect.value === _savedSegReciter) {
                onSegReciterChange();
            }
        }
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
    if (reciter) localStorage.setItem('insp_seg_reciter', reciter);
    segChapterSelect.innerHTML = '<option value="">-- select --</option>';
    if (segChapterSS) segChapterSS.refresh();
    segVerseSelect.innerHTML = '<option value="">All</option>';
    clearSegDisplay();
    _segDataStale = false;
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
    _splitChains = null;
    _chainedOpIds = null;
    _segSavedChains = null;
    if (!reciter) return;

    try {
        const resp = await fetch(`/api/seg/chapters/${reciter}`);
        if (segReciterSelect.value !== reciter) return; // reciter changed while loading
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

    if (segReciterSelect.value !== reciter) return; // reciter changed while loading chapters

    // Fetch validation, stats, all segments, and edit history in parallel
    const [valResult, statsResult, allResult, histResult] = await Promise.allSettled([
        fetch(`/api/seg/validate/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/stats/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/all/${reciter}`).then(r => r.json()),
        fetch(`/api/seg/edit-history/${reciter}`).then(r => r.ok ? r.json() : null),
    ]);

    if (segReciterSelect.value !== reciter) return; // reciter changed during parallel fetches

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
        _rewriteAudioUrls();
        computeSilenceAfter();
        if (segFilterBarEl) segFilterBarEl.hidden = false;
        applyFiltersAndRender();
        // Preload peaks only for chapters with validation errors (on-demand for the rest)
        const errorChapters = _collectErrorChapters(segValidation);
        if (errorChapters.length > 0) _fetchPeaks(reciter, errorChapters);
        // Fetch cache status then show panel (fast — cached in memory on server)
        if (_isCurrentReciterBySurah()) _fetchCacheStatus(reciter);
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

    // Clear audio state
    segAudioEl.src = '';
    segPlayBtn.disabled = true;
    stopSegAnimation();
    _segPrefetchCache = {};

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
        // Stale response guard: reciter or chapter changed while fetching
        if (segReciterSelect.value !== reciter || segChapterSelect.value !== chapter) return;
        segData = await resp.json();
        if (segData.error) return;
        // Rewrite audio URL to use proxy (by_surah only)
        if (_isCurrentReciterBySurah() && segData.audio_url && !segData.audio_url.startsWith('/api/')) {
            segData.audio_url = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(segData.audio_url)}`;
        }

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

        // Fetch peaks for this chapter if not already loaded
        _fetchChapterPeaksIfNeeded(reciter, chNum);

        // Preload audio src so browser fetches metadata in the background
        // (eliminates delay on first play click)
        if (segData.audio_url) {
            segAudioEl.src = segData.audio_url;
            segAudioEl.preload = 'metadata';
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

const _ARABIC_DIGITS = ['٠','١','٢','٣','٤','٥','٦','٧','٨','٩'];
function _toArabicNumeral(n) {
    return String(n).split('').map(d => _ARABIC_DIGITS[+d]).join('');
}

/** Normalize a short ref to canonical surah:ayah:word-surah:ayah:word format. */
function _normalizeRef(ref) {
    if (!ref) return ref;
    const vwc = (segAllData || segData || {}).verse_word_counts;
    const parts = ref.split('-');
    if (parts.length === 2) {
        const s = parts[0].split(':'), e = parts[1].split(':');
        if (s.length === 3 && e.length === 3) return ref; // already canonical
        if (s.length === 2 && e.length === 2) {
            const n = vwc?.[`${e[0]}:${e[1]}`] || 1;
            return `${s[0]}:${s[1]}:1-${e[0]}:${e[1]}:${n}`;
        }
    } else if (parts.length === 1) {
        const c = ref.split(':');
        if (c.length === 2) {
            const n = vwc?.[`${c[0]}:${c[1]}`] || 1;
            return `${c[0]}:${c[1]}:1-${c[0]}:${c[1]}:${n}`;
        }
        if (c.length === 3) return `${ref}-${ref}`;
    }
    return ref;
}

/** Insert verse end markers (۝N) at verse boundaries within segment text. */
function _addVerseMarkers(text, ref) {
    if (!text || !ref) return text;
    const vwc = (segAllData || segData || {}).verse_word_counts;
    const p = parseSegRef(_normalizeRef(ref));
    if (!p || !vwc) return text;

    const words = text.split(/\s+/).filter(Boolean);
    const out = [];
    let ay = p.ayah_from, w = p.word_from;

    for (let i = 0; i < words.length; i++) {
        out.push(words[i]);
        // Skip Quranic annotation marks (ۜ ۙ ۚ etc., U+06D0–U+06EF) that appear
        // space-separated in QPC text — they are not real words and must not advance w.
        if (!/[\u0600-\u066F]/.test(words[i])) continue;
        const total = vwc[`${p.surah}:${ay}`] || 0;
        if (total > 0 && w >= total) {
            out.push('\u06DD' + _toArabicNumeral(ay));
            ay++;
            w = 1;
        } else {
            w++;
        }
    }
    return out.join(' ');
}

function segDerivedProps(seg) {
    if (seg._derived) return seg._derived;
    const duration_s     = (seg.time_end - seg.time_start) / 1000;
    const num_words      = countSegWords(seg.matched_ref);
    const p              = parseSegRef(seg.matched_ref);
    const num_verses     = p ? p.ayah_to - p.ayah_from + 1 : 0;
    const confidence_pct = (seg.confidence || 0) * 100;
    const silence_after_ms = seg.silence_after_ms;
    seg._derived = { duration_s, num_words, num_verses, confidence_pct, silence_after_ms };
    return seg._derived;
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

    // 3. Active filter conditions (AND logic; skip conditions with null value)
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
    const updated = segData.segments.map(s => { s.chapter = chapter; return s; });
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

            // For split-chain after-cards: draw full parent waveform instead of just the leaf slice
            const wfSeg = canvas._splitHL
                ? { ...seg, time_start: canvas._splitHL.wfStart, time_end: canvas._splitHL.wfEnd }
                : seg;

            // If this canvas is in active split/trim edit mode, draw the edit overlay
            // instead of the plain base waveform (which would wipe the split cursor).
            if (canvas._splitData) {
                canvas._splitBaseCache = null;
                drawSplitWaveform(canvas);
                _waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }
            if (canvas._trimWindow) {
                canvas._wfCache = null;
                drawTrimWaveform(canvas);
                _waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
                return;
            }

            // Draw from pre-computed peaks (no audio download needed)
            if (drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter)) {
                _drawSplitHighlight(canvas, wfSeg);
                _drawTrimHighlight(canvas, seg);
                _drawMergeHighlight(canvas, seg);
                _waveformObserver.unobserve(canvas);
                canvas.removeAttribute('data-needs-waveform');
            }
            // No peaks yet — leave canvas as-is; _fetchPeaks polling will
            // call _redrawPeaksWaveforms when they arrive.
        });
    }, { rootMargin: '200px' });
    return _waveformObserver;
}

function drawAllSegWaveforms() {
    if (!segDisplayedSegments) return;
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
    if (!chapters || chapters.length === 0) return;  // always require explicit chapters
    let url = `/api/seg/peaks/${reciter}?chapters=${chapters.join(',')}`;
    fetch(url).then(r => r.json()).then(data => {
        if (!segAllData || segReciterSelect.value !== reciter) return;
        if (!segPeaksByAudio) segPeaksByAudio = {};
        Object.assign(segPeaksByAudio, data.peaks || {});
        // Also key by proxy URL so rewritten audio URLs can find peaks
        if (_isCurrentReciterBySurah()) {
            for (const [origUrl, pe] of Object.entries(data.peaks || {})) {
                if (origUrl && !origUrl.startsWith('/api/')) {
                    segPeaksByAudio[`/api/seg/audio-proxy/${segReciterSelect.value}?url=${encodeURIComponent(origUrl)}`] = pe;
                }
            }
        }
        _redrawPeaksWaveforms();
        if (!data.complete) {
            _peaksPollTimer = setTimeout(() => _fetchPeaks(reciter, chapters), 3000);
        }
    }).catch(() => {});
}

/** Fetch peaks for a single chapter if the audio URL's peaks aren't already loaded. */
function _fetchChapterPeaksIfNeeded(reciter, chapter) {
    if (!segAllData) return;
    const audioUrl = segAllData.audio_by_chapter?.[String(chapter)] || '';
    if (!audioUrl) return;
    // Check both original URL and proxy URL
    if (segPeaksByAudio?.[audioUrl]) return;
    const proxyUrl = `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(audioUrl)}`;
    if (segPeaksByAudio?.[proxyUrl]) return;
    _fetchPeaks(reciter, [chapter]);
}

/** Extract unique chapter numbers from all validation error categories. */
function _collectErrorChapters(validation) {
    if (!validation) return [];
    const chapters = new Set();
    const cats = ['errors', 'missing_verses', 'missing_words', 'failed',
                  'low_confidence', 'boundary_adj',
                  'cross_verse', 'audio_bleeding', 'repetitions'];
    for (const cat of cats) {
        const items = validation[cat];
        if (items) items.forEach(i => { if (i.chapter) chapters.add(i.chapter); });
    }
    return [...chapters].sort((a, b) => a - b);
}

// ---------------------------------------------------------------------------
// Audio cache — proxy CDN audio through server for local caching
// ---------------------------------------------------------------------------

let _audioCachePollTimer = null;

function _isCurrentReciterBySurah() {
    const reciter = segReciterSelect.value;
    const info = segAllReciters.find(r => r.slug === reciter);
    return info && info.audio_source && info.audio_source.startsWith('by_surah');
}

/** Compare a segment's audio_url (may be relative) against segAudioEl.src (always absolute). */
function _audioSrcMatch(segUrl, elSrc) {
    if (!segUrl || !elSrc) return false;
    if (segUrl === elSrc) return true;
    return elSrc.endsWith(segUrl);
}

/** Rewrite all audio URLs in segAllData to go through the server proxy (by_surah only). */
function _rewriteAudioUrls() {
    if (!segAllData || !_isCurrentReciterBySurah()) return;
    const reciter = segReciterSelect.value;
    const rewrite = url => url && !url.startsWith('/api/') ? `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(url)}` : url;
    if (segAllData.audio_by_chapter) {
        for (const ch of Object.keys(segAllData.audio_by_chapter)) {
            segAllData.audio_by_chapter[ch] = rewrite(segAllData.audio_by_chapter[ch]);
        }
    }
    if (segAllData.segments) {
        segAllData.segments.forEach(s => { if (s.audio_url) s.audio_url = rewrite(s.audio_url); });
    }
}

function _formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

function _updateCacheStatusUI(data) {
    const statusEl = document.getElementById('seg-cache-status');
    const progressEl = document.getElementById('seg-cache-progress');
    const progressFill = document.getElementById('seg-cache-progress-fill');
    const progressText = document.getElementById('seg-cache-progress-text');
    const prepBtn = document.getElementById('seg-prepare-btn');
    const delBtn = document.getElementById('seg-delete-cache-btn');
    if (!statusEl) return;
    if (!data || data.error) {
        statusEl.textContent = '';
        if (progressEl) progressEl.hidden = true;
        return;
    }

    const allCached = data.cached_count >= data.total;
    if (prepBtn) prepBtn.hidden = allCached;
    if (delBtn) delBtn.hidden = data.cached_count === 0;

    if (data.downloading && data.download_progress) {
        const dp = data.download_progress;
        const pct = dp.total > 0 ? Math.round(dp.downloaded / dp.total * 100) : 0;
        if (progressEl) progressEl.hidden = false;
        if (progressFill) progressFill.style.width = pct + '%';
        if (progressText) progressText.textContent = `Downloading ${dp.downloaded} / ${dp.total} chapters (${_formatBytes(data.cached_bytes)})`;
        statusEl.textContent = '';
        if (prepBtn) prepBtn.hidden = true;
    } else {
        if (progressEl) progressEl.hidden = true;
        if (allCached) {
            statusEl.textContent = `All cached (${_formatBytes(data.cached_bytes)})`;
        } else {
            statusEl.textContent = 'Download audio for faster playback while editing';
        }
    }
}

async function _fetchCacheStatus(reciter) {
    try {
        const resp = await fetch(`/api/seg/audio-cache-status/${reciter}`);
        const data = await resp.json();
        const bar = document.getElementById('seg-cache-bar');
        if (bar) bar.hidden = false;
        _updateCacheStatusUI(data);
        return data;
    } catch { return null; }
}

async function _prepareAudio(reciter) {
    const prepBtn = document.getElementById('seg-prepare-btn');
    if (prepBtn) { prepBtn.disabled = true; prepBtn.hidden = true; }
    try {
        await fetch(`/api/seg/prepare-audio/${reciter}`, { method: 'POST' });
    } catch { /* poll will handle */ }
    // Poll progress
    if (_audioCachePollTimer) clearInterval(_audioCachePollTimer);
    _audioCachePollTimer = setInterval(async () => {
        if (segReciterSelect.value !== reciter) {
            clearInterval(_audioCachePollTimer); _audioCachePollTimer = null; return;
        }
        const data = await _fetchCacheStatus(reciter);
        if (data && (!data.downloading || data.cached_count >= data.total)) {
            clearInterval(_audioCachePollTimer); _audioCachePollTimer = null;
            if (prepBtn) { prepBtn.disabled = false; prepBtn.textContent = 'Download All Audio'; }
            _updateCacheStatusUI(data);
        }
    }, 2000);
}

async function _deleteAudioCache(reciter) {
    if (!confirm('Delete cached audio for this reciter?\nOnly delete once you are finished editing.')) return;
    const delBtn = document.getElementById('seg-delete-cache-btn');
    if (delBtn) { delBtn.disabled = true; delBtn.textContent = 'Deleting...'; }
    try {
        await fetch(`/api/seg/delete-audio-cache/${reciter}`, { method: 'DELETE' });
    } catch { /* ignore */ }
    if (delBtn) { delBtn.disabled = false; delBtn.textContent = 'Delete Cache'; }
    await _fetchCacheStatus(reciter);
}

function _redrawPeaksWaveforms() {
    const observer = _ensureWaveformObserver();
    const editCanvas = _getEditCanvas();
    [segListEl, segValidationEl, segValidationGlobalEl, segHistoryView].forEach(container => {
        if (!container) return;
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => {
            if (c === editCanvas) return; // handled separately below — don't re-observe
            // Unobserve then re-observe to force a fresh intersection check
            observer.unobserve(c);
            observer.observe(c);
        });
    });
    // Redraw split/trim canvas directly with fresh peaks (bypassing observer to avoid cursor wipe)
    if (editCanvas?._splitData) { editCanvas._splitBaseCache = null; drawSplitWaveform(editCanvas); }
    else if (editCanvas?._trimWindow) { editCanvas._wfCache = null; drawTrimWaveform(editCanvas); }
}


// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function clearSegDisplay() {
    if (_waveformObserver) { _waveformObserver.disconnect(); _waveformObserver = null; }
    _segIndexMap = null;
    segAllData = null;
    segActiveFilters = [];
    if (segFilterBarEl) { segFilterBarEl.hidden = true; segFilterRowsEl.innerHTML = ''; }
    const cacheBar = document.getElementById('seg-cache-bar');
    if (cacheBar) cacheBar.hidden = true;
    if (_audioCachePollTimer) { clearInterval(_audioCachePollTimer); _audioCachePollTimer = null; }
    if (segFilterCountEl) segFilterCountEl.textContent = '';
    if (segFilterClearBtn) segFilterClearBtn.hidden = true;
    if (segFilterStatusEl) segFilterStatusEl.textContent = '';
    segData = null;
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
    _splitChains = null;
    _chainedOpIds = null;
    _segSavedChains = null;
    segHistoryBtn.hidden = true;
    segHistoryView.hidden = true;
    segHistoryStats.innerHTML = '';
    segHistoryBatches.innerHTML = '';
    segSavePreview.hidden = true;
    segSavePreviewStats.innerHTML = '';
    segSavePreviewBatches.innerHTML = '';
    _segPrefetchCache = {};
    _segContinuousPlay = false;
    _segPlayEndMs = 0;
    segPeaksByAudio = null;
    if (_peaksPollTimer) { clearTimeout(_peaksPollTimer); _peaksPollTimer = null; }
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

// ---------------------------------------------------------------------------
// Canvas click-to-seek / drag-to-scrub
// ---------------------------------------------------------------------------

let _segScrubActive = false;

function _seekFromCanvasEvent(e, canvas, row) {
    const seg = resolveSegFromRow(row);
    if (!seg) return;

    const rect = canvas.getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    // For split-chain cards the canvas shows the parent waveform, so map
    // the click position to parent bounds, not the leaf's own bounds.
    const splitHL = canvas._splitHL;
    const tStart = splitHL ? splitHL.wfStart : seg.time_start;
    const tEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;
    const timeMs = tStart + progress * (tEnd - tStart);

    if (segListEl.contains(row)) {
        // Main section
        const idx = parseInt(row.dataset.segIndex);
        const chapter = parseInt(row.dataset.segChapter);
        if (idx === segCurrentIdx && !segAudioEl.paused) {
            segAudioEl.currentTime = timeMs / 1000;
        } else {
            playFromSegment(idx, chapter, timeMs);
        }
    } else {
        // Error / history / save / context cards
        const playBtn = row.querySelector('.seg-card-play-btn');
        if (!playBtn) return;
        if (valCardPlayingBtn === playBtn && valCardAudio && !valCardAudio.paused) {
            valCardAudio.currentTime = timeMs / 1000;
        } else {
            playErrorCardAudio(seg, playBtn, timeMs);
        }
    }
}

function _handleSegCanvasMousedown(e) {
    const canvas = e.target.closest('canvas');
    if (!canvas) return;
    const row = canvas.closest('.seg-row');
    if (!row || segEditMode) return;

    e.preventDefault();
    _segScrubActive = true;
    _seekFromCanvasEvent(e, canvas, row);

    function onMove(ev) {
        _seekFromCanvasEvent(ev, canvas, row);
    }
    function onUp() {
        _segScrubActive = false;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

function handleSegRowClick(e) {

    // Canvas click-to-seek (intercept before other handlers)
    const clickedCanvas = e.target.closest('canvas');
    if (clickedCanvas) {
        e.stopPropagation();
        const row = clickedCanvas.closest('.seg-row');
        if (row && !segEditMode) _seekFromCanvasEvent(e, clickedCanvas, row);
        return;
    }

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
    // Play button
    const playBtn = e.target.closest('.seg-card-play-btn');
    if (playBtn) {
        e.stopPropagation();
        const row = playBtn.closest('.seg-row');
        if (segListEl.contains(row)) {
            // Main section: toggle play/pause
            const idx = parseInt(row.dataset.segIndex);
            if (idx === segCurrentIdx && !segAudioEl.paused) {
                segAudioEl.pause();
            } else {
                playFromSegment(idx, parseInt(row.dataset.segChapter));
            }
        } else {
            // Accordion / history: use valCardAudio
            const seg = resolveSegFromRow(row);
            if (seg) playErrorCardAudio(seg, playBtn);
        }
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
        if (!seg || !row) return;
        if (!segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            _accordionOpCtx = { wrapper };
            if (_isWrapperContextShown(wrapper) || !wrapper.querySelector('.val-card-actions')) {
                // Context already shown, or rebuilt accordion (no toggle btn) — enter immediately
                enterEditWithBuffer(seg, row, 'split');
            } else {
                // Context toggle exists but not shown yet — show first, then enter
                ensureContextShown(row);
                setTimeout(() => enterEditWithBuffer(seg, row, 'split'), 1000);
            }
            return;
        }
        enterEditWithBuffer(seg, row, 'split');
        return;
    }
    // Merge prev/next buttons
    const mergePrev = e.target.closest('.btn-merge-prev');
    if (mergePrev) {
        e.stopPropagation();
        const row = mergePrev.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        if (!segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            if (_isWrapperContextShown(wrapper) || !wrapper.querySelector('.val-card-actions')) {
                _accordionOpCtx = { wrapper, direction: 'prev' };
                mergeAdjacent(seg, 'prev');
            } else {
                ensureContextShown(row);
                setTimeout(() => {
                    _accordionOpCtx = { wrapper, direction: 'prev' };
                    mergeAdjacent(seg, 'prev');
                }, 1000);
            }
            return;
        }
        mergeAdjacent(seg, 'prev');
        return;
    }
    const mergeNext = e.target.closest('.btn-merge-next');
    if (mergeNext) {
        e.stopPropagation();
        const row = mergeNext.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        if (!segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            if (_isWrapperContextShown(wrapper) || !wrapper.querySelector('.val-card-actions')) {
                _accordionOpCtx = { wrapper, direction: 'next' };
                mergeAdjacent(seg, 'next');
            } else {
                ensureContextShown(row);
                setTimeout(() => {
                    _accordionOpCtx = { wrapper, direction: 'next' };
                    mergeAdjacent(seg, 'next');
                }, 1000);
            }
            return;
        }
        mergeAdjacent(seg, 'next');
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
    // Edit Ref button
    const editRefBtn = e.target.closest('.btn-edit-ref');
    if (editRefBtn) {
        e.stopPropagation();
        const row = editRefBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const refSpan = row.querySelector('.seg-text-ref');
            if (refSpan) startRefEdit(refSpan, seg, row);
        }
        return;
    }
    // Row click to play (ignore if clicking on actions)
    const row = e.target.closest('.seg-row');
    if (row && !e.target.closest('.seg-play-col') && !e.target.closest('.seg-actions')) {
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
    if (seg.segment_uid) row.dataset.segUid = seg.segment_uid;

    // For history cards: store time/audio data directly so the waveform observer
    // can draw even when the segment no longer exists at this index.
    if (readOnly) {
        row.dataset.histTimeStart = seg.time_start;
        row.dataset.histTimeEnd = seg.time_end;
        if (seg.audio_url) row.dataset.histAudioUrl = seg.audio_url;
    }

    // Play column at the far left (between waveforms of adjacent cards)
    if (!isContext && !readOnly) {
        const playCol = document.createElement('div');
        playCol.className = 'seg-play-col';

        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.textContent = '\u25B6';
        playBtn.title = 'Play segment audio';
        playCol.appendChild(playBtn);

        if (showGotoBtn) {
            const gotoBtn = document.createElement('button');
            gotoBtn.className = 'btn btn-sm seg-card-goto-btn';
            gotoBtn.textContent = 'Go to';
            playCol.appendChild(gotoBtn);
        }

        row.appendChild(playCol);
    }

    // Left column: canvas + action buttons
    const leftCol = document.createElement('div');
    leftCol.className = 'seg-left';

    const canvas = document.createElement('canvas');
    canvas.width = 380;
    canvas.height = 60;
    canvas.setAttribute('data-needs-waveform', '');

    if (readOnly && showPlayBtn) {
        // History cards: play button to the left of the waveform
        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.textContent = '\u25B6';
        playBtn.title = 'Play segment audio';
        leftCol.appendChild(playBtn);
        leftCol.appendChild(canvas);
    } else {
        leftCol.appendChild(canvas);
    }

    // Editing grid below waveform (no play column — it's at row level now)
    if (!isContext && !readOnly) {
        const actions = document.createElement('div');
        actions.className = 'seg-actions';

        const trimBtn = document.createElement('button');
        trimBtn.className = 'btn btn-sm btn-adjust';
        trimBtn.textContent = 'Adjust';

        const { prev: adjPrev, next: adjNext } = getAdjacentSegments(seg.chapter, seg.index);

        const mergePrevBtn = document.createElement('button');
        mergePrevBtn.className = 'btn btn-sm btn-merge-prev';
        mergePrevBtn.textContent = 'Merge \u2191';
        if (!adjPrev) {
            mergePrevBtn.disabled = true;
            mergePrevBtn.title = 'No previous segment to merge with';
        } else if (adjPrev.audio_url && seg.audio_url && adjPrev.audio_url !== seg.audio_url) {
            mergePrevBtn.disabled = true;
            mergePrevBtn.title = 'Cannot merge segments from different audio files';
        }

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm btn-delete';
        deleteBtn.textContent = 'Delete';

        const splitBtn = document.createElement('button');
        splitBtn.className = 'btn btn-sm btn-split';
        splitBtn.textContent = 'Split';

        const mergeNextBtn = document.createElement('button');
        mergeNextBtn.className = 'btn btn-sm btn-merge-next';
        mergeNextBtn.textContent = 'Merge \u2193';
        if (!adjNext) {
            mergeNextBtn.disabled = true;
            mergeNextBtn.title = 'No next segment to merge with';
        } else if (adjNext.audio_url && seg.audio_url && adjNext.audio_url !== seg.audio_url) {
            mergeNextBtn.disabled = true;
            mergeNextBtn.title = 'Cannot merge segments from different audio files';
        }

        const editRefBtn = document.createElement('button');
        editRefBtn.className = 'btn btn-sm btn-edit-ref';
        editRefBtn.textContent = 'Edit Ref';

        actions.append(trimBtn, mergePrevBtn, deleteBtn, splitBtn, mergeNextBtn, editRefBtn);
        leftCol.appendChild(actions);
    } else if (isContext) {
        // Context cards: hidden play button for click-to-play via row click
        const playBtn = document.createElement('button');
        playBtn.className = 'btn btn-sm seg-card-play-btn';
        playBtn.hidden = true;
        leftCol.appendChild(playBtn);
    }

    row.appendChild(leftCol);

    // Text box (right column): metadata left, Arabic text right
    const textBox = document.createElement('div');
    const confClass = getConfClass(seg);
    textBox.className = `seg-text ${confClass}`;

    // Metadata column (left side of text box)
    const metaCol = document.createElement('div');
    metaCol.className = 'seg-text-meta';

    // Header: #N | ref | duration
    const header = document.createElement('div');
    header.className = 'seg-text-header';

    const indexSpan = document.createElement('span');
    indexSpan.className = 'seg-text-index';
    indexSpan.textContent = showChapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const sep1 = document.createElement('span');
    sep1.className = 'seg-text-sep';
    sep1.textContent = '|';

    const refSpan = document.createElement('span');
    refSpan.className = 'seg-text-ref';
    refSpan.textContent = formatRef(seg.matched_ref);

    const sep2 = document.createElement('span');
    sep2.className = 'seg-text-sep';
    sep2.textContent = '|';

    const durSpan = document.createElement('span');
    durSpan.className = 'seg-text-duration';
    const durSec = (seg.time_end - seg.time_start) / 1000;
    durSpan.textContent = durSec.toFixed(1) + 's';
    durSpan.title = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;

    header.append(indexSpan, sep1, refSpan, sep2, durSpan);
    if (missingWordSegIndices && missingWordSegIndices.has(seg.index)) {
        const tag = document.createElement('span');
        tag.className = 'seg-tag seg-tag-missing';
        tag.textContent = 'Missing words';
        header.appendChild(tag);
    }
    metaCol.appendChild(header);

    // Confidence below header
    const confSpan = document.createElement('span');
    confSpan.className = `seg-text-conf ${confClass}`;
    confSpan.textContent = seg.matched_ref ? (seg.confidence * 100).toFixed(1) + '%' : 'FAIL';
    metaCol.appendChild(confSpan);

    // Context label (for context cards)
    if (contextLabel) {
        const lbl = document.createElement('div');
        lbl.className = 'seg-text-label';
        lbl.textContent = contextLabel;
        metaCol.appendChild(lbl);
    }

    textBox.appendChild(metaCol);

    // Arabic text (right side, top-aligned)
    const body = document.createElement('div');
    body.className = 'seg-text-body';
    body.textContent = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';
    textBox.appendChild(body);

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

/** Draw waveform from peaks for a segment, resolving its audio URL. Returns true if drawn. */
function drawWaveformFromPeaksForSeg(canvas, seg, chapter) {
    if (!segPeaksByAudio) return false;
    const audioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const pe = segPeaksByAudio[audioUrl];
    if (pe?.peaks?.length > 0) {
        drawSegmentWaveformFromPeaks(canvas, seg.time_start, seg.time_end, pe.peaks, pe.duration_ms);
        return true;
    }
    return false;
}

function drawSegPlayhead(canvas, startMs, endMs, currentTimeMs, audioUrl) {
    // Restore cached waveform image if available (avoids recomputing from raw samples every frame)
    const ctx = canvas.getContext('2d');
    const cacheKey = `${startMs}:${endMs}`;
    if (canvas._wfCache && canvas._wfCacheKey === cacheKey) {
        ctx.putImageData(canvas._wfCache, 0, 0);
    } else {
        if (segPeaksByAudio && audioUrl) {
            const pe = segPeaksByAudio[audioUrl];
            if (pe?.peaks?.length) {
                drawSegmentWaveformFromPeaks(canvas, startMs, endMs, pe.peaks, pe.duration_ms);
            }
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

function playFromSegment(segIndex, chapterOverride, seekToMs) {
    if (!segAllData) return;
    stopErrorCardAudio();
    _activeAudioSource = 'main';
    const chapter = chapterOverride ?? (segChapterSelect.value ? parseInt(segChapterSelect.value) : null);
    const seg = chapter != null
        ? getSegByChapterIndex(chapter, segIndex)
        : (segDisplayedSegments ? segDisplayedSegments.find(s => s.index === segIndex) : null);
    if (!seg) return;

    _segContinuousPlay = _segAutoPlayEnabled;
    _segPlayEndMs = seg.time_end;

    // Ensure audio element has a src (deferred from chapter select)
    const segAudioUrl = seg.audio_url || '';
    if (segAudioUrl && !segAudioEl.src.endsWith(segAudioUrl)) {
        segAudioEl.src = segAudioUrl;
    }

    segAudioEl.playbackRate = parseFloat(segSpeedSelect.value);
    segAudioEl.currentTime = (seekToMs != null ? seekToMs : seg.time_start) / 1000;
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
    if (!next) return;
    const currentUrl = segAudioEl.src || '';
    if (!next.audio_url || _audioSrcMatch(next.audio_url, currentUrl)) return;
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
            _segContinuousPlay = _segAutoPlayEnabled;
            _activeAudioSource = 'main';
            // Refresh _segPlayEndMs from current segment data so a trimmed segment
            // doesn't use a stale pre-trim end time.
            if (segCurrentIdx >= 0 && segDisplayedSegments) {
                const curSeg = segDisplayedSegments.find(s => s.index === segCurrentIdx);
                if (curSeg) _segPlayEndMs = curSeg.time_end;
            }
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
    const currentSrc = segAudioEl.src || '';

    // Find the last displayed segment on the *current* audio file
    let lastSegOnAudio = null;
    if (segDisplayedSegments && segDisplayedSegments.length > 0) {
        for (let i = segDisplayedSegments.length - 1; i >= 0; i--) {
            const s = segDisplayedSegments[i];
            if (_audioSrcMatch(s.audio_url, currentSrc)) {
                lastSegOnAudio = s;
                break;
            }
        }
        if (!lastSegOnAudio) lastSegOnAudio = segDisplayedSegments[segDisplayedSegments.length - 1];
    }

    // At end of last segment on this audio file: auto-advance or stop
    if (lastSegOnAudio && timeMs >= lastSegOnAudio.time_end) {
        const nextSeg = _nextDisplayedSeg(lastSegOnAudio.index);
        const isConsecutive = nextSeg && nextSeg.index === lastSegOnAudio.index + 1;
        if (_segContinuousPlay && isConsecutive && !_audioSrcMatch(nextSeg.audio_url, currentSrc)) {
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
                if (currentSrc && !_audioSrcMatch(seg.audio_url, currentSrc)) continue;
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
                && _audioSrcMatch(s.audio_url, currentSrc));
            if (justEnded) {
                const nextSeg2 = _nextDisplayedSeg(justEnded.index);
                if (nextSeg2 && _audioSrcMatch(nextSeg2.audio_url, currentSrc)) {
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
        // When autoplay is off and we drift into a new segment (zero-gap adjacency),
        // stop playback — the user only intended to play the original segment.
        if (!_segContinuousPlay && prevIdx >= 0 && segCurrentIdx >= 0) {
            segAudioEl.pause();
            stopSegAnimation();
            _segPlayEndMs = 0;
            return;
        }
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
    // Sync play button icon on the active row
    if (_prevHighlightedRow) {
        const btn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25A0';
    }
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
    // Sync play button icon on the active row
    if (_prevHighlightedRow) {
        const btn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25B6';
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
    // Frame-accurate stop: don't wait for timeupdate (~250ms lag) when not in
    // continuous-play mode. Continuous play is still handled by onSegTimeUpdate.
    if (!_segContinuousPlay && _segPlayEndMs > 0 && !segAudioEl.paused
            && segAudioEl.currentTime * 1000 >= _segPlayEndMs) {
        segAudioEl.pause();
        stopSegAnimation();
        _segPlayEndMs = 0;
        return;
    }
    segAnimId = requestAnimationFrame(animateSeg);
}

let _prevHighlightedRow = null;
let _prevHighlightedIdx = -1;

function updateSegHighlight() {
    if (segCurrentIdx === _prevHighlightedIdx) return;
    if (_prevHighlightedRow) {
        _prevHighlightedRow.classList.remove('playing');
        const prevBtn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (prevBtn) prevBtn.textContent = '\u25B6';
    }
    _prevHighlightedRow = null;
    _prevHighlightedIdx = segCurrentIdx;
    if (segCurrentIdx >= 0) {
        const row = segListEl.querySelector(`.seg-row[data-seg-index="${segCurrentIdx}"]`);
        if (row) {
            row.classList.add('playing');
            _prevHighlightedRow = row;
            if (!segAudioEl.paused) {
                const btn = row.querySelector('.seg-card-play-btn');
                if (btn) btn.textContent = '\u25A0';
            }
        }
    }
}

let _prevPlayheadIdx = -1;
let _prevPlayheadRow = null;
let _currentPlayheadRow = null;

function drawActivePlayhead() {
    if (!segAllData || !segChapterSelect.value) return;
    // Don't overwrite the edit-mode waveform with playhead animation
    if (segEditMode && segCurrentIdx === segEditIndex) return;
    const chapter = parseInt(segChapterSelect.value);
    const time = segAudioEl.currentTime * 1000; // convert to ms

    const indexChanged = _prevPlayheadIdx !== segCurrentIdx;

    // Clear playhead from previously active canvas (if it changed)
    if (_prevPlayheadIdx >= 0 && indexChanged) {
        const prevRow = _prevPlayheadRow || segListEl.querySelector(`.seg-row[data-seg-index="${_prevPlayheadIdx}"]`);
        if (prevRow) {
            const canvas = prevRow.querySelector('canvas');
            const seg = getSegByChapterIndex(chapter, _prevPlayheadIdx);
            if (canvas && seg) {
                drawWaveformFromPeaksForSeg(canvas, seg, chapter);
            }
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
            if (canvas && seg) {
                const audioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';
                drawSegPlayhead(canvas, seg.time_start, seg.time_end, time, audioUrl);
            }
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

    // Pause audio and disable continuous play so auto-advance doesn't interrupt editing
    if (!segAudioEl.paused) { segAudioEl.pause(); stopSegAnimation(); }
    _segContinuousPlay = false;

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
            _splitChainUid = null; _splitChainWrapper = null;  // cancel split chain on Escape
            refSpan.textContent = formatRef(originalRef);
        }
    });

    input.addEventListener('blur', commit);
    input.addEventListener('click', (e) => e.stopPropagation());
}

/** After split ref-edit on first half, chain to editing the second half. */
function _chainSplitRefEdit(chapter) {
    if (!_splitChainUid) return;
    const chainUid = _splitChainUid;
    const chainWrapper = _splitChainWrapper;
    _splitChainUid = null;
    _splitChainWrapper = null;
    // Search segAllData first (always complete), fall back to segData for current chapter
    const allSegs = segAllData?.segments || segData?.segments || [];
    const secondSeg = allSegs.find(s => s.segment_uid === chainUid);
    if (!secondSeg) return;
    const selector = `.seg-row[data-seg-chapter="${secondSeg.chapter}"][data-seg-index="${secondSeg.index}"]`;
    // Prefer the accordion wrapper over the main list to keep the edit in-context
    const secondRow = (chainWrapper && chainWrapper.querySelector(selector))
        || segListEl.querySelector(selector)
        || document.querySelector(selector);
    if (!secondRow) return;
    secondRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const refSpan = secondRow.querySelector('.seg-text-ref');
    if (refSpan) {
        segPlayStatus.textContent = 'Now edit second half reference';
        setTimeout(() => startRefEdit(refSpan, secondSeg, secondRow), 100);
    }
}

async function commitRefEdit(seg, newRef, row) {
    const oldRef = seg.matched_ref || '';
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    // Normalize short refs: "1:7" → "1:7:1-1:7:N"
    newRef = _normalizeRef(newRef);
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
        _chainSplitRefEdit(chapter);
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

    _chainSplitRefEdit(chapter);
}

/** Update a single .seg-row card in-place (works for both main and error section cards). */
function updateSegCard(row, seg) {
    row.classList.add('dirty');

    // Grey out any ignore button on this card — segment already has a pending edit.
    // The button lives in .val-card-wrapper (sibling of .seg-row), so walk up if not found inside row.
    const ignoreBtn = row.querySelector('.val-action-btn.ignore-btn')
        || row.closest('.val-card-wrapper')?.querySelector('.val-action-btn.ignore-btn');
    if (ignoreBtn && !ignoreBtn.disabled) {
        ignoreBtn.disabled = true;
        ignoreBtn.title = 'Cannot ignore — this segment already has unsaved edits';
    }

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
    if (body) body.textContent = _addVerseMarkers(seg.display_text || seg.matched_text, seg.matched_ref) || '(alignment failed)';

    const durSpan = row.querySelector('.seg-text-duration');
    if (durSpan) {
        const durSec = (seg.time_end - seg.time_start) / 1000;
        durSpan.textContent = durSec.toFixed(1) + 's';
        durSpan.title = `${formatTimeMs(seg.time_start)} \u2013 ${formatTimeMs(seg.time_end)}`;
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
    showSavePreview();
}

// ---------------------------------------------------------------------------
// Save Confirmation Preview
// ---------------------------------------------------------------------------

function buildSavePreviewData() {
    const batches = [];
    const warningChapters = [];
    const opCounts = {};
    const fixKindCounts = {};
    let totalOps = 0;

    for (const [ch, dirtyEntry] of segDirtyMap) {
        const chOps = segOpLog.get(ch) || [];
        if (chOps.length === 0) { warningChapters.push(ch); continue; }
        for (const op of chOps) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            fixKindCounts[op.fix_kind || 'manual'] = (fixKindCounts[op.fix_kind || 'manual'] || 0) + 1;
            totalOps++;
        }
        batches.push({
            batch_id: null,
            saved_at_utc: null,
            chapter: parseInt(ch),
            save_mode: dirtyEntry.structural ? 'full_replace' : 'patch',
            operations: chOps,
        });
    }

    const summary = {
        total_operations: totalOps,
        total_batches: batches.length + warningChapters.length,
        chapters_edited: batches.length + warningChapters.length,
        verses_edited: _countVersesFromBatches(batches),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
    return { batches, summary, warningChapters };
}

function showSavePreview() {
    if (!segSavePreview.hidden) return;
    _segSavedPreviewState = { scrollTop: segListEl.scrollTop };
    const data = buildSavePreviewData();

    // Rebuild split chains from combined saved + pending data so pending trims/splits
    // on split-derived segments render inside their chain row.
    _segSavedChains = { splitChains: _splitChains, chainedOpIds: _chainedOpIds };
    const allBatches = [...(segHistoryData?.batches || []), ...data.batches];
    const splitLineage = _buildSplitLineage(allBatches);
    const { chains, chainedOpIds } = _buildSplitChains(allBatches, splitLineage);
    _splitChains = chains;
    _chainedOpIds = chainedOpIds;

    // Render stats
    renderHistorySummaryStats(data.summary, segSavePreviewStats);

    // Show warning for dirty chapters with no recorded operations
    if (data.warningChapters.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'seg-save-preview-warning';
        warn.textContent = `${data.warningChapters.length} chapter(s) marked as changed `
            + `but have no detailed operations recorded: `
            + data.warningChapters.map(c => surahOptionText(c)).join(', ');
        segSavePreviewStats.prepend(warn);
    }

    // Render batches
    renderHistoryBatches(data.batches, segSavePreviewBatches);

    // Style pending timestamps in gold
    segSavePreviewBatches.querySelectorAll('.seg-history-batch-time').forEach(el => {
        if (el.textContent === 'Pending') el.style.color = '#f0a500';
    });

    // Hide normal UI (same pattern as showHistoryView)
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { el.dataset.hiddenByPreview = el.hidden ? '1' : ''; el.hidden = true; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { controls.dataset.hiddenByPreview = controls.hidden ? '1' : ''; controls.hidden = true; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { shortcuts.dataset.hiddenByPreview = shortcuts.hidden ? '1' : ''; shortcuts.hidden = true; }
    segHistoryView.hidden = true;

    segSavePreview.hidden = false;

    // Trigger waveform observer + arrows
    const observer = _ensureWaveformObserver();
    segSavePreview.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        segSavePreview.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
}

function hideSavePreview(restoreScroll = true) {
    stopErrorCardAudio();
    segSavePreview.hidden = true;
    segSavePreviewStats.innerHTML = '';
    segSavePreviewBatches.innerHTML = '';

    // Restore history-only chains (preview may have merged pending ops into chains)
    if (_segSavedChains) {
        _splitChains = _segSavedChains.splitChains;
        _chainedOpIds = _segSavedChains.chainedOpIds;
        _segSavedChains = null;
    }

    // Restore normal UI
    for (const id of _SEG_NORMAL_IDS) {
        const el = document.getElementById(id);
        if (el) { if (el.dataset.hiddenByPreview !== '1') el.hidden = false; delete el.dataset.hiddenByPreview; }
    }
    const panel = document.getElementById('segments-panel');
    const controls = panel.querySelector('.seg-controls');
    if (controls) { if (controls.dataset.hiddenByPreview !== '1') controls.hidden = false; delete controls.dataset.hiddenByPreview; }
    const shortcuts = panel.querySelector('.shortcuts-guide');
    if (shortcuts) { if (shortcuts.dataset.hiddenByPreview !== '1') shortcuts.hidden = false; delete shortcuts.dataset.hiddenByPreview; }

    // If pending edits were discarded, reload data to restore clean state
    if (_segDataStale) {
        _segDataStale = false;
        _segSavedPreviewState = null;
        onSegReciterChange();
    } else if (restoreScroll && _segSavedPreviewState) {
        const saved = _segSavedPreviewState;
        _segSavedPreviewState = null;
        requestAnimationFrame(() => { segListEl.scrollTop = saved.scrollTop; });
    }
}

async function confirmSaveFromPreview() {
    hideSavePreview(false);  // defer scroll restore to refreshValidation
    await executeSave();
}

async function executeSave() {
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
                    segments: chSegs.map(s => {
                        const o = {
                            segment_uid: s.segment_uid || '',
                            time_start: s.time_start,
                            time_end: s.time_end,
                            matched_ref: s.matched_ref,
                            matched_text: s.matched_text,
                            confidence: s.confidence,
                            phonemes_asr: s.phonemes_asr || '',
                            audio_url: s.audio_url || '',
                        };
                        if (s.wrap_word_ranges) o.wrap_word_ranges = s.wrap_word_ranges;
                        if (s.has_repeated_words) o.has_repeated_words = true;
                        return o;
                    }),
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
            // Trigger validation.log generation once for all saves, then refresh UI
            fetch(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' })
                .then(() => refreshValidation())
                .catch(() => refreshValidation());
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


async function _afterUndoSuccess(reciter, opsReversed) {
    try {
        const histResp = await fetch(`/api/seg/edit-history/${reciter}`);
        if (histResp.ok) {
            segHistoryData = await histResp.json();
            renderEditHistoryPanel(segHistoryData);
            const observer = _ensureWaveformObserver();
            segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
            requestAnimationFrame(() => {
                segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
            });
        }
    } catch (_) { /* non-critical */ }
    _segDataStale = true;
    fetch(`/api/seg/trigger-validation/${reciter}`, { method: 'POST' }).catch(() => {});
    segPlayStatus.textContent = `Undo successful — ${opsReversed} op${opsReversed !== 1 ? 's' : ''} reversed`;
}

async function onBatchUndoClick(batchId, chapter, btn) {
    const reciter = segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this save${chLabel}? The operations will be reversed.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const resp = await fetch(`/api/seg/undo-batch/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: batchId }),
        });
        const result = await resp.json();
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo batch failed:', e);
        alert('Undo failed — see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

async function onOpUndoClick(batchId, opIds, btn) {
    const reciter = segReciterSelect.value;
    if (!reciter) return;
    if (!confirm('Undo this operation?')) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    try {
        const resp = await fetch(`/api/seg/undo-ops/${reciter}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ batch_id: batchId, op_ids: opIds }),
        });
        const result = await resp.json();
        if (result.ok) {
            await _afterUndoSuccess(reciter, result.operations_reversed);
        } else {
            alert(`Undo failed: ${result.error}`);
            btn.disabled = false;
            btn.textContent = 'Undo';
        }
    } catch (e) {
        console.error('Undo op failed:', e);
        alert('Undo failed — see console for details');
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

/**
 * Returns unique saved batch IDs from a split chain, newest first.
 * Pending (unsaved) ops have no batch_id and are excluded.
 */
function _getChainBatchIds(chain) {
    const seen = new Set();
    const ids = [];
    // Walk ops in reverse so the result is newest-first
    for (let i = chain.ops.length - 1; i >= 0; i--) {
        const batchId = chain.ops[i].batch?.batch_id;
        if (batchId && !seen.has(batchId)) {
            seen.add(batchId);
            ids.push(batchId);
        }
    }
    return ids;
}

/**
 * Undo all batches in a split chain, in reverse chronological order (newest first).
 * Each batch is undone sequentially; if one fails the chain stops and shows the error.
 */
async function onChainUndoClick(batchIds, chapter, btn) {
    const reciter = segReciterSelect.value;
    if (!reciter) return;
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Undo this entire split chain${chLabel}? ${batchIds.length} save(s) will be reversed in order.`)) return;

    btn.disabled = true;
    btn.textContent = 'Undoing...';

    let totalReversed = 0;
    let failed = false;
    for (const batchId of batchIds) {
        try {
            const resp = await fetch(`/api/seg/undo-batch/${reciter}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ batch_id: batchId }),
            });
            const result = await resp.json();
            if (result.ok) {
                totalReversed += result.operations_reversed || 0;
            } else {
                alert(`Undo failed on batch ${batchIds.indexOf(batchId) + 1}/${batchIds.length}: ${result.error}`);
                failed = true;
                break;
            }
        } catch (e) {
            console.error('Chain undo failed:', e);
            alert('Undo failed — see console for details');
            failed = true;
            break;
        }
    }

    // Refresh history regardless (partial undo still changed data)
    await _afterUndoSuccess(reciter, totalReversed);
    if (!failed) {
        segPlayStatus.textContent = `Undo successful — ${totalReversed} op${totalReversed !== 1 ? 's' : ''} reversed across ${batchIds.length} save(s)`;
    } else {
        btn.disabled = false;
        btn.textContent = 'Undo';
    }
}

function onPendingBatchDiscard(chapter, btn) {
    const chLabel = chapter != null ? ` for ${surahOptionText(chapter)}` : '';
    if (!confirm(`Discard pending edits${chLabel}?`)) return;

    // Remove this chapter's dirty state and operation log
    segDirtyMap.delete(chapter);
    segDirtyMap.delete(String(chapter));
    segOpLog.delete(chapter);
    segOpLog.delete(String(chapter));

    // Flag data as stale so the in-memory segment data refreshes on close
    _segDataStale = true;

    // Update save button state
    segSaveBtn.disabled = !isDirty();

    // Re-render preview or close if nothing left
    if (!isDirty()) {
        hideSavePreview();
        return;
    }
    // Rebuild and re-render the preview in-place
    const data = buildSavePreviewData();
    // Rebuild chains from updated combined data
    const allBatches = [...(segHistoryData?.batches || []), ...data.batches];
    const splitLineage = _buildSplitLineage(allBatches);
    const { chains: ch, chainedOpIds: cIds } = _buildSplitChains(allBatches, splitLineage);
    _splitChains = ch;
    _chainedOpIds = cIds;
    renderHistorySummaryStats(data.summary, segSavePreviewStats);
    if (data.warningChapters.length > 0) {
        const warn = document.createElement('div');
        warn.className = 'seg-save-preview-warning';
        warn.textContent = `${data.warningChapters.length} chapter(s) marked as changed `
            + `but have no detailed operations recorded: `
            + data.warningChapters.map(c => surahOptionText(c)).join(', ');
        segSavePreviewStats.prepend(warn);
    }
    renderHistoryBatches(data.batches, segSavePreviewBatches);
    segSavePreviewBatches.querySelectorAll('.seg-history-batch-time').forEach(el => {
        if (el.textContent === 'Pending') el.style.color = '#f0a500';
    });
    // Re-trigger arrows
    const observer = _ensureWaveformObserver();
    segSavePreview.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        segSavePreview.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
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
            localStorage.setItem('insp_seg_speed', segSpeedSelect.value);
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
        case 'Escape':
            if (!segSavePreview.hidden) {
                e.preventDefault();
                hideSavePreview();
            } else if (segEditMode) {
                e.preventDefault();
                exitEditMode();
            } else if (_segSavedFilterView) {
                e.preventDefault();
                _restoreFilterView();
            }
            break;

        case 'Enter':
            if (!segSavePreview.hidden) {
                e.preventDefault();
                confirmSaveFromPreview();
            } else if (segEditMode && segCurrentIdx >= 0) {
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


/** Find the card canvas that's currently in edit mode. */
function _getEditCanvas() {
    const row = document.querySelector('.seg-row.seg-edit-target');
    return row?.querySelector('canvas') || null;
}

// ---------------------------------------------------------------------------
// Adjust mode
// ---------------------------------------------------------------------------

let TRIM_PAD_LEFT = 500;          // ms padding before segment in adjust mode (overridden by config)
let TRIM_PAD_RIGHT = 500;         // ms padding after segment in adjust mode (overridden by config)
let TRIM_DIM_ALPHA = 0.45;        // dimming opacity for padded regions (overridden by config)
let SHOW_BOUNDARY_PHONEMES = true; // show GT/ASR tail phonemes on boundary_adj cards (overridden by config)

/**
 * Enter trim or split mode. Waveforms are drawn from peaks (no audio buffer needed).
 */
function enterEditWithBuffer(seg, row, mode) {
    if (segEditMode) return;

    // Capture playback position before pausing (used by enterSplitMode to seed the cursor)
    const isErrorPlaying = _activeAudioSource === 'error' && valCardAudio && !valCardAudio.paused;
    const prePausePlayMs = isErrorPlaying
        ? valCardAudio.currentTime * 1000
        : (segAudioEl.paused ? null : segAudioEl.currentTime * 1000);

    // Pause audio and disable continuous play so auto-advance doesn't interrupt editing
    if (isErrorPlaying) stopErrorCardAudio();
    if (!segAudioEl.paused) { segAudioEl.pause(); stopSegAnimation(); }
    _segContinuousPlay = false;

    // Hide play button — edit mode has its own preview controls
    const playCol = row.querySelector('.seg-play-col');
    if (playCol) playCol.hidden = true;

    // Edit history: snapshot before entering edit mode
    _pendingOp = createOp(mode === 'trim' ? 'trim_segment' : 'split_segment');
    _pendingOp.targets_before = [snapshotSeg(seg)];

    try {
        if (mode === 'trim') enterTrimMode(seg, row);
        else if (mode === 'split') enterSplitMode(seg, row, prePausePlayMs);
    } catch (e) {
        console.error(`[${mode}] error entering edit mode:`, e);
        _pendingOp = null;
        segEditMode = null;
        segEditIndex = -1;
        document.body.classList.remove('seg-edit-active');
        const targetRow = document.querySelector('.seg-row.seg-edit-target');
        if (targetRow) {
            targetRow.querySelector('.seg-edit-inline')?.remove();
            const acts = targetRow.querySelector('.seg-actions');
            if (acts) acts.hidden = false;
            targetRow.classList.remove('seg-edit-target');
        }
    }
}

function enterTrimMode(seg, row) {
    if (segEditMode) {
        console.warn('[trim] blocked: already in edit mode:', segEditMode);
        return;
    }
    segEditMode = 'trim';
    segEditIndex = seg.index;

    // Dim other rows via CSS
    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    // Hide normal action buttons, create inline controls
    const actions = row.querySelector('.seg-actions');
    if (actions) actions.hidden = true;

    const canvas = row.querySelector('canvas');
    const segLeft = row.querySelector('.seg-left');

    // Build inline edit controls (visual-only, no number inputs)
    const inline = document.createElement('div');
    inline.className = 'seg-edit-inline';

    const durationSpan = document.createElement('span');
    durationSpan.className = 'seg-edit-duration';
    durationSpan.textContent = `${((seg.time_end - seg.time_start) / 1000).toFixed(2)}s`;

    const statusSpan = document.createElement('span');
    statusSpan.className = 'seg-edit-status';
    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    const mkBtn = (text, cls, fn) => { const b = document.createElement('button'); b.className = `btn btn-sm ${cls}`; b.textContent = text; b.addEventListener('click', fn); return b; };
    btnRow.appendChild(mkBtn('Cancel', 'btn-cancel', exitEditMode));
    btnRow.appendChild(mkBtn('Preview', 'btn-preview', previewTrimAudio));
    btnRow.appendChild(mkBtn('Apply', 'btn-confirm', () => confirmTrim(seg)));
    btnRow.appendChild(durationSpan);
    btnRow.appendChild(statusSpan);
    inline.appendChild(btnRow);

    segLeft.appendChild(inline);

    // Store element refs on canvas for other functions to access
    canvas._trimEls = { durationSpan, statusSpan };

    // Compute context window: segment + small padding (clamped to adjacent boundaries)
    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const currentChapter = parseInt(segChapterSelect.value);
    const chapterSegs = (chapter === currentChapter) ? _getChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevEnd = segIdx > 0 ? chapterSegs[segIdx - 1].time_end : 0;
    const audioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const peaksDuration = segPeaksByAudio?.[audioUrl]?.duration_ms;
    const nextStart = segIdx >= 0 && segIdx < chapterSegs.length - 1
        ? chapterSegs[segIdx + 1].time_start
        : (peaksDuration || seg.time_end + 1000);
    const windowStart = Math.max(prevEnd, seg.time_start - TRIM_PAD_LEFT);
    const windowEnd = Math.min(nextStart, seg.time_end + TRIM_PAD_RIGHT);
    canvas._trimWindow = { windowStart, windowEnd, currentStart: seg.time_start, currentEnd: seg.time_end, audioUrl };
    canvas._wfCache = null; // clear cached normal waveform
    canvas._trimBaseCache = null;

    drawTrimWaveform(canvas);
    setupTrimDragHandles(canvas, seg);
}

/** Slice peaks for a time range and resample to `buckets` bins. Returns {maxVals, minVals} or null. */
function _slicePeaks(audioUrl, startMs, endMs, buckets) {
    if (!segPeaksByAudio) return null;
    const pe = segPeaksByAudio[audioUrl];
    if (!pe?.peaks?.length) return null;
    const pps = pe.peaks.length / pe.duration_ms;  // peaks per ms
    const startIdx = Math.max(0, Math.floor(startMs * pps));
    const endIdx = Math.min(pe.peaks.length, Math.ceil(endMs * pps));
    const slice = pe.peaks.slice(startIdx, endIdx);
    if (slice.length === 0) return null;
    const maxVals = new Float32Array(buckets);
    const minVals = new Float32Array(buckets);
    if (slice.length >= buckets) {
        // More data than pixels: block min/max
        const blockSize = slice.length / buckets;
        for (let i = 0; i < buckets; i++) {
            const from = Math.floor(i * blockSize);
            const to = Math.min(Math.ceil((i + 1) * blockSize), slice.length);
            let mx = -1, mn = 1;
            for (let j = from; j < to; j++) {
                if (slice[j][1] > mx) mx = slice[j][1];
                if (slice[j][0] < mn) mn = slice[j][0];
            }
            maxVals[i] = mx;
            minVals[i] = mn;
        }
    } else {
        // Fewer data points than pixels: linear interpolation
        for (let i = 0; i < buckets; i++) {
            const fi = (i / buckets) * (slice.length - 1);
            const lo = Math.floor(fi);
            const hi = Math.min(lo + 1, slice.length - 1);
            const t = fi - lo;
            minVals[i] = slice[lo][0] * (1 - t) + slice[hi][0] * t;
            maxVals[i] = slice[lo][1] * (1 - t) + slice[hi][1] * t;
        }
    }
    return { maxVals, minVals };
}

function _ensureTrimBaseCache(canvas) {
    if (canvas._trimBaseCache) return true;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const tw = canvas._trimWindow;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    const audioUrl = tw.audioUrl || '';
    const data = _slicePeaks(audioUrl, tw.windowStart, tw.windowEnd, width);
    if (!data) return false;

    const scale = height / 2 * 0.9;

    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - data.minVals[i] * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.stroke();

    canvas._trimBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

function drawTrimWaveform(canvas) {
    if (!_ensureTrimBaseCache(canvas)) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const tw = canvas._trimWindow;

    ctx.putImageData(canvas._trimBaseCache, 0, 0);

    // Dim outside the trim region
    const startX = ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;
    const endX = ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * width;

    ctx.fillStyle = `rgba(0, 0, 0, ${TRIM_DIM_ALPHA})`;
    ctx.fillRect(0, 0, startX, height);
    ctx.fillRect(endX, 0, width - endX, height);

    // Start handle (green)
    ctx.strokeStyle = '#4caf50';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(startX, 0);
    ctx.lineTo(startX, height);
    ctx.stroke();
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
    let didDrag = false;
    const HANDLE_THRESHOLD = 12;

    function _getHandleXs() {
        const tw = canvas._trimWindow, w = canvas.width;
        return {
            startX: ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
            endX: ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
        };
    }

    function onMousedown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const { startX, endX } = _getHandleXs();
        didDrag = false;

        if (Math.abs(x - startX) < HANDLE_THRESHOLD) dragging = 'start';
        else if (Math.abs(x - endX) < HANDLE_THRESHOLD) dragging = 'end';
        if (dragging) canvas.style.cursor = 'col-resize';
    }

    function onMousemove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const tw = canvas._trimWindow;
        const width = canvas.width;

        if (!dragging) {
            const { startX, endX } = _getHandleXs();
            canvas.style.cursor = (Math.abs(x - startX) < HANDLE_THRESHOLD || Math.abs(x - endX) < HANDLE_THRESHOLD) ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        const timeAtX = tw.windowStart + (x / width) * (tw.windowEnd - tw.windowStart);
        const snapped = Math.round(timeAtX / 10) * 10;

        if (dragging === 'start') {
            tw.currentStart = Math.max(tw.windowStart, Math.min(snapped, tw.currentEnd - 50));
        } else {
            tw.currentEnd = Math.max(tw.currentStart + 50, Math.min(snapped, tw.windowEnd));
        }
        updateTrimDuration(canvas);
        drawTrimWaveform(canvas);
    }

    function onMouseup(e) {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const tw = canvas._trimWindow;
            const timeAtX = tw.windowStart + (x / canvas.width) * (tw.windowEnd - tw.windowStart);
            // Snap to 10ms grid (same as handle dragging) so click-to-preview is
            // consistent with what the Preview button and Apply will use.
            const snapped = Math.round(timeAtX / 10) * 10;
            _playRange(snapped, tw.currentEnd);
        }
        dragging = null;
        canvas.style.cursor = '';
    }
    function onMouseleave() { dragging = null; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = () => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

function updateTrimDuration(canvas) {
    canvas = canvas || _getEditCanvas();
    const tw = canvas?._trimWindow;
    const el = canvas?._trimEls?.durationSpan;
    if (!tw || !el) return;
    el.textContent = `${((tw.currentEnd - tw.currentStart) / 1000).toFixed(2)}s`;
}

function confirmTrim(seg) {
    const canvas = _getEditCanvas();
    const tw = canvas?._trimWindow;
    const trimStatus = canvas?._trimEls?.statusSpan || null;
    const newStart = tw?.currentStart;
    const newEnd = tw?.currentEnd;
    if (newStart == null || newEnd == null || newStart >= newEnd) {
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
    seg.confidence = 1.0;
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
let _previewLooping = false;   // 'trim' | 'split-left' | 'split-right' | false
let _previewJustSeeked = false;

function previewTrimAudio() {
    const canvas = _getEditCanvas();
    const tw = canvas?._trimWindow;
    if (!tw) return;
    // Toggle: if already playing in trim preview, stop
    if (_previewLooping && !segAudioEl.paused) {
        _previewLooping = false;
        _previewJustSeeked = false;
        segAudioEl.pause();
        if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
        if (canvas._trimWindow) drawTrimWaveform(canvas);
        return;
    }
    _previewLooping = 'trim';
    _playRange(tw.currentStart, tw.currentEnd);
}


let _playRangeRAF = null;

function _playRange(startMs, endMs) {
    if (_previewStopHandler) {
        segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = _getEditCanvas();

    // Map playhead to waveform coordinate space
    let wfStart, wfEnd;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = () => {
        if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
        if (canvas?._splitData) drawSplitWaveform(canvas);
        else if (canvas?._trimWindow) drawTrimWaveform(canvas);
    };

    // For split/trim mode: redraw live each frame so dragging the handle while
    // playing visually updates in real time. For other cases use a static snapshot.
    const inEditMode = canvas && (canvas._splitData || canvas._trimWindow);
    let _playRangeSnapshot = null;
    if (canvas && !inEditMode) {
        _playRangeSnapshot = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
    }

    function animatePlayhead() {
        if (!canvas || segAudioEl.paused) return;
        const curMs = segAudioEl.currentTime * 1000;
        // Compute live effective end and loop-start for all preview modes
        let effectiveEnd = endMs;
        let loopStart = null;
        if (_previewLooping === 'trim' && canvas?._trimWindow) {
            effectiveEnd = canvas._trimWindow.currentEnd;
            loopStart = canvas._trimWindow.currentStart;
        } else if (_previewLooping === 'split-left' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.currentSplit;
            loopStart = canvas._splitData.seg.time_start;
        } else if (_previewLooping === 'split-right' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.seg.time_end;
            loopStart = canvas._splitData.currentSplit;
        } else if (canvas?._splitData && endMs !== canvas._splitData.seg.time_end) {
            // Non-looping split left: stop at current split point
            effectiveEnd = canvas._splitData.currentSplit;
        }
        // Clear the seek guard once the browser has actually seeked back
        if (_previewJustSeeked && curMs < effectiveEnd) {
            _previewJustSeeked = false;
        }
        if (curMs >= effectiveEnd && !_previewJustSeeked) {
            // Looping: seek to fresh start position
            if (_previewLooping && loopStart !== null) {
                segAudioEl.currentTime = loopStart / 1000;
                _previewJustSeeked = true;
                _playRangeRAF = requestAnimationFrame(animatePlayhead);
                return;
            }
            segAudioEl.pause();
            cleanup();
            return;
        }
        // Redraw base — split/trim modes redraw live so handle drags are reflected;
        // other modes restore a pre-computed snapshot
        if (canvas._splitData) drawSplitWaveform(canvas);
        else if (canvas._trimWindow) drawTrimWaveform(canvas);
        else if (_playRangeSnapshot) {
            canvas.getContext('2d').putImageData(_playRangeSnapshot, 0, 0);
        }
        if (curMs >= wfStart && curMs <= wfEnd) {
            const ctx = canvas.getContext('2d'), w = canvas.width, h = canvas.height;
            const x = ((curMs - wfStart) / (wfEnd - wfStart)) * w;
            ctx.strokeStyle = '#f72585'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = '#f72585';
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = () => {
        segAudioEl.currentTime = start;
        segAudioEl.playbackRate = parseFloat(segSpeedSelect.value);
        segAudioEl.play();
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    // Get audio URL from canvas edit data (works for both main list and accordion cards)
    const targetUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = segChapterSelect.value ? parseInt(segChapterSelect.value) : null;
                     const s = ch != null ? getSegByChapterIndex(ch, segEditIndex) : null;
                     return s && s.audio_url; })();
    if (targetUrl && !segAudioEl.src.endsWith(targetUrl)) {
        segAudioEl.src = targetUrl;
        segAudioEl.addEventListener('canplay', doPlay, { once: true });
        segAudioEl.load();
    } else if (segAudioEl.src && segAudioEl.readyState >= 1) {
        doPlay();
    } else if (targetUrl) {
        // Audio element has no usable source yet — force load
        segAudioEl.src = targetUrl;
        segAudioEl.addEventListener('canplay', doPlay, { once: true });
        segAudioEl.load();
    }
}

function previewSplitAudio(side) {
    const canvas = _getEditCanvas();
    const sd = canvas?._splitData;
    if (!sd) return;
    const loopKey = `split-${side}`;
    // Toggle: if already looping this side, stop
    if (_previewLooping === loopKey && !segAudioEl.paused) {
        _previewLooping = false;
        _previewJustSeeked = false;
        segAudioEl.pause();
        if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
        if (canvas._splitData) drawSplitWaveform(canvas);
        return;
    }
    _previewLooping = loopKey;
    const splitTime = sd.currentSplit;
    _playRange(
        side === 'left' ? sd.seg.time_start : splitTime,
        side === 'left' ? splitTime : sd.seg.time_end
    );
}

// ---------------------------------------------------------------------------
// Split mode
// ---------------------------------------------------------------------------

function enterSplitMode(seg, row, prePausePlayMs = null) {
    if (segEditMode) {
        console.warn('[split] blocked: already in edit mode:', segEditMode);
        return;
    }
    segEditMode = 'split';
    segEditIndex = seg.index;

    // Dim other rows via CSS
    row.classList.add('seg-edit-target');
    document.body.classList.add('seg-edit-active');

    // Hide normal action buttons, create inline controls
    const actions = row.querySelector('.seg-actions');
    if (actions) actions.hidden = true;

    const canvas = row.querySelector('canvas');
    const segLeft = row.querySelector('.seg-left');

    const mid = Math.round((seg.time_start + seg.time_end) / 2);
    const defaultSplit = (prePausePlayMs !== null && prePausePlayMs > seg.time_start && prePausePlayMs < seg.time_end)
        ? Math.round(prePausePlayMs)
        : mid;

    // Build inline edit controls (visual-only, no number inputs)
    const inline = document.createElement('div');
    inline.className = 'seg-edit-inline';

    const infoSpan = document.createElement('span');
    infoSpan.className = 'seg-edit-info';
    infoSpan.textContent = `L ${((defaultSplit - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - defaultSplit) / 1000).toFixed(2)}s`;

    const btnRow = document.createElement('div');
    btnRow.className = 'seg-edit-buttons';
    const mkBtn = (text, cls, fn) => { const b = document.createElement('button'); b.className = `btn btn-sm ${cls}`; b.textContent = text; b.addEventListener('click', fn); return b; };
    btnRow.appendChild(mkBtn('Cancel', 'btn-cancel', exitEditMode));
    btnRow.appendChild(mkBtn('Play Left', 'btn-preview', () => previewSplitAudio('left')));
    btnRow.appendChild(mkBtn('Play Right', 'btn-preview', () => previewSplitAudio('right')));
    btnRow.appendChild(mkBtn('Split', 'btn-confirm', () => confirmSplit(seg)));
    btnRow.appendChild(infoSpan);
    inline.appendChild(btnRow);

    segLeft.appendChild(inline);

    // Store element refs on canvas
    canvas._splitEls = { infoSpan };
    canvas._wfCache = null; // clear cached normal waveform

    const chapter = seg.chapter || parseInt(segChapterSelect.value);
    const splitAudioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';
    canvas._splitData = { seg, currentSplit: defaultSplit, audioUrl: splitAudioUrl };
    canvas._splitBaseCache = null;
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);
}

function _ensureSplitBaseCache(canvas) {
    if (canvas._splitBaseCache) return true;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const centerY = height / 2;
    const sd = canvas._splitData;
    const seg = sd.seg;

    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    const audioUrl = sd.audioUrl || '';
    const data = _slicePeaks(audioUrl, seg.time_start, seg.time_end, width);
    if (!data) {
        ctx.fillStyle = '#888';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No waveform data', width / 2, height / 2);
        return false;
    }

    const scale = height / 2 * 0.9;

    // Filled waveform
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    for (let i = width - 1; i >= 0; i--) {
        ctx.lineTo(i, centerY - data.minVals[i] * scale);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
    ctx.fill();

    // Waveform outline
    ctx.strokeStyle = '#4361ee';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < width; i++) {
        const y = centerY - data.maxVals[i] * scale;
        if (i === 0) ctx.moveTo(i, y); else ctx.lineTo(i, y);
    }
    ctx.stroke();

    canvas._splitBaseCache = ctx.getImageData(0, 0, width, height);
    return true;
}

function drawSplitWaveform(canvas) {
    const hasCachedBase = _ensureSplitBaseCache(canvas);
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const sd = canvas._splitData;
    const seg = sd.seg;

    if (hasCachedBase) ctx.putImageData(canvas._splitBaseCache, 0, 0);

    const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * width;

    // Tint right half differently
    ctx.fillStyle = 'rgba(255, 152, 0, 0.15)';
    ctx.fillRect(splitX, 0, width - splitX, height);

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
    let didDrag = false;

    function onMousedown(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;
        didDrag = false;
        if (Math.abs(x - splitX) < 15) {
            dragging = true;
            canvas.style.cursor = 'col-resize';
        }
    }

    function onMousemove(e) {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;

        if (!dragging) {
            // Hover cursor: col-resize near handle, pointer elsewhere
            canvas.style.cursor = Math.abs(x - splitX) < 15 ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
        const snapped = Math.round(timeAtX / 10) * 10;
        sd.currentSplit = Math.max(seg.time_start + 50, Math.min(snapped, seg.time_end - 50));
        updateSplitInfo(canvas, seg, sd.currentSplit);
        drawSplitWaveform(canvas);
    }

    function onMouseup(e) {
        if (!dragging && !didDrag) {
            // Click outside drag handle — play from click position
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const sd = canvas._splitData;
            const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
            if (timeAtX < sd.currentSplit) {
                _playRange(timeAtX, sd.currentSplit);
            } else {
                _playRange(timeAtX, seg.time_end);
            }
        }
        dragging = false;
        canvas.style.cursor = '';
    }
    function onMouseleave() { dragging = false; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = () => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

function updateSplitInfo(canvas, seg, splitTime) {
    canvas = canvas || _getEditCanvas();
    const el = canvas?._splitEls?.infoSpan;
    if (el) {
        el.textContent = `L ${((splitTime - seg.time_start) / 1000).toFixed(2)}s | R ${((seg.time_end - splitTime) / 1000).toFixed(2)}s`;
    }
}

function confirmSplit(seg) {
    const canvas = _getEditCanvas();
    const splitTime = canvas?._splitData?.currentSplit;
    if (splitTime == null || splitTime <= seg.time_start || splitTime >= seg.time_end) {
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
    _fixupValIndicesForSplit(chapter, seg.index);

    const accCtx = _accordionOpCtx;
    _accordionOpCtx = null;

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();

    if (accCtx) {
        _rebuildAccordionAfterSplit(accCtx.wrapper, chapter, seg, firstHalf, secondHalf);
    } else {
        refreshOpenAccordionCards();
    }

    // Edit history: finalize after re-render
    if (splitOp) finalizeOp(chapter, splitOp);

    segPlayStatus.textContent = 'Split — edit first half reference, then second';

    // Chain ref editing: first half → second half
    _splitChainUid = secondHalf.segment_uid;
    _splitChainWrapper = accCtx ? accCtx.wrapper : null;
    const searchRoot = accCtx ? accCtx.wrapper : segListEl;
    const firstRow = searchRoot.querySelector(`.seg-row[data-seg-chapter="${chapter}"][data-seg-index="${firstHalf.index}"]`);
    if (firstRow) {
        firstRow.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const refSpan = firstRow.querySelector('.seg-text-ref');
        if (refSpan) {
            startRefEdit(refSpan, firstHalf, firstRow);
        }
    }
}


// ---------------------------------------------------------------------------
// Merge
// ---------------------------------------------------------------------------

/** Merge a segment with its previous or next neighbour in the same chapter. */
async function mergeAdjacent(seg, direction) {
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
    mergeOp.merge_direction = direction;
    mergeOp.targets_before = [snapshotSeg(first), snapshotSeg(second)];

    const firstAudio = first.audio_url || '';
    const secondAudio = second.audio_url || '';
    if (firstAudio !== secondAudio) {
        // Safety guard — buttons should already be disabled for different audio files
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

    // Resolve text from merged ref (avoids duplicate words at overlap boundaries)
    let mergedText = [first.matched_text, second.matched_text].filter(Boolean).join(' ');
    let mergedDisplay = [first.display_text, second.display_text].filter(Boolean).join(' ');
    if (mergedRef) {
        try {
            const resp = await fetch(`/api/seg/resolve_ref?ref=${encodeURIComponent(mergedRef)}`);
            const data = await resp.json();
            if (data.text) {
                mergedText = data.text;
                mergedDisplay = data.display_text || data.text;
            }
        } catch (e) {
            console.warn('Failed to resolve merged ref, using concatenated text:', e);
        }
    }

    const merged = {
        ...first,
        segment_uid: crypto.randomUUID(),
        index: first.index,
        time_start: first.time_start,
        time_end: second.time_end,
        matched_ref: mergedRef,
        matched_text: mergedText,
        display_text: mergedDisplay,
        confidence: 1.0,
    };

    // Edit history: record applied state
    mergeOp.applied_at_utc = new Date().toISOString();
    mergeOp.targets_after = [snapshotSeg(merged)];

    const keptOldIdx = first.index;
    const consumedOldIdx = second.index;

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
    _fixupValIndicesForMerge(chapter, keptOldIdx, consumedOldIdx);
    if (chapter === currentChapter && segData) {
        segData.segments = getChapterSegments(chapter);
    }
    computeSilenceAfter();
    applyVerseFilterAndRender();

    const accCtx = _accordionOpCtx;
    _accordionOpCtx = null;
    const accCategory = accCtx?.wrapper?.closest('details[data-category]')?.dataset?.category;

    // Always refresh all open accordion cards so sibling wrappers get updated indices.
    refreshOpenAccordionCards();

    // Re-apply the specialized merged+context view on the freshly rendered wrapper.
    if (accCtx && accCategory) {
        const freshDetails = document.querySelector(`details[data-category="${accCategory}"]`);
        const mergedCard = freshDetails?.querySelector(`.seg-row[data-seg-uid="${merged.segment_uid}"]`);
        const freshWrapper = mergedCard?.closest('.val-card-wrapper');
        if (freshWrapper) {
            _rebuildAccordionAfterMerge(freshWrapper, chapter, merged, accCtx.direction);
        }
    }

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
    _fixupValIndicesForDelete(chapter, seg.index);

    // If deleted segment's chapter matches current chapter, re-render
    if (chapter === currentChapter && segData) {
        segData.segments = getChapterSegments(chapter);
    }

    computeSilenceAfter();
    applyVerseFilterAndRender();
    refreshOpenAccordionCards();

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
    _accordionOpCtx = null;

    // Restore the edit-target card to normal state
    const editRow = document.querySelector('.seg-row.seg-edit-target');
    if (editRow) {
        // Remove inline edit controls, restore normal action buttons and play column
        editRow.querySelector('.seg-edit-inline')?.remove();
        const actions = editRow.querySelector('.seg-actions');
        if (actions) actions.hidden = false;
        const playCol = editRow.querySelector('.seg-play-col');
        if (playCol) playCol.hidden = false;

        // Clean up canvas edit state
        const canvas = editRow.querySelector('canvas');
        if (canvas) {
            canvas._editCleanup?.();
            delete canvas._trimWindow; delete canvas._splitData;
            delete canvas._trimEls; delete canvas._splitEls;
            delete canvas._editCleanup;
            canvas._wfCache = null;
            canvas.style.cursor = '';
            // Redraw normal waveform (only needed on cancel — apply re-renders the list)
            const seg = resolveSegFromRow(editRow);
            if (seg) drawWaveformFromPeaksForSeg(canvas, seg, seg.chapter);
        }
    }

    segEditMode = null;
    segEditIndex = -1;
    // Stop any preview playback and animation
    _previewLooping = false;
    _previewJustSeeked = false;
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
    if (_previewStopHandler) {
        segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    // Pause audio — cancelling the RAF above removes the only mechanism that
    // calls segAudioEl.pause() when preview reaches its end, so without this
    // the audio element keeps playing after Apply/Cancel.
    if (!segAudioEl.paused) { segAudioEl.pause(); stopSegAnimation(); }
    // Un-dim rows (O(1) — remove container class + target marker)
    document.body.classList.remove('seg-edit-active');
    editRow?.classList.remove('seg-edit-target');
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
        state[d.getAttribute('data-category')] = { open: d.open };
    });
    return state;
}

function restoreValPanelState(targetEl, state) {
    targetEl.querySelectorAll('details[data-category]').forEach(d => {
        const s = state[d.getAttribute('data-category')];
        if (s && s.open) d.open = true;  // toggle handler renders badges + cards
    });
}

/** Close all accordions except the given one across both validation panels. */
function _collapseAccordionExcept(exceptDetails) {
    // Only collapse within the same panel — avoids cross-panel interference during restore
    const panel = exceptDetails.closest('#seg-validation-global, #seg-validation') || exceptDetails.parentElement;
    panel.querySelectorAll('details[data-category]').forEach(d => {
        if (d === exceptDetails) return;
        if (d.open) d.open = false;  // toggle handler hides badges + clears cards
    });
}

function renderValidationPanel(data, chapter = null, targetEl = segValidationEl, label = null) {
    targetEl.innerHTML = '';
    if (!data) { targetEl.hidden = true; return; }

    let { errors: errs, missing_verses: mv, missing_words: mw, failed, low_confidence, boundary_adj: ba, cross_verse: cv, audio_bleeding: ab, repetitions: rep, muqattaat, qalqala } = data;

    if (chapter !== null) {
        errs           = (errs           || []).filter(i => i.chapter === chapter);
        mv             = (mv             || []).filter(i => i.chapter === chapter);
        mw             = (mw             || []).filter(i => i.chapter === chapter);
        failed         = (failed         || []).filter(i => i.chapter === chapter);
        low_confidence = (low_confidence || []).filter(i => i.chapter === chapter);
        ba             = (ba             || []).filter(i => i.chapter === chapter);
        cv             = (cv             || []).filter(i => i.chapter === chapter);
        ab             = (ab             || []).filter(i => i.chapter === chapter);
        rep            = (rep            || []).filter(i => i.chapter === chapter);
        muqattaat      = (muqattaat      || []).filter(i => i.chapter === chapter);
        qalqala        = (qalqala        || []).filter(i => i.chapter === chapter);
    }
    const hasAny = (errs && errs.length > 0) || (mv && mv.length > 0) || (mw && mw.length > 0)
        || (failed && failed.length > 0) || (low_confidence && low_confidence.length > 0) || (ba && ba.length > 0)
        || (cv && cv.length > 0) || (ab && ab.length > 0) || (rep && rep.length > 0)
        || (muqattaat && muqattaat.length > 0) || (qalqala && qalqala.length > 0);
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
            name: 'Detected Repetitions', items: rep, type: 'repetitions', countClass: 'val-rep-count',
            getLabel: i => i.display_ref || i.ref,
            getTitle: i => i.text,
            btnClass: 'val-rep',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Low Confidence', items: low_confidence, type: 'low_confidence', countClass: 'has-warnings',
            getLabel: i => i.ref,
            getTitle: i => `${(i.confidence * 100).toFixed(1)}%`,
            btnClass: i => i.confidence < 0.60 ? 'val-conf-low' : 'val-conf-mid',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'May Require Boundary Adjustment', items: ba, type: 'boundary_adj', countClass: 'has-warnings',
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
        },
        {
            name: 'Muqatta\u02bcat', items: muqattaat || [], type: 'muqattaat', countClass: 'val-cross-count',
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
        {
            name: 'Qalqala', items: qalqala || [], type: 'qalqala', countClass: 'val-cross-count',
            isQalqala: true,
            getLabel: i => i.ref, getTitle: () => '', btnClass: 'val-cross',
            onClick: i => jumpToSegment(i.chapter, i.seg_index)
        },
    ];

    const QALQALA_LETTERS_ORDER = ['\u0642', '\u0637', '\u0628', '\u062c', '\u062f'];

    categories.forEach(cat => {
        if (!cat.items || cat.items.length === 0) return;

        const isLowConf = cat.type === 'low_confidence';
        const isQalqala = !!cat.isQalqala;
        const LC_DEFAULT = _lcDefaultThreshold;

        // For low_confidence, items shown depend on current slider value.
        // For qalqala, items can be filtered by the active letter button.
        let lcThreshold = LC_DEFAULT;
        let activeQalqalaLetter = null;
        const getVisibleItems = () => {
            if (isLowConf) return cat.items.filter(i => (i.confidence * 100) < lcThreshold).sort((a, b) => a.confidence - b.confidence);
            if (isQalqala && activeQalqalaLetter) return cat.items.filter(i => i.qalqala_letter === activeQalqalaLetter);
            return cat.items;
        };

        const details = document.createElement('details');
        details.setAttribute('data-category', cat.type);
        details._valCatType = cat.type;
        details._valCatItems = cat.items;
        const summary = document.createElement('summary');
        const countForSummary = isLowConf ? cat.items.filter(i => (i.confidence * 100) < LC_DEFAULT).length : cat.items.length;
        summary.innerHTML = `${cat.name} <span class="val-count ${cat.countClass}" data-lc-count>${countForSummary}</span>`;

        details.appendChild(summary);

        // Confidence slider (low_confidence only, shown when open)
        let sliderRow = null;
        if (isLowConf) {
            sliderRow = document.createElement('div');
            sliderRow.className = 'lc-slider-row';
            sliderRow.hidden = true;
            sliderRow.innerHTML = `<label class="lc-slider-label">Show confidence &lt; <span class="lc-slider-val">${LC_DEFAULT}%</span></label><input type="range" class="lc-slider" min="50" max="99" step="1" value="${LC_DEFAULT}">`;
            details.appendChild(sliderRow);
        }

        // Qalqala letter filter (qalqala only, shown when open)
        let qalqalaFilterRow = null;
        if (isQalqala) {
            qalqalaFilterRow = document.createElement('div');
            qalqalaFilterRow.className = 'lc-slider-row qalqala-filter-row';
            qalqalaFilterRow.hidden = true;
            const filterLabel = document.createElement('span');
            filterLabel.className = 'lc-slider-label';
            filterLabel.textContent = 'Filter by letter:';
            qalqalaFilterRow.appendChild(filterLabel);
            QALQALA_LETTERS_ORDER.forEach(letter => {
                if (!cat.items.some(i => i.qalqala_letter === letter)) return;
                const btn = document.createElement('button');
                btn.className = 'val-btn val-cross qalqala-letter-btn';
                btn.textContent = letter;
                btn.title = `Show only segments ending with ${letter}`;
                btn.setAttribute('data-letter', letter);
                btn.addEventListener('click', () => {
                    const countEl = summary.querySelector('[data-lc-count]');
                    if (activeQalqalaLetter === letter) {
                        activeQalqalaLetter = null;
                        btn.classList.remove('active');
                    } else {
                        activeQalqalaLetter = letter;
                        qalqalaFilterRow.querySelectorAll('.qalqala-letter-btn').forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                    }
                    const visible = getVisibleItems();
                    if (countEl) countEl.textContent = visible.length;
                    if (_cardRenderRafId) { cancelAnimationFrame(_cardRenderRafId); _cardRenderRafId = null; }
                    cardsDiv.innerHTML = '';
                    renderCategoryCards(cat.type, visible, cardsDiv);
                    requestAnimationFrame(_updateCtxAllBtn);
                });
                qalqalaFilterRow.appendChild(btn);
            });
            details.appendChild(qalqalaFilterRow);
        }

        // Button list: hidden for qalqala (letter filter replaces it), otherwise hidden until open
        const itemsDiv = document.createElement('div');
        itemsDiv.className = 'val-items';
        itemsDiv.hidden = true;
        if (isQalqala) itemsDiv.style.display = 'none';

        const rebuildButtons = (items) => {
            itemsDiv.innerHTML = '';
            items.forEach(issue => {
                const btn = document.createElement('button');
                const cls = typeof cat.btnClass === 'function' ? cat.btnClass(issue) : cat.btnClass;
                btn.className = `val-btn ${cls}`;
                btn.textContent = cat.getLabel(issue);
                btn.title = cat.getTitle(issue) || '';
                btn.addEventListener('click', () => cat.onClick(issue));
                itemsDiv.appendChild(btn);
            });
        };
        rebuildButtons(getVisibleItems());
        details.appendChild(itemsDiv);

        // Cards container (hidden until accordion opens)
        const cardsDiv = document.createElement('div');
        cardsDiv.className = 'val-cards-container';
        cardsDiv.hidden = true;

        // "Show/Hide All Context" bulk toggle — label reflects whether context is default-shown
        const _ctxDefaultShown = cat.type === 'failed' || cat.type === 'boundary_adj' || cat.type === 'audio_bleeding' || cat.type === 'repetitions' || cat.type === 'qalqala';
        const ctxAllRow = document.createElement('div');
        ctxAllRow.className = 'val-ctx-all-row';
        ctxAllRow.hidden = true;
        const ctxAllBtn = document.createElement('button');
        ctxAllBtn.className = 'val-action-btn val-action-btn-muted';
        ctxAllBtn.textContent = _ctxDefaultShown ? 'Hide All Context' : 'Show All Context';
        ctxAllRow.appendChild(ctxAllBtn);
        details.appendChild(ctxAllRow);

        function _updateCtxAllBtn() {
            const anyShown = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')].some(b => b._isContextShown && b._isContextShown());
            ctxAllBtn.textContent = anyShown ? 'Hide All Context' : 'Show All Context';
        }
        ctxAllBtn.addEventListener('click', () => {
            const allBtns = [...cardsDiv.querySelectorAll('.val-ctx-toggle-btn')];
            const anyShown = allBtns.some(b => b._isContextShown && b._isContextShown());
            allBtns.forEach(b => {
                if (anyShown && b._isContextShown && b._isContextShown()) b.click();
                else if (!anyShown && b._showContext && !b._isContextShown()) b.click();
            });
            _updateCtxAllBtn();
        });

        details.appendChild(cardsDiv);

        if (isLowConf && sliderRow) {
            const sliderEl = sliderRow.querySelector('.lc-slider');
            const sliderValEl = sliderRow.querySelector('.lc-slider-val');
            const countEl = summary.querySelector('[data-lc-count]');
            sliderEl.addEventListener('input', () => {
                lcThreshold = parseInt(sliderEl.value);
                sliderValEl.textContent = `${lcThreshold}%`;
                const visible = getVisibleItems();
                if (countEl) countEl.textContent = visible.length;
                rebuildButtons(visible);
                if (_cardRenderRafId) { cancelAnimationFrame(_cardRenderRafId); _cardRenderRafId = null; }
                cardsDiv.innerHTML = '';
                renderCategoryCards(cat.type, visible, cardsDiv);
            });
        }

        // Opening shows badges + cards; closing hides both and clears cards
        details.addEventListener('toggle', () => {
            if (details.open) {
                _collapseAccordionExcept(details);
                if (sliderRow) sliderRow.hidden = false;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = false;
                if (!isQalqala) itemsDiv.hidden = false;
                const visible = getVisibleItems();
                if (!isQalqala) rebuildButtons(visible);
                renderCategoryCards(cat.type, visible, cardsDiv);
                cardsDiv.hidden = false;
                ctxAllRow.hidden = false;
                // Update label after cards (and default-open contexts) have rendered
                requestAnimationFrame(_updateCtxAllBtn);
            } else {
                if (_cardRenderRafId) { cancelAnimationFrame(_cardRenderRafId); _cardRenderRafId = null; }
                if (sliderRow) sliderRow.hidden = true;
                if (qalqalaFilterRow) qalqalaFilterRow.hidden = true;
                itemsDiv.hidden = true;
                cardsDiv.innerHTML = '';
                cardsDiv.hidden = true;
                ctxAllRow.hidden = true;
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
        // Restore scroll position if returning from save preview
        if (_segSavedPreviewState) {
            const saved = _segSavedPreviewState;
            _segSavedPreviewState = null;
            requestAnimationFrame(() => { segListEl.scrollTop = saved.scrollTop; });
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
    const segAudioUrl = seg.audio_url || segAllData?.audio_by_chapter?.[String(chapter)] || '';

    // For split-chain cards: use parent waveform bounds for display + cursor position
    const splitHL = canvas._splitHL;
    const wfStart = splitHL ? splitHL.wfStart : seg.time_start;
    const wfEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;

    function frame() {
        if (valCardPlayingBtn !== btn) {
            // Stopped — redraw static waveform (parent range + split highlight if applicable)
            // Skip if the canvas has entered split/trim edit mode (avoid wiping the cursor)
            if (canvas && !canvas._splitData && !canvas._trimWindow) {
                const wfSeg = splitHL ? { ...seg, time_start: wfStart, time_end: wfEnd } : seg;
                drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
                if (splitHL) _drawSplitHighlight(canvas, wfSeg);
            }
            valCardAnimId = null;
            valCardAnimSeg = null;
            return;
        }
        // If the canvas has entered split/trim edit mode, stop the playhead animation
        // so it doesn't overwrite the edit cursor.
        if (canvas && (canvas._splitData || canvas._trimWindow)) {
            valCardAnimId = null;
            valCardAnimSeg = null;
            return;
        }
        const timeMs = getValCardAudio().currentTime * 1000;
        // Frame-accurate stop (mirrors the timeupdate listener but at ~16ms resolution)
        if (valCardStopTime !== null && getValCardAudio().currentTime >= valCardStopTime) {
            stopErrorCardAudio();
            return;
        }
        if (!canvas._wfCache) {
            // Snapshot the current canvas (which includes split highlight from IntersectionObserver)
            const cacheKey = `${wfStart}:${wfEnd}`;
            canvas._wfCache = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
            canvas._wfCacheKey = cacheKey;
        }
        drawSegPlayhead(canvas, wfStart, wfEnd, timeMs, segAudioUrl);
        valCardAnimId = requestAnimationFrame(frame);
    }
    valCardAnimId = requestAnimationFrame(frame);
}

function playErrorCardAudio(seg, btn, seekToMs) {
    const audio = getValCardAudio();

    // If already playing this button, stop (unless seeking to a specific position)
    if (valCardPlayingBtn === btn && !audio.paused && seekToMs == null) {
        stopErrorCardAudio();
        return;
    }

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

    const seekSec = seekToMs != null ? seekToMs / 1000 : (seg.time_start || 0) / 1000;
    const endSec = (seg.time_end || 0) / 1000;

    if (audio.src !== audioUrl && audio.getAttribute('data-url') !== audioUrl) {
        audio.src = audioUrl;
        audio.setAttribute('data-url', audioUrl);
        audio.addEventListener('loadedmetadata', function onLoad() {
            audio.removeEventListener('loadedmetadata', onLoad);
            audio.currentTime = seekSec;
            valCardStopTime = endSec;
            audio.playbackRate = parseFloat(segSpeedSelect.value);
            audio.play();
        });
    } else {
        audio.currentTime = seekSec;
        valCardStopTime = endSec;
        audio.playbackRate = parseFloat(segSpeedSelect.value);
        audio.play();
    }

    btn.textContent = '\u23F9';
    valCardPlayingBtn = btn;
    _startValCardAnimation(btn, seg);
}

function invalidateLoadedErrorCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (details.open) details.open = false;  // toggle handler clears cards + hides badges
    });
}

/** Re-render cards for any currently open accordion (preserves open state after structural edits). */
function refreshOpenAccordionCards() {
    document.querySelectorAll('details[data-category]').forEach(details => {
        if (!details.open) return;
        const cardsDiv = details.querySelector('.val-cards-container');
        if (!cardsDiv || !details._valCatItems) return;
        renderCategoryCards(details._valCatType, details._valCatItems, cardsDiv);
    });
}

// ---------------------------------------------------------------------------
// Validation index fixup after structural ops (split/merge/delete)
// ---------------------------------------------------------------------------

const _VAL_SINGLE_INDEX_CATS = ['failed', 'low_confidence', 'boundary_adj', 'cross_verse', 'audio_bleeding', 'repetitions', 'muqattaat', 'qalqala'];

function _forEachValItem(chapter, fn) {
    if (!segValidation) return;
    for (const cat of _VAL_SINGLE_INDEX_CATS) {
        const arr = segValidation[cat];
        if (!arr) continue;
        for (const item of arr) {
            if (item.chapter === chapter) fn(item, 'seg_index');
        }
    }
    const mw = segValidation.missing_words;
    if (mw) {
        for (const item of mw) {
            if (item.chapter !== chapter) continue;
            if (item.seg_indices) {
                for (let i = 0; i < item.seg_indices.length; i++) {
                    const wrapped = { seg_index: item.seg_indices[i] };
                    fn(wrapped, 'seg_index');
                    item.seg_indices[i] = wrapped.seg_index;
                }
            }
            if (item.auto_fix) {
                fn(item.auto_fix, 'target_seg_index');
            }
        }
    }
}

function _fixupValIndicesForSplit(chapter, splitIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] > splitIndex) item[key] += 1;
    });
}

function _fixupValIndicesForMerge(chapter, keptIndex, consumedIndex) {
    const maxIdx = Math.max(keptIndex, consumedIndex);
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === consumedIndex) item[key] = keptIndex;
        else if (item[key] > maxIdx) item[key] -= 1;
    });
}

function _fixupValIndicesForDelete(chapter, deletedIndex) {
    _forEachValItem(chapter, (item, key) => {
        if (item[key] === deletedIndex) item[key] = -1;
        else if (item[key] > deletedIndex) item[key] -= 1;
    });
}

/**
 * Render an error card for a segment — thin wrapper around renderSegCard.
 * @param {object} seg — segment from segAllData.segments
 * @param {object} options — { isContext, contextLabel }
 */
function renderErrorCard(seg, options = {}) {
    const { isContext = false, contextLabel = '', readOnly = false } = options;
    return renderSegCard(seg, {
        showChapter: true,
        showPlayBtn: true,
        showGotoBtn: !isContext && !readOnly,
        isContext,
        contextLabel,
        readOnly,
    });
}

/**
 * Render all error cards for one validation category into a container.
 * @param {string} type — 'errors'|'missing_verses'|'missing_words'|'failed'|'low_confidence'|'cross_verse'
 * @param {Array} items — issues array for this category
 * @param {HTMLElement} container — target container div
 */
function renderCategoryCards(type, items, container) {
    if (_cardRenderRafId) { cancelAnimationFrame(_cardRenderRafId); _cardRenderRafId = null; }
    container.innerHTML = '';
    if (!segAllData || !items || items.length === 0) return;

    const BATCH_SIZE = 30;
    const observer = _ensureWaveformObserver();

    // Kick off peak fetch upfront (cheap URL lookups, non-blocking network)
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

    function renderOneItem(issue) {
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

            // Action buttons row (Auto Fix + Show Context, side by side)
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';

            if (issue.auto_fix) {
                const fixBtn = document.createElement('button');
                fixBtn.className = 'val-action-btn';
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
                    undoBtn.className = 'val-action-btn val-action-btn-danger';
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
                actionsRow.appendChild(fixBtn);
            }

            if (segsInWrapper.length > 0) {
                addContextToggle(actionsRow, segsInWrapper);
            }

            wrapper.appendChild(actionsRow);
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
                const prevCard = renderErrorCard(prev, { contextLabel: 'Previous verse boundary', readOnly: true });
                wrapper.appendChild(prevCard);
                segsInWrapper.push({ seg: prev, card: prevCard });
            }
            if (next && (!prev || next.index !== prev.index)) {
                const nextCard = renderErrorCard(next, { contextLabel: 'Next verse boundary', readOnly: true });
                wrapper.appendChild(nextCard);
                segsInWrapper.push({ seg: next, card: nextCard });
            }

            if (segsInWrapper.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'seg-loading';
                empty.textContent = 'No boundary segments found for this missing verse.';
                wrapper.appendChild(empty);
            } else {
                const actionsRow = document.createElement('div');
                actionsRow.className = 'val-card-actions';
                addContextToggle(actionsRow, segsInWrapper);
                wrapper.appendChild(actionsRow);
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

            // Phoneme tail comparison inside the card's left column
            if (type === 'boundary_adj' && SHOW_BOUNDARY_PHONEMES && (issue.gt_tail || issue.asr_tail)) {
                const textBox = card.querySelector('.seg-text');
                if (textBox) {
                    const tailEl = document.createElement('div');
                    tailEl.className = 'val-phoneme-tail';
                    const gt = issue.gt_tail || '';
                    const asr = issue.asr_tail || '';
                    tailEl.innerHTML =
                        `<span class="val-tail-label">GT:</span> <span class="val-tail-phonemes">${gt}</span>\n` +
                        `<span class="val-tail-label">ASR:</span> <span class="val-tail-phonemes">${asr}</span>`;
                    textBox.appendChild(tailEl);
                }
            }

            // Action buttons row (Ignore + Show Context, side by side)
            const actionsRow = document.createElement('div');
            actionsRow.className = 'val-card-actions';

            if ((type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala') ||
                (type === 'low_confidence' && seg.confidence < 1.0)) {
                const ignoreBtn = document.createElement('button');
                ignoreBtn.className = 'val-action-btn ignore-btn';
                const segChapterForBtn = seg.chapter || parseInt(segChapterSelect.value);
                const isDirtySegment = segDirtyMap.get(segChapterForBtn)?.indices?.has(seg.index);
                if (seg.confidence >= 1.0) {
                    ignoreBtn.disabled = true;
                    ignoreBtn.textContent = 'Ignored';
                    wrapper.style.opacity = '0.5';
                } else if (isDirtySegment) {
                    ignoreBtn.disabled = true;
                    ignoreBtn.textContent = 'Ignore';
                    ignoreBtn.title = 'Cannot ignore — this segment already has unsaved edits';
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
                actionsRow.appendChild(ignoreBtn);
            }

            wrapper.appendChild(actionsRow);
            const contextDefault = type === 'failed' || type === 'boundary_adj' || type === 'audio_bleeding' || type === 'repetitions' || type === 'qalqala';
            const nextOnly = type === 'muqattaat' || type === 'qalqala';
            addContextToggle(actionsRow, [{ seg, card }], { defaultOpen: contextDefault, nextOnly });
            container.appendChild(wrapper);
        }
    }

    function processBatch(startIdx) {
        const end = Math.min(startIdx + BATCH_SIZE, items.length);
        for (let i = startIdx; i < end; i++) renderOneItem(items[i]);
        // Observe canvases added in this batch
        container.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        if (end < items.length) {
            _cardRenderRafId = requestAnimationFrame(() => processBatch(end));
        } else {
            _cardRenderRafId = null;
        }
    }

    processBatch(0);
}

function resolveIssueToSegment(type, issue) {
    if (issue.seg_index != null && issue.seg_index < 0) return null;
    if (type === 'failed' || type === 'low_confidence' || type === 'boundary_adj' || type === 'cross_verse' || type === 'audio_bleeding' || type === 'repetitions' || type === 'muqattaat' || type === 'qalqala') {
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

function addContextToggle(actionsContainer, segsInWrapper, { defaultOpen = false, nextOnly = false } = {}) {
    const ctxBtn = document.createElement('button');
    ctxBtn.className = 'val-action-btn val-action-btn-muted val-ctx-toggle-btn';
    ctxBtn.textContent = 'Show Context';
    let contextShown = false;
    let contextEls = [];

    // Context cards are inserted into the wrapper (parent of cards),
    // not the actionsContainer (which is a row of buttons inside wrapper)
    function showContext() {
        const first = segsInWrapper[0];
        const last = segsInWrapper[segsInWrapper.length - 1];
        const cardParent = first.card.parentNode;

        const { prev } = getAdjacentSegments(first.seg.chapter, first.seg.index);
        const { next } = getAdjacentSegments(last.seg.chapter, last.seg.index);

        if (!nextOnly && prev) {
            const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' });
            cardParent.insertBefore(prevCard, first.card);
            contextEls.push(prevCard);
        }
        if (next) {
            const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' });
            if (last.card.nextSibling) {
                cardParent.insertBefore(nextCard, last.card.nextSibling);
            } else {
                // Insert before the actions row
                cardParent.insertBefore(nextCard, actionsContainer);
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

    // Expose for programmatic access (e.g. ensureContextShown before merge/split)
    ctxBtn._showContext = showContext;
    ctxBtn._isContextShown = () => contextShown;

    ctxBtn.addEventListener('click', () => {
        if (contextShown) hideContext();
        else showContext();
    });

    actionsContainer.appendChild(ctxBtn);

    if (defaultOpen) showContext();
}

/** Auto-show context on an accordion card wrapper if not already visible. */
function ensureContextShown(row) {
    const wrapper = row.closest('.val-card-wrapper');
    if (!wrapper) return;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return;
    for (const btn of actionsRow.children) {
        if (typeof btn._showContext === 'function') {
            if (!btn._isContextShown()) btn._showContext();
            return;
        }
    }
}

/** Check if a val-card-wrapper currently has context cards shown. */
function _isWrapperContextShown(wrapper) {
    if (!wrapper) return false;
    const actionsRow = wrapper.querySelector('.val-card-actions');
    if (!actionsRow) return false;
    for (const btn of actionsRow.children) {
        if (typeof btn._isContextShown === 'function') return btn._isContextShown();
    }
    return false;
}

/**
 * Update an accordion wrapper in-place after a split.
 * Replaces only the split segment's card with firstHalf + secondHalf, preserving
 * all other main cards so cascaded splits accumulate all results. Context cards
 * are refreshed to reflect the updated outermost neighbours.
 */
function _rebuildAccordionAfterSplit(wrapper, chapter, origSeg, firstHalf, secondHalf) {
    const observer = _ensureWaveformObserver();
    const allSegs = segAllData?.segments || segData?.segments || [];

    // --- 1. Remove stale context cards (will re-add below) ---
    wrapper.querySelectorAll('.seg-row-context').forEach(c => c.remove());

    // --- 2. Find and replace the card for origSeg ---
    // Match by uid (set on card via data-seg-uid) or fall back to chapter+index
    const mainCards = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    const splitCard = mainCards.find(c =>
        (origSeg.segment_uid && c.dataset.segUid === origSeg.segment_uid) ||
        (parseInt(c.dataset.segChapter) === (origSeg.chapter || chapter) &&
         parseInt(c.dataset.segIndex) === origSeg.index));

    if (splitCard) {
        const f = renderErrorCard(firstHalf);
        const s = renderErrorCard(secondHalf);
        wrapper.insertBefore(f, splitCard);
        wrapper.insertBefore(s, splitCard);
        splitCard.remove();
        [f, s].forEach(c => c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv)));
    } else {
        // Fallback: append both halves before the actions row if present
        const actionsRow = wrapper.querySelector('.val-card-actions');
        [renderErrorCard(firstHalf), renderErrorCard(secondHalf)].forEach(c => {
            actionsRow ? wrapper.insertBefore(c, actionsRow) : wrapper.appendChild(c);
            c.querySelectorAll('canvas[data-needs-waveform]').forEach(cv => observer.observe(cv));
        });
    }

    // --- 3. Refresh data-seg-index on remaining main cards (indices may have shifted) ---
    wrapper.querySelectorAll('.seg-row:not(.seg-row-context)').forEach(card => {
        const uid = card.dataset.segUid;
        if (!uid) return;
        const updatedSeg = allSegs.find(s => s.segment_uid === uid);
        if (updatedSeg) card.dataset.segIndex = updatedSeg.index;
    });

    // --- 4. Re-add context cards based on updated outermost neighbours ---
    const updatedMain = [...wrapper.querySelectorAll('.seg-row:not(.seg-row-context)')];
    if (updatedMain.length === 0) return;

    const firstMainSeg = resolveSegFromRow(updatedMain[0]);
    const lastMainSeg  = resolveSegFromRow(updatedMain[updatedMain.length - 1]);

    if (firstMainSeg) {
        const { prev } = getAdjacentSegments(firstMainSeg.chapter || chapter, firstMainSeg.index);
        if (prev) {
            const prevCard = renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' });
            wrapper.insertBefore(prevCard, updatedMain[0]);
            prevCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        }
    }
    if (lastMainSeg) {
        const { next } = getAdjacentSegments(lastMainSeg.chapter || chapter, lastMainSeg.index);
        if (next) {
            const actionsRow = wrapper.querySelector('.val-card-actions');
            const nextCard = renderErrorCard(next, { isContext: true, contextLabel: 'Next' });
            actionsRow ? wrapper.insertBefore(nextCard, actionsRow) : wrapper.appendChild(nextCard);
            nextCard.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        }
    }
}

/** Rebuild an accordion wrapper in-place after a merge, showing merged + remaining context. */
function _rebuildAccordionAfterMerge(wrapper, chapter, merged, direction) {
    const { prev, next } = getAdjacentSegments(merged.chapter || chapter, merged.index);

    const issueLabel = wrapper.querySelector('.val-card-issue-label');
    wrapper.innerHTML = '';
    if (issueLabel) wrapper.appendChild(issueLabel);

    // Merged-prev: the old prev context was consumed; show merged + old next context
    // Merged-next: the old next context was consumed; show old prev context + merged
    if (direction === 'prev' && next) {
        wrapper.appendChild(renderErrorCard(merged));
        wrapper.appendChild(renderErrorCard(next, { isContext: true, contextLabel: 'Next' }));
    } else if (direction === 'next' && prev) {
        wrapper.appendChild(renderErrorCard(prev, { isContext: true, contextLabel: 'Previous' }));
        wrapper.appendChild(renderErrorCard(merged));
    } else {
        wrapper.appendChild(renderErrorCard(merged));
    }

    const observer = _ensureWaveformObserver();
    wrapper.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
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
    // Reset filters and sort on view enter
    _histFilterOpTypes.clear();
    _histFilterErrCats.clear();
    _histSortMode = 'time';
    segHistoryFilters.querySelectorAll('.seg-history-filter-pill.active')
        .forEach(p => p.classList.remove('active'));
    segHistorySortTime.classList.add('active');
    segHistoryFilterClear.hidden = true;
    // Observe all waveform canvases + draw arrows
    const observer = _ensureWaveformObserver();
    segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
    requestAnimationFrame(() => {
        segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
    });
}

function hideHistoryView() {
    stopErrorCardAudio();
    _histFilterOpTypes.clear();
    _histFilterErrCats.clear();
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

    // If a batch was undone while in History view, reload all data
    if (_segDataStale) {
        _segDataStale = false;
        onSegReciterChange();
    }
}

// ---------------------------------------------------------------------------
// Edit History — Split Chain Detection
// ---------------------------------------------------------------------------

/**
 * Traces each split-derived segment UID back to its root ancestor's waveform bounds.
 * Returns Map<uid, {wfStart, wfEnd, audioUrl}>.
 */
function _buildSplitLineage(allBatches) {
    const lineage = new Map();
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parent = op.targets_before?.[0];
            if (!parent) continue;
            const parentCtx = (parent.segment_uid && lineage.has(parent.segment_uid))
                ? lineage.get(parent.segment_uid)
                : { wfStart: parent.time_start, wfEnd: parent.time_end, audioUrl: parent.audio_url };
            for (const child of (op.targets_after || [])) {
                if (child.segment_uid) lineage.set(child.segment_uid, parentCtx);
            }
        }
    }
    return lineage;
}

/**
 * Identifies root split ops and absorbs all descendant ops (trim, further splits)
 * into the same chain. Returns { chains: Map<rootOpId, chainData>, chainedOpIds: Set<opId> }.
 * chainData = { rootSnap, rootBatch, ops: [{op, batch}], latestDate }
 */
function _buildSplitChains(allBatches, splitLineage) {
    const chains = new Map();
    const chainedOpIds = new Set();
    const uidToChain = new Map();

    // Pass 1: find root split ops (parent UID is NOT itself a split descendant)
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parentUid = op.targets_before?.[0]?.segment_uid;
            if (parentUid && splitLineage.has(parentUid)) continue; // descendant split — pass 2
            chains.set(op.op_id, {
                rootSnap: op.targets_before?.[0],
                rootBatch: batch,
                ops: [{ op, batch }],
                latestDate: batch.saved_at_utc || '',
            });
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || [])) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id);
            }
        }
    }

    // Pass 2: absorb descendant ops into their chains.
    // Only trim, split, and ref edits are absorbed; merge/delete/ignore stay as independent rows.
    const _CHAIN_ABSORB_OPS = new Set([
        'trim_segment', 'split_segment', 'edit_reference', 'confirm_reference',
    ]);
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (chainedOpIds.has(op.op_id)) continue;
            if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue;
            const beforeUids = (op.targets_before || []).map(s => s.segment_uid).filter(Boolean);
            let chainId = null;
            for (const uid of beforeUids) {
                if (uidToChain.has(uid)) { chainId = uidToChain.get(uid); break; }
            }
            if (!chainId) continue;
            const chain = chains.get(chainId);
            chain.ops.push({ op, batch });
            if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc;
            chainedOpIds.add(op.op_id);
            for (const snap of (op.targets_after || [])) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId);
            }
        }
    }

    return { chains, chainedOpIds };
}

/**
 * Computes the current leaf snapshots for a chain: segments produced by chain ops
 * but never consumed as inputs within the chain. Sorted by time_start.
 */
function _computeChainLeafSnaps(chain) {
    const finalSnaps = new Map();
    const beforeUids = new Set();
    for (const { op } of chain.ops) {
        // Only mark a UID as consumed if it does NOT appear in the same op's
        // targets_after.  In-place ops (trim, ref-edit) keep the same UID in
        // both before and after — those UIDs are preserved, not consumed.
        const afterUids = new Set(
            (op.targets_after || []).map(s => s.segment_uid).filter(Boolean)
        );
        for (const snap of (op.targets_before || [])) {
            if (snap.segment_uid && !afterUids.has(snap.segment_uid)) {
                beforeUids.add(snap.segment_uid);
            }
        }
        for (const snap of (op.targets_after || [])) {
            if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap);
        }
    }
    return [...finalSnaps.entries()]
        .filter(([uid]) => !beforeUids.has(uid))
        .map(([, snap]) => snap)
        .sort((a, b) => a.time_start - b.time_start);
}

/**
 * Renders a split chain as a single history row: 1 before → N after.
 * Each after-card shows the full parent waveform with a green highlight on its slice.
 */
function renderSplitChainRow(chain) {
    const rootSnap = chain.rootSnap;
    const leafSnaps = _computeChainLeafSnaps(chain);
    const chapter = chain.rootBatch?.chapter ?? null;

    const wrapper = document.createElement('div');
    wrapper.className = 'seg-history-batch seg-history-split-chain';

    // Header
    const header = document.createElement('div');
    header.className = 'seg-history-batch-header';

    const time = document.createElement('span');
    time.className = 'seg-history-batch-time';
    time.textContent = _formatHistDate(chain.latestDate);
    header.appendChild(time);

    if (chapter != null) {
        const ch = document.createElement('span');
        ch.className = 'seg-history-batch-chapter';
        ch.textContent = surahOptionText(chapter);
        header.appendChild(ch);
    }

    const badge = document.createElement('span');
    badge.className = 'seg-history-batch-ops-count';
    badge.textContent = `Split \u2192 ${leafSnaps.length}`;
    header.appendChild(badge);

    // Issue delta badges: root snapshot → leaf snapshots (derived from actual data)
    {
        const beforeIssues = new Set();
        if (rootSnap) _classifySnapIssues(rootSnap).forEach(i => beforeIssues.add(i));
        const afterIssues = new Set();
        for (const ls of leafSnaps) _classifySnapIssues(ls).forEach(i => afterIssues.add(i));
        const shortLabels = {
            failed: 'fail', low_confidence: 'low conf', cross_verse: 'cross', repetitions: 'reps',
        };
        for (const cat of [...beforeIssues].filter(i => !afterIssues.has(i))) {
            const b = document.createElement('span');
            b.className = 'seg-history-val-delta improved';
            b.textContent = `\u2212${shortLabels[cat] || cat}`;
            header.appendChild(b);
        }
        for (const cat of [...afterIssues].filter(i => !beforeIssues.has(i))) {
            const b = document.createElement('span');
            b.className = 'seg-history-val-delta regression';
            b.textContent = `+${shortLabels[cat] || cat}`;
            header.appendChild(b);
        }
    }

    // Undo button — undoes the chain's batches in reverse chronological order
    const chainBatchIds = _getChainBatchIds(chain);
    if (chainBatchIds.length > 0) {
        const undoBtn = document.createElement('button');
        undoBtn.className = 'btn btn-sm seg-history-undo-btn';
        undoBtn.textContent = 'Undo';
        undoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onChainUndoClick(chainBatchIds, chapter, undoBtn);
        });
        header.appendChild(undoBtn);
    }

    wrapper.appendChild(header);

    // Body: single diff grid
    const body = document.createElement('div');
    body.className = 'seg-history-batch-body';

    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';

    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';

    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    const arrowSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    arrowSvg.setAttribute('height', '1');
    arrowCol.appendChild(arrowSvg);

    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';

    // Compute waveform window: union of root bounds + all leaf bounds
    // (a leaf may have been trimmed wider than the original parent)
    let wfStart = rootSnap ? rootSnap.time_start : 0;
    let wfEnd   = rootSnap ? rootSnap.time_end   : 0;
    for (const ls of leafSnaps) {
        wfStart = Math.min(wfStart, ls.time_start);
        wfEnd   = Math.max(wfEnd,   ls.time_end);
    }
    const wfExpanded = rootSnap && (wfStart < rootSnap.time_start || wfEnd > rootSnap.time_end);

    // Before card (original segment)
    if (rootSnap) {
        const beforeCard = renderSegCard(_snapToSeg(rootSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
        beforeCol.appendChild(beforeCard);
        // If waveform expanded beyond root bounds, show context highlight on before card too
        if (wfExpanded) {
            const bc = beforeCard.querySelector('canvas');
            if (bc) bc._splitHL = { wfStart, wfEnd, hlStart: rootSnap.time_start, hlEnd: rootSnap.time_end };
        }
    }

    // After cards — set _splitHL on each canvas after creation
    if (leafSnaps.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = '(all segments deleted)';
        afterCol.appendChild(empty);
    } else {
        for (const leafSnap of leafSnaps) {
            const card = renderSegCard(_snapToSeg(leafSnap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
            afterCol.appendChild(card);
            if (rootSnap) {
                const canvas = card.querySelector('canvas');
                if (canvas) {
                    canvas._splitHL = {
                        wfStart,
                        wfEnd,
                        hlStart: leafSnap.time_start,
                        hlEnd:   leafSnap.time_end,
                    };
                }
            }
        }
    }

    diff.append(beforeCol, arrowCol, afterCol);
    body.appendChild(diff);
    wrapper.appendChild(body);
    return wrapper;
}

function renderEditHistoryPanel(data) {
    if (!data || !data.batches || data.batches.length === 0) {
        segHistoryBtn.hidden = true;
        segHistoryFilters.hidden = true;
        return;
    }
    segHistoryBtn.hidden = false;

    // Clear any active filters from previous data
    _histFilterOpTypes.clear();
    _histFilterErrCats.clear();

    // Build split chain index (used by renderHistoryBatches)
    const splitLineage = _buildSplitLineage(data.batches);
    const { chains, chainedOpIds } = _buildSplitChains(data.batches, splitLineage);
    _splitChains = chains;
    _chainedOpIds = chainedOpIds;

    // Ensure peaks are fetched for all chapters referenced in history (they may not
    // have validation errors and thus weren't covered by the initial fetch).
    {
        const reciter = segReciterSelect.value;
        const allHistoryChapters = [...new Set(
            data.batches.flatMap(b => {
                const chs = [];
                if (b.chapter != null) chs.push(b.chapter);
                if (Array.isArray(b.chapters)) chs.push(...b.chapters);
                return chs;
            }).filter(ch => ch != null)
        )];
        if (reciter && allHistoryChapters.length > 0) _fetchPeaks(reciter, allHistoryChapters);
    }

    if (data.summary) {
        data.summary.verses_edited = _countVersesFromBatches(data.batches);
        renderHistorySummaryStats(data.summary);
    }
    renderHistoryFilterBar(data);
    renderHistoryBatches(data.batches);
}

function renderHistorySummaryStats(summary, container = segHistoryStats) {
    container.innerHTML = '';
    if (!summary) return;

    // Stat cards row
    const cardsRow = document.createElement('div');
    cardsRow.className = 'seg-history-stat-cards';
    const stats = [
        { value: summary.total_operations, label: 'Operations' },
        { value: summary.chapters_edited, label: 'Chapters' },
        { value: summary.verses_edited ?? '–', label: 'Verses' },
    ];
    for (const s of stats) {
        const card = document.createElement('div');
        card.className = 'seg-history-stat-card';
        card.innerHTML = `<div class="seg-history-stat-value">${s.value}</div>`
            + `<div class="seg-history-stat-label">${s.label}</div>`;
        cardsRow.appendChild(card);
    }
    container.appendChild(cardsRow);
}

/** Extract unique surah:ayah keys from a matched_ref (handles cross-verse). */
function _versesFromRef(ref) {
    if (!ref) return [];
    const parts = ref.split('-');
    if (parts.length !== 2) return [];
    const sb = parts[0].split(':'), se = parts[1].split(':');
    if (sb.length < 2 || se.length < 2) return [];
    const surah = parseInt(sb[0]), ayahStart = parseInt(sb[1]);
    const surahEnd = parseInt(se[0]), ayahEnd = parseInt(se[1]);
    if (surah !== surahEnd) return [`${surah}:${ayahStart}`, `${surahEnd}:${ayahEnd}`];
    const out = [];
    for (let a = ayahStart; a <= ayahEnd; a++) out.push(`${surah}:${a}`);
    return out;
}

/** Count unique verses touched across all operations in the given batches. */
function _countVersesFromBatches(batches) {
    const verses = new Set();
    for (const batch of batches) {
        for (const op of (batch.operations || [])) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                for (const v of _versesFromRef(snap.matched_ref)) verses.add(v);
            }
        }
    }
    return verses.size;
}

// ---------------------------------------------------------------------------
// History Filters
// ---------------------------------------------------------------------------

/** Does this flattened item match any of the active op-type filters? */
function _itemMatchesOpFilter(item, opTypes) {
    return item.group.some(op => opTypes.has(op.op_type));
}

/** Does this flattened item match any of the active error-category filters? */
function _itemMatchesCatFilter(item, cats) {
    for (const op of item.group) {
        if (op.op_context_category && cats.has(op.op_context_category)) return true;
    }
    const delta = _deriveOpIssueDelta(item.group);
    for (const cat of cats) {
        if (delta.resolved.includes(cat) || delta.introduced.includes(cat)) return true;
    }
    return false;
}

function renderHistoryFilterBar(data) {
    segHistoryFilterOps.innerHTML = '';
    segHistoryFilterCats.innerHTML = '';
    segHistoryFilterClear.hidden = true;

    if (!data.summary && (!data.batches || data.batches.length === 0)) {
        segHistoryFilters.hidden = true;
        return;
    }

    // Flatten batches into items for accurate card-level counts
    const chainedOpIds = _chainedOpIds || new Set();
    const allItems = _flattenBatchesToItems(data.batches, chainedOpIds);

    // Op type pills: count items by primary op type
    const opCounts = {};
    for (const item of allItems) {
        if (item.group.length === 0) continue;
        const primary = item.group[0].op_type;
        opCounts[primary] = (opCounts[primary] || 0) + 1;
    }
    const sortedOps = Object.entries(opCounts).sort((a, b) => b[1] - a[1]);
    for (const [opType, count] of sortedOps) {
        const pill = document.createElement('button');
        pill.className = 'seg-history-filter-pill';
        pill.dataset.filterType = 'op';
        pill.dataset.filterValue = opType;
        pill.innerHTML = `${EDIT_OP_LABELS[opType] || opType} <span class="pill-count">${count}</span>`;
        pill.addEventListener('click', () => toggleHistoryFilter('op', opType, pill));
        segHistoryFilterOps.appendChild(pill);
    }

    // Error category pills: count items that touch each category
    const catCounts = {};
    for (const item of allItems) {
        if (item.group.length === 0) continue;
        const delta = _deriveOpIssueDelta(item.group);
        const touchedCats = new Set([
            ...delta.resolved,
            ...delta.introduced,
            ...item.group.map(op => op.op_context_category).filter(Boolean),
        ]);
        for (const cat of touchedCats) {
            catCounts[cat] = (catCounts[cat] || 0) + 1;
        }
    }
    const sortedCats = Object.entries(catCounts).sort((a, b) => b[1] - a[1]);
    for (const [cat, count] of sortedCats) {
        const pill = document.createElement('button');
        pill.className = 'seg-history-filter-pill';
        pill.dataset.filterType = 'cat';
        pill.dataset.filterValue = cat;
        pill.innerHTML = `${ERROR_CAT_LABELS[cat]} <span class="pill-count">${count}</span>`;
        pill.addEventListener('click', () => toggleHistoryFilter('cat', cat, pill));
        segHistoryFilterCats.appendChild(pill);
    }

    // Always show filter bar (sort is always relevant); hide empty filter rows
    segHistoryFilterOps.parentElement.hidden = (sortedOps.length < 2);
    segHistoryFilterCats.parentElement.hidden = (sortedCats.length < 2);
    segHistoryFilters.hidden = false;
}

function toggleHistoryFilter(type, value, pill) {
    const set = type === 'op' ? _histFilterOpTypes : _histFilterErrCats;
    if (set.has(value)) {
        set.delete(value);
        pill.classList.remove('active');
    } else {
        set.add(value);
        pill.classList.add('active');
    }
    applyHistoryFilters();
}

function applyHistoryFilters() {
    if (!segHistoryData) return;
    const allBatches = segHistoryData.batches;
    const hasFilters = _histFilterOpTypes.size > 0 || _histFilterErrCats.size > 0;

    segHistoryFilterClear.hidden = !hasFilters;

    // Flatten all batches into items, then filter at item level
    const chainedIds = _chainedOpIds || new Set();
    const allItems = _flattenBatchesToItems(allBatches, chainedIds);

    const filtered = hasFilters
        ? allItems.filter(item => {
            if (_histFilterOpTypes.size > 0 && !_itemMatchesOpFilter(item, _histFilterOpTypes)) return false;
            if (_histFilterErrCats.size > 0 && !_itemMatchesCatFilter(item, _histFilterErrCats)) return false;
            return true;
        })
        : allItems;

    // Recompute and render summary stats
    if (hasFilters) {
        renderHistorySummaryStats(_computeFilteredItemSummary(filtered));
    } else {
        renderHistorySummaryStats(segHistoryData.summary);
    }

    // Render filtered items (or empty placeholder)
    if (filtered.length === 0 && hasFilters) {
        segHistoryBatches.innerHTML = '';
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = 'No edits match the active filters.';
        segHistoryBatches.appendChild(empty);
        return;
    }

    _renderHistoryDisplayItems(filtered, allBatches, segHistoryBatches);

    // Redraw waveforms + arrows if history view is visible
    if (!segHistoryView.hidden) {
        const observer = _ensureWaveformObserver();
        segHistoryView.querySelectorAll('canvas[data-needs-waveform]').forEach(c => observer.observe(c));
        requestAnimationFrame(() => {
            segHistoryView.querySelectorAll('.seg-history-diff').forEach(drawHistoryArrows);
        });
    }
}

function _computeFilteredItemSummary(items) {
    const opCounts = {};
    const fixKindCounts = {};
    const chaptersEdited = new Set();
    for (const item of items) {
        if (item.chapter != null) chaptersEdited.add(item.chapter);
        if (Array.isArray(item.chapters)) item.chapters.forEach(ch => chaptersEdited.add(ch));
        for (const op of item.group) {
            opCounts[op.op_type] = (opCounts[op.op_type] || 0) + 1;
            const fk = op.fix_kind || 'unknown';
            fixKindCounts[fk] = (fixKindCounts[fk] || 0) + 1;
        }
    }
    return {
        total_operations: Object.values(opCounts).reduce((s, v) => s + v, 0),
        chapters_edited: chaptersEdited.size,
        verses_edited: _countVersesFromItems(items),
        op_counts: opCounts,
        fix_kind_counts: fixKindCounts,
    };
}

/** Count unique verses touched across all flattened items. */
function _countVersesFromItems(items) {
    const verses = new Set();
    for (const item of items) {
        for (const op of item.group) {
            for (const snap of [...(op.targets_before || []), ...(op.targets_after || [])]) {
                for (const v of _versesFromRef(snap.matched_ref)) verses.add(v);
            }
        }
    }
    return verses.size;
}

function clearHistoryFilters() {
    _histFilterOpTypes.clear();
    _histFilterErrCats.clear();
    segHistoryFilterOps.querySelectorAll('.seg-history-filter-pill.active')
        .forEach(p => p.classList.remove('active'));
    segHistoryFilterCats.querySelectorAll('.seg-history-filter-pill.active')
        .forEach(p => p.classList.remove('active'));
    applyHistoryFilters();
}

function setHistorySort(mode) {
    _histSortMode = mode;
    segHistorySortTime.classList.toggle('active', mode === 'time');
    segHistorySortQuran.classList.toggle('active', mode === 'quran');
    applyHistoryFilters();
}

function renderHistoryBatches(batches, container = segHistoryBatches) {
    const chainedOpIds = _chainedOpIds || new Set();
    const items = _flattenBatchesToItems(batches, chainedOpIds);
    _renderHistoryDisplayItems(items, batches, container);
}

/**
 * Render pre-flattened items + split chain rows into a container.
 * Shared by renderHistoryBatches (full render) and applyHistoryFilters (filtered render).
 */
function _renderHistoryDisplayItems(opItems, batches, container) {
    container.innerHTML = '';
    const displayItems = [];

    // Add split chain rows — only show chains that have at least one op from the
    // batches being rendered (so main history shows all chains, save preview shows
    // only chains touched by pending ops, and filtered views respect the filter).
    if (_splitChains && _histFilterErrCats.size === 0) {
        const showSplitChains = _histFilterOpTypes.size === 0 || _histFilterOpTypes.has('split_segment');
        if (showSplitChains) {
            const batchOpIds = new Set(
                batches.flatMap(b => (b.operations || []).map(op => op.op_id))
            );
            for (const chain of _splitChains.values()) {
                if (chain.ops.some(({ op }) => batchOpIds.has(op.op_id))) {
                    displayItems.push({ type: 'chain', chain, date: chain.latestDate || '' });
                }
            }
        }
    }

    for (const item of opItems) {
        displayItems.push({ type: 'op-item', item, date: item.date });
    }

    if (_histSortMode === 'quran') {
        // Sort by chapter ascending, then segment position, then date descending
        displayItems.sort((a, b) => {
            const aChap = _histItemChapter(a);
            const bChap = _histItemChapter(b);
            if (aChap !== bChap) return aChap - bChap;
            const aPos = _histItemTimeStart(a);
            const bPos = _histItemTimeStart(b);
            if (aPos !== bPos) return aPos - bPos;
            return b.date.localeCompare(a.date);
        });
    } else {
        // Sort most-recent first; chains before op-items at same date; then batchIdx desc, groupIdx asc
        displayItems.sort((a, b) => {
            const cmp = b.date.localeCompare(a.date);
            if (cmp !== 0) return cmp;
            if (a.type === 'chain' && b.type !== 'chain') return -1;
            if (b.type === 'chain' && a.type !== 'chain') return 1;
            const aBIdx = a.item?.batchIdx ?? 0;
            const bBIdx = b.item?.batchIdx ?? 0;
            if (aBIdx !== bBIdx) return bBIdx - aBIdx;
            return (a.item?.groupIdx ?? 0) - (b.item?.groupIdx ?? 0);
        });
    }

    for (const di of displayItems) {
        if (di.type === 'chain') {
            container.appendChild(renderSplitChainRow(di.chain));
        } else {
            container.appendChild(_renderOpCard(di.item));
        }
    }
}

/** Extract effective chapter number from a display item (for Quran-order sort). */
function _histItemChapter(di) {
    if (di.type === 'chain') return di.chain.rootBatch?.chapter ?? Infinity;
    const item = di.item;
    if (item.chapter != null) return item.chapter;
    if (Array.isArray(item.chapters) && item.chapters.length) return Math.min(...item.chapters);
    return Infinity;
}

/** Extract segment time_start from a display item (for within-chapter ordering). */
function _histItemTimeStart(di) {
    if (di.type === 'chain') return di.chain.rootSnap?.time_start ?? Infinity;
    const firstOp = di.item?.group?.[0];
    return firstOp?.targets_before?.[0]?.time_start ?? Infinity;
}

/**
 * Flatten batches into one display item per op-group (or special card type).
 * Each item has: type, group (ops array), chapter, batchId, date, metadata for rendering.
 */
function _flattenBatchesToItems(batches, chainedOpIds) {
    const items = [];
    for (let bIdx = 0; bIdx < batches.length; bIdx++) {
        const batch = batches[bIdx];
        const nonChainOps = (batch.operations || []).filter(op => !chainedOpIds.has(op.op_id));
        const isMultiChapter = batch.chapter == null && Array.isArray(batch.chapters);
        const isStripSpecials = batch.batch_type === 'strip_specials';

        if (isStripSpecials) {
            // One item per ref-group within the strip_specials batch
            const byRef = new Map();
            for (const op of nonChainOps) {
                const ref = op.targets_before?.[0]?.matched_ref || '(unknown)';
                if (!byRef.has(ref)) byRef.set(ref, []);
                byRef.get(ref).push(op);
            }
            let gIdx = 0;
            for (const [, refOps] of byRef) {
                items.push({
                    type: 'strip-specials-card',
                    group: refOps,
                    chapter: batch.chapter,
                    chapters: batch.chapters,
                    batchId: batch.batch_id,
                    date: batch.saved_at_utc || '',
                    isRevert: !!batch.is_revert,
                    isPending: !batch.batch_id && !batch.is_revert,
                    batchIdx: bIdx, groupIdx: gIdx++,
                });
            }
        } else if (isMultiChapter) {
            // One card for the whole multi-chapter batch
            items.push({
                type: 'multi-chapter-card',
                group: nonChainOps,
                chapter: batch.chapter,
                chapters: batch.chapters,
                batchId: batch.batch_id,
                date: batch.saved_at_utc || '',
                isRevert: !!batch.is_revert,
                isPending: !batch.batch_id && !batch.is_revert,
                batchIdx: bIdx, groupIdx: 0,
            });
        } else if (batch.is_revert && nonChainOps.length === 0) {
            // Pure revert with no remaining ops
            items.push({
                type: 'revert-card',
                group: [],
                chapter: batch.chapter,
                chapters: batch.chapters,
                batchId: batch.batch_id,
                date: batch.saved_at_utc || '',
                isRevert: true,
                isPending: false,
                batchIdx: bIdx, groupIdx: 0,
            });
        } else {
            // Normal batch: one item per op-group
            const groups = _groupRelatedOps(nonChainOps);
            for (let gIdx = 0; gIdx < groups.length; gIdx++) {
                items.push({
                    type: 'op-card',
                    group: groups[gIdx],
                    chapter: batch.chapter,
                    chapters: batch.chapters,
                    batchId: batch.batch_id,
                    date: batch.saved_at_utc || '',
                    isRevert: !!batch.is_revert,
                    isPending: !batch.batch_id && !batch.is_revert,
                    batchIdx: bIdx, groupIdx: gIdx,
                });
            }
            // If batch had ops but all were chained away, and it's not a revert, skip
        }
    }
    return items;
}

/** Append resolved/introduced issue badges to a header element. */
function _appendIssueDeltaBadges(container, group) {
    const delta = _deriveOpIssueDelta(group);
    const shortLabels = {
        failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary',
        cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
        repetitions: 'reps',
    };
    for (const cat of delta.resolved) {
        const badge = document.createElement('span');
        badge.className = 'seg-history-val-delta improved';
        badge.textContent = `\u2212${shortLabels[cat] || cat}`;
        container.appendChild(badge);
    }
    for (const cat of delta.introduced) {
        const badge = document.createElement('span');
        badge.className = 'seg-history-val-delta regression';
        badge.textContent = `+${shortLabels[cat] || cat}`;
        container.appendChild(badge);
    }
}

/**
 * Render a single flattened display item as a top-level card.
 * Replaces the old _renderBatchItem — each op-group is now its own card.
 */
function _renderOpCard(item) {
    const wrapper = document.createElement('div');
    wrapper.className = 'seg-history-batch' + (item.isRevert ? ' is-revert' : '');

    // Header
    const header = document.createElement('div');
    header.className = 'seg-history-batch-header';

    // Op type badge(s) — primary + follow-ups
    const group = item.group;
    if (item.type === 'strip-specials-card') {
        const badge = document.createElement('span');
        badge.className = 'seg-history-op-type-badge';
        badge.textContent = `Deletion \u00d7${group.length}`;
        header.appendChild(badge);
    } else if (item.type === 'multi-chapter-card') {
        const opType = group[0]?.op_type;
        const badge = document.createElement('span');
        badge.className = 'seg-history-op-type-badge';
        badge.textContent = `${EDIT_OP_LABELS[opType] || opType} \u00d7${group.length}`;
        header.appendChild(badge);
    } else if (item.type === 'revert-card') {
        // No op badge needed — revert badge below covers it
    } else if (group.length > 0) {
        // op-card: primary badge
        const primary = group[0];
        const typeBadge = document.createElement('span');
        typeBadge.className = 'seg-history-op-type-badge';
        typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type;
        header.appendChild(typeBadge);

        // Follow-up badges
        const followUp = {};
        for (let i = 1; i < group.length; i++) {
            const t = group[i].op_type;
            followUp[t] = (followUp[t] || 0) + 1;
        }
        for (const [t, count] of Object.entries(followUp)) {
            const fb = document.createElement('span');
            fb.className = 'seg-history-op-type-badge secondary';
            fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` \u00d7${count}` : '');
            header.appendChild(fb);
        }
    }

    // Fix kind badges
    const fixKinds = new Set(group.map(op => op.fix_kind).filter(fk => fk && fk !== 'manual'));
    if (item.type === 'strip-specials-card' || item.type === 'multi-chapter-card') fixKinds.add('auto_fix');
    for (const fk of fixKinds) {
        const fkBadge = document.createElement('span');
        fkBadge.className = 'seg-history-op-fix-kind';
        fkBadge.textContent = fk;
        header.appendChild(fkBadge);
    }

    // Issue delta badges (derived from snapshots)
    if (group.length > 0) {
        _appendIssueDeltaBadges(header, group);
    }

    // Revert badge
    if (item.isRevert) {
        const badge = document.createElement('span');
        badge.className = 'seg-history-batch-revert-badge';
        badge.textContent = 'Reverted';
        header.appendChild(badge);
    }

    // Chapter badge
    const ch = item.chapter;
    if (ch != null) {
        const chSpan = document.createElement('span');
        chSpan.className = 'seg-history-batch-chapter';
        chSpan.textContent = surahOptionText(ch);
        header.appendChild(chSpan);
    }

    // Date
    const time = document.createElement('span');
    time.className = 'seg-history-batch-time';
    time.textContent = _formatHistDate(item.date || null);
    header.appendChild(time);

    // Undo / Discard button (margin-left:auto pushes it right)
    if (item.isPending) {
        const discardBtn = document.createElement('button');
        discardBtn.className = 'btn btn-sm seg-history-undo-btn';
        discardBtn.textContent = 'Discard';
        discardBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onPendingBatchDiscard(item.chapter, discardBtn);
        });
        header.appendChild(discardBtn);
    } else if (item.batchId && !item.isRevert) {
        const opIds = group.map(op => op.op_id);
        const undoBtn = document.createElement('button');
        undoBtn.className = 'btn btn-sm seg-history-undo-btn';
        undoBtn.textContent = 'Undo';
        undoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onOpUndoClick(item.batchId, opIds, undoBtn);
        });
        header.appendChild(undoBtn);
    }

    wrapper.appendChild(header);

    // Body — type-specific
    if (group.length > 0 || item.type === 'multi-chapter-card') {
        const body = document.createElement('div');
        body.className = 'seg-history-batch-body';

        if (item.type === 'strip-specials-card') {
            body.appendChild(_renderSpecialDeleteGroup(group));
        } else if (item.type === 'multi-chapter-card') {
            const chList = document.createElement('div');
            chList.className = 'seg-history-chapter-list';
            chList.textContent = 'Chapters: ' + (item.chapters || []).map(c => surahOptionText(c)).join(', ');
            body.appendChild(chList);
        } else if (group.length === 1) {
            body.appendChild(renderHistoryOp(group[0], item.chapter, item.batchId, { skipLabel: true }));
        } else {
            body.appendChild(renderHistoryGroupedOp(group, item.chapter, item.batchId, { skipLabel: true }));
        }

        wrapper.appendChild(body);
    }

    return wrapper;
}

/**
 * Render a collapsed "before → deleted" card for a group of same-ref special deletions.
 * Shows one representative card with "×N deleted" in the after column.
 */
function _renderSpecialDeleteGroup(refOps) {
    const count = refOps.length;
    const snap = refOps[0].targets_before?.[0];

    const diffEl = document.createElement('div');
    diffEl.className = 'seg-history-diff';

    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';
    if (snap) {
        beforeCol.appendChild(renderSegCard(_snapToSeg(snap, null), { readOnly: true, showPlayBtn: true }));
    }

    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';
    const emptyEl = document.createElement('div');
    emptyEl.className = 'seg-history-empty';
    emptyEl.textContent = count > 1 ? `\u00d7${count} deleted` : '(deleted)';
    afterCol.appendChild(emptyEl);

    diffEl.appendChild(beforeCol);
    diffEl.appendChild(afterCol);
    return diffEl;
}

/**
 * Group related operations within a batch so they render as one card.
 * E.g. split → edit first half ref → edit second half ref  ⇒  single group.
 * Returns array of groups, each group is an array of ops.
 */
function _groupRelatedOps(operations) {
    if (!operations || operations.length === 0) return [];
    if (operations.length === 1) return [[operations[0]]];

    const groups = [];
    const opGroupIdx = new Map(); // op array index → group index
    const uidToGroup = new Map(); // segment_uid → group index (which group produced it)

    for (let i = 0; i < operations.length; i++) {
        const op = operations[i];
        const beforeUids = (op.targets_before || []).map(t => t.segment_uid).filter(Boolean);

        // Check if any before-UID was produced by a previous op in this batch
        let parentGroup = null;
        for (const uid of beforeUids) {
            if (uidToGroup.has(uid)) {
                parentGroup = uidToGroup.get(uid);
                break;
            }
        }

        if (parentGroup !== null) {
            groups[parentGroup].push(op);
            opGroupIdx.set(i, parentGroup);
        } else {
            const gIdx = groups.length;
            groups.push([op]);
            opGroupIdx.set(i, gIdx);
        }

        // Register this op's output UIDs
        const gIdx = opGroupIdx.get(i);
        for (const snap of (op.targets_after || [])) {
            if (snap.segment_uid) uidToGroup.set(snap.segment_uid, gIdx);
        }
    }

    return groups;
}

/**
 * Render a group of related ops as a single combined card.
 * Shows the original before (from first op) → final after (latest snapshot per UID).
 */
function renderHistoryGroupedOp(group, chapter, batchId, { skipLabel = false } = {}) {
    const primary = group[0];

    // Collect final snapshot for each output UID (last write wins)
    const finalSnaps = new Map();
    for (const op of group) {
        for (const snap of (op.targets_after || [])) {
            if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap);
        }
    }

    // Before = primary op's targets_before
    const before = primary.targets_before || [];

    // After = final states, ordered by primary's targets_after UIDs
    const primaryAfterUids = (primary.targets_after || []).map(t => t.segment_uid);
    const after = primaryAfterUids.map(uid => finalSnaps.get(uid)).filter(Boolean);

    const wrap = document.createElement('div');
    wrap.className = 'seg-history-op seg-history-grouped-op';

    if (!skipLabel) {
    // --- Label row: primary badge + follow-up badges ---
    const label = document.createElement('div');
    label.className = 'seg-history-op-label';

    const typeBadge = document.createElement('span');
    typeBadge.className = 'seg-history-op-type-badge';
    typeBadge.textContent = EDIT_OP_LABELS[primary.op_type] || primary.op_type;
    label.appendChild(typeBadge);

    // Follow-up op type badges (smaller)
    const followUp = {};
    for (let i = 1; i < group.length; i++) {
        const t = group[i].op_type;
        followUp[t] = (followUp[t] || 0) + 1;
    }
    for (const [t, count] of Object.entries(followUp)) {
        const fb = document.createElement('span');
        fb.className = 'seg-history-op-type-badge secondary';
        fb.textContent = '+ ' + (EDIT_OP_LABELS[t] || t) + (count > 1 ? ` x${count}` : '');
        label.appendChild(fb);
    }

    const fixKinds = new Set(group.map(op => op.fix_kind).filter(fk => fk && fk !== 'manual'));
    for (const fk of fixKinds) {
        const fkBadge = document.createElement('span');
        fkBadge.className = 'seg-history-op-fix-kind';
        fkBadge.textContent = fk;
        label.appendChild(fkBadge);
    }
    if (batchId) {
        const groupOpIds = group.map(op => op.op_id);
        const undoBtn = document.createElement('button');
        undoBtn.className = 'btn btn-sm seg-history-op-undo-btn';
        undoBtn.textContent = 'Undo';
        undoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onOpUndoClick(batchId, groupOpIds, undoBtn);
        });
        label.appendChild(undoBtn);
    }
    wrap.appendChild(label);
    }

    // --- 3-column diff grid ---
    const diff = document.createElement('div');
    diff.className = 'seg-history-diff';

    const beforeCol = document.createElement('div');
    beforeCol.className = 'seg-history-before';
    const arrowCol = document.createElement('div');
    arrowCol.className = 'seg-history-arrows';
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('height', '1');
    arrowCol.appendChild(svg);
    const afterCol = document.createElement('div');
    afterCol.className = 'seg-history-after';

    const beforeCards = [];
    for (const snap of before) {
        const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
        beforeCol.appendChild(card);
        beforeCards.push(card);
    }

    const afterCards = [];
    if (after.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'seg-history-empty';
        empty.textContent = '(deleted)';
        afterCol.appendChild(empty);
    } else {
        for (const snap of after) {
            const card = renderSegCard(_snapToSeg(snap, chapter), { readOnly: true, showChapter: true, showPlayBtn: true });
            afterCol.appendChild(card);
            afterCards.push(card);
        }
    }

    // Change highlighting for 1→1 groups (e.g. trim then ref edit)
    if (before.length === 1 && after.length === 1) {
        _highlightChanges(before[0], after[0], beforeCards[0], afterCards[0]);
    }

    // Merge highlight: annotate after-card canvas with absorbed segment's range
    if ((primary.op_type === 'merge_segments' || primary.op_type === 'waqf_sakt')
            && before.length === 2 && afterCards.length === 1) {
        const afterCanvas = afterCards[0].querySelector('canvas');
        if (afterCanvas && primary.merge_direction) {
            const hlSnap = primary.merge_direction === 'prev' ? before[1] : before[0];
            afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end };
        }
    }

    diff.append(beforeCol, arrowCol, afterCol);
    wrap.appendChild(diff);
    return wrap;
}

function renderHistoryOp(op, chapter, batchId, { skipLabel = false } = {}) {
    const wrap = document.createElement('div');
    wrap.className = 'seg-history-op';

    if (!skipLabel) {
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
    if (batchId) {
        const undoBtn = document.createElement('button');
        undoBtn.className = 'btn btn-sm seg-history-op-undo-btn';
        undoBtn.textContent = 'Undo';
        undoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            onOpUndoClick(batchId, [op.op_id], undoBtn);
        });
        label.appendChild(undoBtn);
    }
    wrap.appendChild(label);
    }

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

    // Merge highlight: annotate after-card canvas with absorbed segment's range
    if ((op.op_type === 'merge_segments' || op.op_type === 'waqf_sakt')
            && before.length === 2 && afterCards.length === 1) {
        const afterCanvas = afterCards[0].querySelector('canvas');
        if (afterCanvas && op.merge_direction) {
            const hlSnap = op.merge_direction === 'prev' ? before[1] : before[0];
            afterCanvas._mergeHL = { hlStart: hlSnap.time_start, hlEnd: hlSnap.time_end };
        }
    }

    diff.append(beforeCol, arrowCol, afterCol);
    wrap.appendChild(diff);
    return wrap;
}

function _snapToSeg(snap, chapter) {
    const seg = {
        index: snap.index_at_save,
        chapter: chapter,
        audio_url: snap.audio_url || '',
        time_start: snap.time_start,
        time_end: snap.time_end,
        matched_ref: snap.matched_ref || '',
        matched_text: snap.matched_text || '',
        display_text: snap.display_text || '',
        confidence: snap.confidence ?? 0,
    };
    if (snap.wrap_word_ranges) seg.wrap_word_ranges = snap.wrap_word_ranges;
    if (snap.has_repeated_words) seg.has_repeated_words = true;
    return seg;
}

function _highlightChanges(beforeSnap, afterSnap, beforeCard, afterCard) {
    // Compare fields and add .seg-history-changed to after card elements
    if (beforeSnap.matched_ref !== afterSnap.matched_ref) {
        const el = afterCard.querySelector('.seg-text-ref');
        if (el) el.classList.add('seg-history-changed');
    }
    if (beforeSnap.time_start !== afterSnap.time_start || beforeSnap.time_end !== afterSnap.time_end) {
        const el = afterCard.querySelector('.seg-text-duration');
        if (el) el.classList.add('seg-history-changed');
        // Store trim highlight data on canvases for waveform overlay
        const bCanvas = beforeCard.querySelector('canvas');
        const aCanvas = afterCard.querySelector('canvas');
        if (bCanvas) bCanvas._trimHL = { color: 'red', otherStart: afterSnap.time_start, otherEnd: afterSnap.time_end };
        if (aCanvas) aCanvas._trimHL = { color: 'green', otherStart: beforeSnap.time_start, otherEnd: beforeSnap.time_end };
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

/** Draw red/green overlay on history card waveforms to show trim changes. */
function _drawTrimHighlight(canvas, seg) {
    const hl = canvas._trimHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const dur = seg.time_end - seg.time_start;
    if (dur <= 0) return;

    const rgba = hl.color === 'red' ? 'rgba(244, 67, 54, 0.3)' : 'rgba(76, 175, 80, 0.3)';
    ctx.fillStyle = rgba;

    if (hl.color === 'red') {
        // Before card: highlight regions that were removed (present in before, absent in after)
        if (seg.time_start < hl.otherStart) {
            const x2 = ((hl.otherStart - seg.time_start) / dur) * w;
            ctx.fillRect(0, 0, x2, h);
        }
        if (seg.time_end > hl.otherEnd) {
            const x1 = ((hl.otherEnd - seg.time_start) / dur) * w;
            ctx.fillRect(x1, 0, w - x1, h);
        }
    } else {
        // After card: highlight regions that were added (present in after, absent in before)
        if (seg.time_start < hl.otherStart) {
            const x2 = ((hl.otherStart - seg.time_start) / dur) * w;
            ctx.fillRect(0, 0, x2, h);
        }
        if (seg.time_end > hl.otherEnd) {
            const x1 = ((hl.otherEnd - seg.time_start) / dur) * w;
            ctx.fillRect(x1, 0, w - x1, h);
        }
    }
}

/** Draw dim + green overlay on split chain after-card waveforms. */
function _drawSplitHighlight(canvas, wfSeg) {
    const hl = canvas._splitHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const dur = wfSeg.time_end - wfSeg.time_start;
    if (dur <= 0) return;
    const toX = ms => Math.max(0, Math.min(w, ((ms - wfSeg.time_start) / dur) * w));

    const x1 = toX(hl.hlStart);
    const x2 = toX(hl.hlEnd);

    // Dim the parts of the waveform outside this leaf's range
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    if (x1 > 0) ctx.fillRect(0, 0, x1, h);
    if (x2 < w) ctx.fillRect(x2, 0, w - x2, h);

    // Green highlight on this leaf's range
    ctx.fillStyle = 'rgba(76, 175, 80, 0.3)';
    if (x2 > x1) ctx.fillRect(x1, 0, x2 - x1, h);
}

/** Draw dim + green overlay on merge result card showing the absorbed segment's range. */
function _drawMergeHighlight(canvas, seg) {
    const hl = canvas._mergeHL;
    if (!hl) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    const dur = seg.time_end - seg.time_start;
    if (dur <= 0) return;
    const toX = ms => Math.max(0, Math.min(w, ((ms - seg.time_start) / dur) * w));

    const x1 = toX(hl.hlStart);
    const x2 = toX(hl.hlEnd);

    // Dim the base portion (outside the absorbed segment's range)
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    if (x1 > 0) ctx.fillRect(0, 0, x1, h);
    if (x2 < w) ctx.fillRect(x2, 0, w - x2, h);

    // Green highlight on the absorbed segment's range
    ctx.fillStyle = 'rgba(76, 175, 80, 0.3)';
    if (x2 > x1) ctx.fillRect(x1, 0, x2 - x1, h);
}

function _appendValDeltas(container, before, after) {
    if (!before || !after) return;
    const cats = _validationCategories || Object.keys(ERROR_CAT_LABELS);
    const shortLabels = {
        failed: 'fail', low_confidence: 'low conf', boundary_adj: 'boundary',
        cross_verse: 'cross', missing_words: 'gaps', audio_bleeding: 'bleed',
        repetitions: 'reps', muqattaat: 'muqattaat', qalqala: 'qalqala',
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
    if (!isoStr) return 'Pending';
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
