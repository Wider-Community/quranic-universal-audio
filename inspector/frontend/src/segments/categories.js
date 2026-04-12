/**
 * Per-segment category classification -- mirrors server-side validation logic.
 * Pure functions that read from state but don't mutate it.
 */

import { state, _MN_RE, _STRIP_CHARS, _LETTER_RE } from './state.js';

// ---------------------------------------------------------------------------
// Text helpers
// ---------------------------------------------------------------------------

export function _stripQuranDeco(text) {
    const nfd = text.normalize('NFD');
    let out = '';
    for (const ch of nfd) {
        if (_STRIP_CHARS.has(ch)) continue;
        if (_MN_RE.test(ch)) continue;
        out += ch;
    }
    return out.trim();
}

export function _lastArabicLetter(text) {
    const stripped = _stripQuranDeco(text);
    for (let i = stripped.length - 1; i >= 0; i--) {
        if (_LETTER_RE.test(stripped[i])) return stripped[i];
    }
    return null;
}

export function _isStandaloneWord(text) {
    if (!state._standaloneWords) return false;
    return state._standaloneWords.has(_stripQuranDeco(text));
}

/** Check if a segment is ignored for a specific validation category. */
export function _isIgnoredFor(seg, category) {
    const ic = seg.ignored_categories;
    if (ic) return ic.includes('_all') || ic.includes(category);
    return !!seg.ignored;  // back-compat for old boolean
}

// ---------------------------------------------------------------------------
// Per-segment classification
// ---------------------------------------------------------------------------

/**
 * Classify a segment into ALL applicable validation categories.
 * Returns an array of category strings. Works on live segments and snapshots.
 */
export function _classifySegCategories(seg) {
    const cats = [];
    const ref = seg.matched_ref || '';
    const confidence = seg.confidence ?? 0;

    if (!ref) { cats.push('failed'); return cats; }

    if (confidence < 0.80) cats.push('low_confidence');
    if (seg.wrap_word_ranges || seg.has_repeated_words) cats.push('repetitions');

    // Parse canonical ref: "surah:ayah:word-surah:ayah:word"
    const parts = ref.split('-');
    if (parts.length !== 2) return cats;
    const sp = parts[0].split(':'), ep = parts[1].split(':');
    if (sp.length !== 3 || ep.length !== 3) return cats;
    const surah = +sp[0], sAyah = +sp[1], sWord = +sp[2];
    const eAyah = +ep[1], eWord = +ep[2];

    // Cross-verse
    if (sAyah !== eAyah && !_isIgnoredFor(seg, 'cross_verse')) {
        cats.push('cross_verse');
    }

    // Boundary adjustment: 1-word, not muqattaat, not single-word verse, not standalone
    const vwc = state.segAllData?.verse_word_counts;
    if (sWord === eWord && sAyah === eAyah && !_isIgnoredFor(seg, 'boundary_adj')
        && !state._muqattaatVerses?.has(`${surah}:${sAyah}`)
        && !(vwc && vwc[`${surah}:${sAyah}`] === 1)
        && !state._standaloneRefs?.has(`${surah}:${sAyah}:${sWord}`)
        && !_isStandaloneWord(seg.matched_text || '')) {
        cats.push('boundary_adj');
    }

    // Muqattaat
    if (sWord === 1 && state._muqattaatVerses?.has(`${surah}:${sAyah}`) && !_isIgnoredFor(seg, 'muqattaat')) {
        cats.push('muqattaat');
    }

    // Qalqala
    if (!_isIgnoredFor(seg, 'qalqala')) {
        const last = _lastArabicLetter(seg.matched_text || '');
        if (last && state._qalqalaLetters?.has(last)) cats.push('qalqala');
    }

    // Audio bleeding (by_ayah only)
    if (seg.entry_ref && seg.audio_url && state.segAllData?.audio_by_chapter) {
        const chapterAudio = state.segAllData.audio_by_chapter[String(seg.chapter)];
        if (chapterAudio && seg.audio_url !== chapterAudio) {
            const entryParts = seg.entry_ref.split(':');
            if (entryParts.length >= 2) {
                const segVerse = `${sp[0]}:${sp[1]}`;
                const entryVerse = `${entryParts[0]}:${entryParts[1]}`;
                if (segVerse !== entryVerse) cats.push('audio_bleeding');
            }
        }
    }

    return cats;
}

// ---------------------------------------------------------------------------
// Snapshot classification (for edit history)
// ---------------------------------------------------------------------------

/**
 * Classify a segment snapshot into validation issue categories.
 * Uses pre-computed categories when available, falls back to basic detection.
 */
export function _classifySnapIssues(snap) {
    if (snap?.categories) return [...snap.categories];
    const issues = [];
    if (!snap || !snap.matched_ref) { if (snap) issues.push('failed'); return issues; }
    if (snap.confidence < 0.80) issues.push('low_confidence');
    if (snap.wrap_word_ranges || snap.has_repeated_words) issues.push('repetitions');
    const parts = snap.matched_ref.split('-');
    if (parts.length === 2) {
        const sp = parts[0].split(':'), ep = parts[1].split(':');
        if (sp.length >= 2 && ep.length >= 2) {
            if (parseInt(sp[1]) !== parseInt(ep[1])) issues.push('cross_verse');
        }
    }
    return issues;
}

/**
 * Derive per-op-group issue delta from snapshot data.
 */
export function _deriveOpIssueDelta(group) {
    if (!group || group.length === 0) return { resolved: [], introduced: [] };
    const primary = group[0];

    const beforeIssues = new Set();
    for (const snap of (primary.targets_before || []))
        _classifySnapIssues(snap).forEach(i => beforeIssues.add(i));

    const finalSnaps = new Map();
    let hasAnyAfterUid = false;
    for (const op of group) {
        for (const snap of (op.targets_after || [])) {
            if (snap.segment_uid) { finalSnaps.set(snap.segment_uid, snap); hasAnyAfterUid = true; }
        }
    }

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
