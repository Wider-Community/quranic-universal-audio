import lowConfidenceGuide from './accordion/low_confidence.guide';

const accordionGuides: Readonly<Record<string, string>> = Object.freeze({
    low_confidence: lowConfidenceGuide,
});

export function getAccordionGuide(category: string): string | null {
    return accordionGuides[category] ?? null;
}
