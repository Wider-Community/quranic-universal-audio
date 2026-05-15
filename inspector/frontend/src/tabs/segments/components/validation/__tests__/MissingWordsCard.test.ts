import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import { makeSegment } from '../../../__tests__/helpers/make-segment';
import { segAllData } from '../../../stores/chapter';
import { segConfig } from '../../../stores/config';
import MissingWordsCard from '../MissingWordsCard.svelte';

afterEach(() => {
  cleanup();
  segAllData.set(null);
  segConfig.update((cfg) => ({ ...cfg, accordionContext: null }));
});

function installSegments(): void {
  const segments = [
    { ...makeSegment(0, 0, 1000), chapter: 1, index: 0 },
    { ...makeSegment(1, 1000, 2000), chapter: 1, index: 1 },
    { ...makeSegment(2, 2000, 3000), chapter: 1, index: 2 },
  ];
  segAllData.set({ segments } as any);
}

describe('MissingWordsCard context defaults', () => {
  it('opens context by default when configured as shown', async () => {
    installSegments();
    segConfig.update((cfg) => ({ ...cfg, accordionContext: { missing_words: 'shown' } }));

    const { getByText } = render(MissingWordsCard, {
      item: { chapter: 1, verse_key: '1:1', seg_indices: [1], msg: 'missing words: [2]' },
    });

    await waitFor(() => expect(getByText('Hide Context')).toBeTruthy());
  });

  it('allows the user to hide default-open context', async () => {
    installSegments();
    segConfig.update((cfg) => ({ ...cfg, accordionContext: { missing_words: 'shown' } }));

    const { getByText } = render(MissingWordsCard, {
      item: { chapter: 1, verse_key: '1:1', seg_indices: [1], msg: 'missing words: [2]' },
    });

    const button = await waitFor(() => getByText('Hide Context'));
    await fireEvent.click(button);

    await waitFor(() => expect(getByText('Show Context')).toBeTruthy());
  });
});
