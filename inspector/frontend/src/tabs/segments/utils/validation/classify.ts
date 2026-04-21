import { get } from 'svelte/store';

import type { EditOp, Segment } from '../../../../lib/types/domain';
import { segAllData } from '../../stores/chapter';
import { segConfig } from '../../stores/config';
import { _LETTER_RE, _MN_RE, _STRIP_CHARS, CONF_HIGH_THRESHOLD } from '../constants';

// A segment-like record that `_classifySegCategories` / `_isIgnoredFor` can
// read. Live segments satisfy `Segment`; history snapshots (opaque
// `SegSnapshot` records) also satisfy this loose shape.
interface SegClassifyInput {
    matched_ref?: string;
    matched_text?: string;
    display_text?: string;
    confidence?: number;
    audio_url?: string;
    entry_ref?: string;
    chapter?: number;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    ignored_categories?: string[];
    /** Back-compat: legacy boolean from pre-categories ignore flag. */
    ignored?: boolean;
}

// ---------------------------------------------------------------------------
// Text helpers
// ---------------------------------------------------------------------------

export function _stripQuranDeco(text: string): string {
    const nfd = text.normalize('NFD');
    let out = '';
    for (const ch of nfd) {
        if (_STRIP_CHARS.has(ch)) continue;
        if (_MN_RE.test(ch)) continue;
        out += ch;
    }
    return out.trim();
}

export function _lastArabicLetter(text: string): string | null {
    const stripped = _stripQuranDeco(text);
    for (let i = stripped.length - 1; i >= 0; i--) {
        const ch = stripped[i];
        if (ch != null && _LETTER_RE.test(ch)) return ch;
    }
    return null;
}

export function _isStandaloneWord(text: string): boolean {
    const cfg = get(segConfig);
    if (!cfg.standaloneWords) return false;
    return cfg.standaloneWords.has(_stripQuranDeco(text));
}

/** Check if a segment is ignored for a specific validation category. */
export function _isIgnoredFor(seg: SegClassifyInput, category: string): boolean {
    const ic = seg.ignored_categories;
    if (ic) return ic.includes('_all') || ic.includes(category);
    return !!seg.ignored; // back-compat for old boolean
}

// ---------------------------------------------------------------------------
// Per-segment classification
// ---------------------------------------------------------------------------

/**
 * Classify a segment into ALL applicable validation categories.
 * Returns an array of category strings. Works on live segments and snapshots.
 */
export function _classifySegCategories(seg: Segment | SegClassifyInput): string[] {
    const cats: string[] = [];
    const ref = seg.matched_ref || '';
    const confidence = seg.confidence ?? 0;

    if (!ref) { cats.push('failed'); return cats; }

    if (confidence < CONF_HIGH_THRESHOLD) cats.push('low_confidence');
    if (seg.wrap_word_ranges || seg.has_repeated_words) cats.push('repetitions');

    const parts = ref.split('-');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return cats;
    const sp = parts[0].split(':'), ep = parts[1].split(':');
    if (sp.length !== 3 || ep.length !== 3) return cats;
    if (sp[0] == null || sp[1] == null || sp[2] == null || ep[1] == null || ep[2] == null) return cats;
    const surah = +sp[0], sAyah = +sp[1], sWord = +sp[2];
    const eAyah = +ep[1], eWord = +ep[2];

    const cfg = get(segConfig);
    const all = get(segAllData);

    // Cross-verse
    if (sAyah !== eAyah && !_isIgnoredFor(seg, 'cross_verse')) {
        cats.push('cross_verse');
    }

    // Boundary adjustment: 1-word, not muqattaat, not single-word verse, not standalone
    const vwc = all?.verse_word_counts;
    if (sWord === eWord && sAyah === eAyah && !_isIgnoredFor(seg, 'boundary_adj')
        && !cfg.muqattaatVerses?.has(`${surah}:${sAyah}`)
        && !(vwc && vwc[`${surah}:${sAyah}`] === 1)
        && !cfg.standaloneRefs?.has(`${surah}:${sAyah}:${sWord}`)
        && !_isStandaloneWord(seg.matched_text || '')) {
        cats.push('boundary_adj');
    }

    // Muqattaat
    if (sWord === 1 && cfg.muqattaatVerses?.has(`${surah}:${sAyah}`) && !_isIgnoredFor(seg, 'muqattaat')) {
        cats.push('muqattaat');
    }

    // Qalqala
    if (!_isIgnoredFor(seg, 'qalqala')) {
        const last = _lastArabicLetter(seg.matched_text || '');
        if (last && cfg.qalqalaLetters?.has(last)) cats.push('qalqala');
    }

    // Audio bleeding (by_ayah only)
    if (seg.entry_ref && seg.audio_url && all?.audio_by_chapter) {
        const chapterAudio = all.audio_by_chapter[String(seg.chapter)];
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

interface SnapForIssues {
    matched_ref?: string;
    confidence?: number;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    categories?: string[];
    segment_uid?: string | null;
}

export function _classifySnapIssues(snap: SnapForIssues | null | undefined): string[] {
    if (snap?.categories) return [...snap.categories];
    const issues: string[] = [];
    if (!snap || !snap.matched_ref) { if (snap) issues.push('failed'); return issues; }
    if ((snap.confidence ?? 0) < CONF_HIGH_THRESHOLD) issues.push('low_confidence');
    if (snap.wrap_word_ranges || snap.has_repeated_words) issues.push('repetitions');
    const parts = snap.matched_ref.split('-');
    if (parts.length === 2 && parts[0] && parts[1]) {
        const sp = parts[0].split(':'), ep = parts[1].split(':');
        if (sp.length >= 2 && ep.length >= 2 && sp[1] != null && ep[1] != null) {
            if (parseInt(sp[1]) !== parseInt(ep[1])) issues.push('cross_verse');
        }
    }
    return issues;
}

export interface OpIssueDelta {
    resolved: string[];
    introduced: string[];
}

export function _deriveOpIssueDelta(group: EditOp[] | null | undefined): OpIssueDelta {
    if (!group || group.length === 0) return { resolved: [], introduced: [] };
    const primary = group[0];
    if (!primary) return { resolved: [], introduced: [] };

    const beforeIssues = new Set<string>();
    for (const snap of (primary.targets_before || [])) {
        _classifySnapIssues(snap as SnapForIssues).forEach((i) => beforeIssues.add(i));
    }

    const finalSnaps = new Map<string, SnapForIssues>();
    let hasAnyAfterUid = false;
    for (const op of group) {
        for (const snap of (op.targets_after || [])) {
            const s = snap as SnapForIssues;
            if (s.segment_uid) { finalSnaps.set(s.segment_uid, s); hasAnyAfterUid = true; }
        }
    }

    const afterSnaps: SnapForIssues[] = hasAnyAfterUid
        ? [...finalSnaps.values()]
        : ((group[group.length - 1]?.targets_after || []) as SnapForIssues[]);

    const afterIssues = new Set<string>();
    for (const snap of afterSnaps) {
        _classifySnapIssues(snap).forEach((i) => afterIssues.add(i));
    }

    return {
        resolved:   [...beforeIssues].filter((i) => !afterIssues.has(i)),
        introduced: [...afterIssues].filter((i) => !beforeIssues.has(i)),
    };
}
