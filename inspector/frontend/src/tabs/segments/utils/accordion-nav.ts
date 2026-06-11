/**
 * Accordion-scoped navigation sequence.
 *
 * When a validation accordion is open the main list is hidden, so the only
 * `.seg-row` cards in the DOM are the open category's rows — in render order.
 * This reads them straight from the DOM (cheap, and immune to the per-card
 * split-group / resolve complexity) to drive ↑/↓ navigation and autoplay-
 * advance through the accordion.
 *
 * The sequence includes context (prev/next neighbour) rows as well as main
 * rows, so ↑/↓ can land on a neighbour, and multi-segment split cards flow
 * through their pieces — one continuous list. A segment that appears twice
 * (e.g. one card's "next" neighbour is the next card's main row) is deduped to
 * a single stop in DOM order.
 */

import { get } from 'svelte/store';

import { playingSegmentIndex } from '../stores/playback';
import { valUiOpenCategory } from '../stores/validation';

export interface AccordionRowRef {
    chapter: number;
    index: number;
}

/** Ordered, deduped (chapter, index) list of the open accordion's rows
 *  (context + main), or [] when no accordion is open / nothing is rendered. */
export function accordionSequence(): AccordionRowRef[] {
    if (get(valUiOpenCategory) === null) return [];
    if (typeof document === 'undefined') return [];
    const rows = document.querySelectorAll<HTMLElement>(
        '.seg-row[data-seg-uid]:not(.mode-history)',
    );
    const out: AccordionRowRef[] = [];
    const seen = new Set<string>();
    rows.forEach((el) => {
        const idx = Number(el.dataset.segIndex);
        const ch = el.dataset.segChapter != null ? Number(el.dataset.segChapter) : NaN;
        if (!Number.isFinite(idx) || !Number.isFinite(ch)) return;
        const key = `${ch}:${idx}`;
        if (seen.has(key)) return;
        seen.add(key);
        out.push({ chapter: ch, index: idx });
    });
    return out;
}

/**
 * Step one card relative to the currently-playing segment within the open
 * accordion sequence. Clamps at the ends. Falls back to the first/last card
 * when nothing in the sequence is currently playing. Returns null when there
 * is no open accordion sequence.
 */
export function accordionStep(dir: 1 | -1): AccordionRowRef | null {
    const seq = accordionSequence();
    if (seq.length === 0) return null;
    const active = get(playingSegmentIndex);
    const pos = active
        ? seq.findIndex((r) => r.chapter === active.chapter && r.index === active.index)
        : -1;
    if (pos === -1) return dir === 1 ? seq[0]! : seq[seq.length - 1]!;
    const next = pos + dir;
    if (next < 0 || next >= seq.length) return seq[pos]!;
    return seq[next]!;
}
