import { cleanup, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { chapterOccasions } from '../../../../lib/recitation-data/occasions';
import { nativeReading } from '../../../../lib/recitation-data/test-native-fixture';
import { assembleWaslGroup } from '../../../../lib/recitation-data/ts-source';
import { focusWaslGroup, loadedVerse } from '../../stores/verse';
import TimedAnalysisRow from '../TimedAnalysisRow.svelte';

describe('TimedAnalysisRow native renderer integration', () => {
    beforeEach(() => {
        loadedVerse.set(null);
        focusWaslGroup.set(null);
    });

    afterEach(() => {
        cleanup();
        loadedVerse.set(null);
        focusWaslGroup.set(null);
    });

    it('renders connected verses with native hooks, a verse marker, and context opacity', async () => {
        const reading = nativeReading('r1', [
            { ref: '1:3', start: 100, end: 1_000, text: 'a' },
            { ref: '1:4', start: 1_000, end: 2_000, text: 'b' },
        ]);
        const occasions = chapterOccasions([reading]);
        const data = assembleWaslGroup(
            'r', occasions, '1:3', {}, {}, { audio_category: 'by_surah' }, '',
        );
        loadedVerse.set({ data, tsSegOffset: 0.1, tsSegEnd: 2 });
        focusWaslGroup.set({
            data,
            span: [100, 2_000],
            refs: ['1:3', '1:4'],
            focusRef: '1:3',
        });
        const { container } = render(TimedAnalysisRow);
        await waitFor(() => expect(container.querySelectorAll('[data-qc-word-id]')).toHaveLength(2));
        const words = container.querySelectorAll<HTMLElement>('[data-qc-word-id]');
        expect(words[0]!.classList.contains('qc-context')).toBe(false);
        expect(words[1]!.classList.contains('qc-context')).toBe(true);
        expect(container.querySelectorAll('[data-qc-column-id]')).toHaveLength(2);
        expect(container.querySelectorAll('[data-qc-sound-id]')).toHaveLength(2);
        expect(container.querySelector('.verse-glyph')).not.toBeNull();
    });
});
