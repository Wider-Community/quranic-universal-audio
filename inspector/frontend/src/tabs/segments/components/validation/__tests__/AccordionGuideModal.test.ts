import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { makeSegment } from '../../../__tests__/helpers/make-segment';
import { segAllData } from '../../../stores/chapter';
import { closeGuideModal } from '../../../stores/guides';
import { segValidation } from '../../../stores/validation';
import GuideModalHarness from './GuideModalHarness.svelte';

class FakeIntersectionObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
  segAllData.set({
    segments: [{ ...makeSegment(0, 0, 1000), chapter: 1, index: 0, segment_uid: 'seg-1' }],
  } as any);
  segValidation.set({
    low_confidence: [{
      chapter: 1,
      seg_index: 0,
      segment_uid: 'seg-1',
      ref: '1:1:1-1:1:1',
      confidence: 0.5,
    }],
  } as any);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  segAllData.set(null);
  segValidation.set(null);
  closeGuideModal();
});

describe('ValidationPanel accordion guide modal', () => {
  it('opens a code-stored text guide from the help button without fetching', async () => {
    vi.stubGlobal('fetch', vi.fn());
    const { getByLabelText, getByText } = render(GuideModalHarness);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(
      getByText((_, el) => el?.tagName === 'P'
        && (el.textContent ?? '').includes("the model wasn't sure its text matched the audio")),
    ).toBeTruthy());
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders history examples without edit controls', async () => {
    const { getByLabelText, getByText, queryByText } = render(GuideModalHarness);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(getByText('Wrong word, low confidence')).toBeTruthy());
    expect(queryByText('Undo')).toBeNull();
    expect(queryByText('Discard')).toBeNull();
  });
});
