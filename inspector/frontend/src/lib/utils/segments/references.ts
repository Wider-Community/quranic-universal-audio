import type { Ref, VerseRef } from '../../types/domain';
import { _ARABIC_DIGITS } from './constants';

/** Parsed canonical segment ref. */
export interface ParsedSegRef {
    surah: number;
    ayah_from: number;
    word_from: number;
    ayah_to: number;
    word_to: number;
}

type VerseWordCounts = Record<VerseRef, number>;

export function isCrossVerse(ref: Ref | null | undefined): boolean {
    if (!ref) return false;
    const parts = ref.split('-');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return false;
    const startAyah = parts[0].split(':')[1];
    const endAyah = parts[1].split(':')[1];
    return startAyah !== endAyah;
}

export function parseSegRef(ref: Ref | null | undefined): ParsedSegRef | null {
    if (!ref) return null;
    const parts = ref.split('-');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return null;
    const s = parts[0].split(':'), e = parts[1].split(':');
    if (s.length < 3 || e.length < 3) return null;
    if (s[0] == null || s[1] == null || s[2] == null || e[1] == null || e[2] == null) return null;
    return { surah: +s[0], ayah_from: +s[1], word_from: +s[2], ayah_to: +e[1], word_to: +e[2] };
}

export function countSegWords(ref: Ref | null | undefined, vwc?: VerseWordCounts): number {
    const p = parseSegRef(ref);
    if (!p) return 0;
    if (p.ayah_from === p.ayah_to) return p.word_to - p.word_from + 1;
    let total = 0;
    for (let a = p.ayah_from; a <= p.ayah_to; a++) {
        const key = `${p.surah}:${a}`;
        if (a === p.ayah_from)      total += (vwc?.[key] ?? p.word_from) - p.word_from + 1;
        else if (a === p.ayah_to)   total += p.word_to;
        else                        total += vwc?.[key] ?? 0;
    }
    return total;
}

export function _toArabicNumeral(n: number): string {
    return String(n).split('').map((d) => _ARABIC_DIGITS[+d] ?? d).join('');
}

/** Normalize a short ref to canonical surah:ayah:word-surah:ayah:word format. */
export function _normalizeRef(ref: Ref | null | undefined, vwc?: VerseWordCounts): Ref | null | undefined {
    if (!ref) return ref;
    const parts = ref.split('-');
    if (parts.length === 2 && parts[0] && parts[1]) {
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

/** Insert verse end markers at verse boundaries within segment text. */
export function _addVerseMarkers(text: string | null | undefined, ref: Ref | null | undefined, vwc?: VerseWordCounts): string {
    if (!text || !ref) return text ?? '';
    const normalized = _normalizeRef(ref, vwc);
    const p = parseSegRef(normalized);
    if (!p || !vwc) return text;

    const words = text.split(/\s+/).filter(Boolean);
    const out: string[] = [];
    let ay = p.ayah_from, w = p.word_from;

    for (let i = 0; i < words.length; i++) {
        const word = words[i];
        if (word == null) continue;
        out.push(word);
        if (!/[\u0600-\u066F]/.test(word)) continue;
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

export function formatRef(ref: Ref | null | undefined, vwc?: VerseWordCounts): string {
    if (!ref) return '(no match)';
    if (!vwc) return ref;
    const parts = ref.split('-');
    if (parts.length !== 2 || !parts[0] || !parts[1]) return ref;
    const start = parts[0].split(':');
    const end = parts[1].split(':');
    if (start.length !== 3 || end.length !== 3) return ref;
    if (start[0] === end[0] && start[1] === end[1] && start[2] === '1') {
        const key = `${start[0]}:${start[1]}`;
        const totalWords = vwc[key];
        if (totalWords && end[2] != null && parseInt(end[2]) === totalWords) {
            return key;
        }
    }
    return ref;
}

export function formatTimeMs(ms: number): string {
    if (!isFinite(ms)) return '0:00';
    const totalSec = ms / 1000;
    const mins = Math.floor(totalSec / 60);
    const secs = Math.floor(totalSec % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function formatDurationMs(ms: number): string {
    if (!isFinite(ms) || ms === 0) return '0s';
    const seconds = ms / 1000;
    if (seconds < 60) return seconds.toFixed(1) + 's';
    const mins = Math.floor(seconds / 60);
    const secs = (seconds % 60).toFixed(0);
    return `${mins}m ${secs}s`;
}

/**
 * Suggest per-verse refs for the two halves when splitting a cross-verse segment.
 * Returns {first, second} ref strings or null if single-verse or data unavailable.
 */
export function _suggestSplitRefs(ref: Ref, vwc?: VerseWordCounts): { first: Ref; second: Ref } | null {
    const p = parseSegRef(ref);
    if (!p || p.ayah_from === p.ayah_to) return null;
    if (!vwc) return null;
    const firstVerseKey = `${p.surah}:${p.ayah_from}`;
    const firstEnd = vwc[firstVerseKey];
    if (!firstEnd) return null;

    const first: Ref = (p.word_from === 1 && p.word_from <= firstEnd)
        ? `${p.surah}:${p.ayah_from}`
        : `${p.surah}:${p.ayah_from}:${p.word_from}-${p.surah}:${p.ayah_from}:${firstEnd}`;

    const nextAyah = p.ayah_from + 1;
    const second: Ref = (nextAyah === p.ayah_to)
        ? `${p.surah}:${p.ayah_to}:1-${p.surah}:${p.ayah_to}:${p.word_to}`
        : `${p.surah}:${nextAyah}:1-${p.surah}:${p.ayah_to}:${p.word_to}`;

    return { first, second };
}
