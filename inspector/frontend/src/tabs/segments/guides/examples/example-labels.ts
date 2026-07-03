/**
 * Locale overlay for guide-example card strings (title / description / context
 * labels), keyed by example id.
 *
 * The example DATA (`./index.ts`) is auto-generated and carries English strings
 * only. This maps each to a message key
 * (`segments_guide_example_<id>_{title,desc,ctxN}`) and falls back to the baked-in
 * English when a locale key is absent — mirroring the `vocabLabel` convention. A
 * newly-generated example renders its English via the fallback until its `ar`
 * keys are dropped into `tabs/segments/messages/{en,ar}.json`.
 */
import * as m from '$lib/paraglide/messages';

import { getGuideExample } from './index';

const M = m as unknown as Record<string, () => string>;

export function exampleTitle(id: string): string {
    const fn = M[`segments_guide_example_${id}_title`];
    return fn ? fn() : (getGuideExample(id)?.title ?? '');
}

export function exampleDescription(id: string): string {
    const fn = M[`segments_guide_example_${id}_desc`];
    return fn ? fn() : (getGuideExample(id)?.description ?? '');
}

/** Localized context-block label, matched to its slot by the English label's
 *  index within the example's `context` array (labels are unique per example). */
export function exampleContextLabel(id: string, englishLabel: string): string {
    const ctx = getGuideExample(id)?.context ?? [];
    const idx = ctx.findIndex((c) => c.label === englishLabel);
    const fn = idx >= 0 ? M[`segments_guide_example_${id}_ctx${idx}`] : undefined;
    return fn ? fn() : englishLabel;
}
