import { cleanup, render } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import BoundaryEvidence from '../BoundaryEvidence.svelte';

afterEach(() => {
    cleanup();
});

const hiddenPauseItem = {
    ref: '2:5:1-2:6:2',
    chapter: 2,
    seg_index: 3,
    segment_uid: 'u1',
    classified_issues: ['hidden_pause'],
    boundary: {
        cursors: [123456],
        refs: ['2:5:1-2:5:3', '2:5:4-2:6:2'],
        score: 2450,
        cuts: [
            {
                cursor_ms: 123456,
                axes: ['lite', 'trio'],
                gap_ms: 450,
                score: 2450,
                word: 'الرحمن',
                final_class: 'he',
                verse_end: false,
                evidence: {},
            },
        ],
    },
};

const falseSplitItem = {
    ref: '2:5:1-2:5:3',
    chapter: 2,
    seg_index: 4,
    segment_uid: 'u2',
    classified_issues: ['false_split'],
    boundary: {
        next_uid: 'u3',
        axes: ['trio'],
        gap_ms: 40,
        score: 1040,
        word: 'شيء',
        final_class: 'nasal',
        verse_end: false,
        is_wasl: true,
        evidence: {},
    },
};

describe('BoundaryEvidence', () => {
    it('renders hidden-pause axes, cursor, gap, word, final class and score', () => {
        const { container, getByText } = render(BoundaryEvidence, {
            category: 'hidden_pause',
            item: hiddenPauseItem as any,
        });
        const chips = Array.from(container.querySelectorAll('.bx-axis')).map((el) => el.textContent);
        expect(chips).toEqual(['lite', 'trio']);
        expect(getByText('cut 2:03.456')).toBeTruthy();
        expect(getByText('gap 450 ms')).toBeTruthy();
        expect(getByText('الرحمن')).toBeTruthy();
        expect(getByText('final he')).toBeTruthy();
        expect(getByText('score 2450')).toBeTruthy();
    });

    it('falls back to bare cursors when the sidecar carries no cuts', () => {
        const item = { ...hiddenPauseItem, boundary: { ...hiddenPauseItem.boundary, cuts: [] } };
        const { getByText, container } = render(BoundaryEvidence, {
            category: 'hidden_pause',
            item: item as any,
        });
        expect(getByText('cut 2:03.456')).toBeTruthy();
        expect(container.querySelectorAll('.bx-axis')).toHaveLength(0);
    });

    it('renders false-split evidence with the merge-target note and wasl chip', () => {
        const { getByText, queryByText } = render(BoundaryEvidence, {
            category: 'false_split',
            item: falseSplitItem as any,
        });
        expect(getByText('trio')).toBeTruthy();
        expect(getByText('gap 40 ms')).toBeTruthy();
        expect(getByText('شيء')).toBeTruthy();
        expect(getByText('merge target: next segment')).toBeTruthy();
        expect(getByText('wasl')).toBeTruthy();
        expect(getByText('score 1040')).toBeTruthy();
        expect(queryByText(/^cut /)).toBeNull();
    });
});
