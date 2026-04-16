/**
 * Reference parsing, formatting, and time formatting utilities.
 *
 * Shim: re-exports pure implementations from lib/utils/segments/references,
 * injecting verse_word_counts from the active segments state.
 */

import {
    _addVerseMarkers as _addVerseMarkersLib,
    _normalizeRef as _normalizeRefLib,
    _suggestSplitRefs as _suggestSplitRefsLib,
    _toArabicNumeral,
    countSegWords as _countSegWords,
    formatDurationMs,
    formatRef as _formatRef,
    formatTimeMs,
    isCrossVerse,
    parseSegRef,
} from '../lib/utils/segments/references';
import type { Ref } from '../types/domain';
import { state } from './state';

export type { ParsedSegRef } from '../lib/utils/segments/references';
export { isCrossVerse, parseSegRef, _toArabicNumeral, formatTimeMs, formatDurationMs };

function _getVwc() {
    return state.segAllData?.verse_word_counts ?? state.segData?.verse_word_counts;
}

export function countSegWords(ref: Ref | null | undefined): number {
    return _countSegWords(ref, _getVwc());
}

export function _normalizeRef(ref: Ref | null | undefined): Ref | null | undefined {
    return _normalizeRefLib(ref, _getVwc());
}

export function _addVerseMarkers(text: string | null | undefined, ref: Ref | null | undefined): string {
    return _addVerseMarkersLib(text, ref, _getVwc());
}

export function formatRef(ref: Ref | null | undefined): string {
    return _formatRef(ref, _getVwc());
}

export function _suggestSplitRefs(ref: Ref): { first: Ref; second: Ref } | null {
    return _suggestSplitRefsLib(ref, _getVwc());
}
