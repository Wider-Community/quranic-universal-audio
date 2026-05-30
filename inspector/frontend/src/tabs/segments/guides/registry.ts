import basmalaAminGuide from './accordion/basmala_amin.guide';
import boundaryAdjGuide from './accordion/boundary_adj.guide';
import crossVerseGuide from './accordion/cross_verse.guide';
import failedGuide from './accordion/failed.guide';
import lowConfidenceGuide from './accordion/low_confidence.guide';
import lowConfidenceV2Guide from './accordion/low_confidence_v2.guide';
import missingVersesGuide from './accordion/missing_verses.guide';
import missingWordsGuide from './accordion/missing_words.guide';
import muqattaatGuide from './accordion/muqattaat.guide';
import qalqalaGuide from './accordion/qalqala.guide';
import repetitionsGuide from './accordion/repetitions.guide';

const accordionGuides: Readonly<Record<string, string>> = Object.freeze({
    failed: failedGuide,
    missing_verses: missingVersesGuide,
    missing_words: missingWordsGuide,
    low_confidence: lowConfidenceGuide,
    low_confidence_v2: lowConfidenceV2Guide,
    boundary_adj: boundaryAdjGuide,
    repetitions: repetitionsGuide,
    cross_verse: crossVerseGuide,
    qalqala: qalqalaGuide,
    muqattaat: muqattaatGuide,
    basmala_amin: basmalaAminGuide,
});

export function getAccordionGuide(category: string): string | null {
    return accordionGuides[category] ?? null;
}

/** True iff a category has a guide — used to hide the help `?` otherwise. */
export function hasAccordionGuide(category: string): boolean {
    return category in accordionGuides;
}

// --- Read-tracking (unread border + first-edit onboarding gate) ------------
//
// A guide's *view key* is the identity we persist per user. `low_confidence`
// and `low_confidence_v2` share one guide (v2 re-exports the same source), so
// they collapse to a single required reading: opening either clears both, and
// storage never holds `low_confidence_v2`. Mirror this in the backend
// (`inspector/constants.py::guide_view_key`) when the mapping changes.

const GUIDE_VIEW_KEY_ALIASES: Readonly<Record<string, string>> = Object.freeze({
    low_confidence_v2: 'low_confidence',
});

/** Collapse a category to the key we persist (folds the low_confidence alias). */
export function guideViewKey(category: string): string {
    return GUIDE_VIEW_KEY_ALIASES[category] ?? category;
}

/**
 * The distinct guides a reviewer must read once before editing — the gate set.
 * Derived from the registry minus aliases, so registering a new guide here
 * auto-adds it; a guide that should NOT re-onboard established reviewers can be
 * registered in `accordionGuides` but left out of this list (badge-only).
 * Order is the canonical reading order.
 */
export const REQUIRED_GUIDE_KEYS: readonly string[] = Object.freeze([
    'failed',
    'missing_verses',
    'missing_words',
    'low_confidence',
    'boundary_adj',
    'repetitions',
    'cross_verse',
    'qalqala',
    'muqattaat',
    'basmala_amin',
]);

/** True iff this user has opened the guide for `category` (alias-aware). */
export function isGuideRead(guidesRead: readonly string[], category: string): boolean {
    return guidesRead.includes(guideViewKey(category));
}

/** True iff every required guide has been read — the edit-gate predicate. */
export function allGuidesRead(guidesRead: readonly string[]): boolean {
    return REQUIRED_GUIDE_KEYS.every((k) => guidesRead.includes(k));
}
