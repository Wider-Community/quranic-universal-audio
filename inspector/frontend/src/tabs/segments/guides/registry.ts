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
