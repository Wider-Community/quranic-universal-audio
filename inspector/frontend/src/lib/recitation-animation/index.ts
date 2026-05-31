/**
 * Recitation-animation feature — shared, surface-agnostic.
 *
 * Public surface: the collapsible section + line animation, the ayah picker,
 * the timeline markers, the chapter-words assembly, and the tunable config.
 * Wired into the dashboard now; designed for the timestamps tab to re-adopt
 * later (same footer + section). No tab-store coupling lives here.
 */

export { default as RecitationSection } from './RecitationSection.svelte';
export { default as LineAnimation } from './LineAnimation.svelte';
export { default as AyahPicker } from './AyahPicker.svelte';
export { default as TimelineAyahMarkers } from './TimelineAyahMarkers.svelte';

export {
    buildChapterRecitation,
    ayahUnitRanges,
    type AssembledVerse,
} from './chapter-words';
export {
    DEFAULT_RECITATION_CONFIG,
    EASING_OPTIONS,
    cssVars,
    cssVarText,
    recitationConfig,
    type Granularity,
    type RecitationAnimConfig,
} from './config';
export type {
    AnimLetter,
    AnimUnit,
    AyahBoundary,
    ChapterRecitation,
    RecitationPlayback,
} from './types';
