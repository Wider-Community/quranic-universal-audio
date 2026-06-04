import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FakeIntersectionObserver } from '../../../../../lib/test-helpers/dom-stubs';
import { makeSegment } from '../../../__tests__/helpers/make-segment';
import { segAllData } from '../../../stores/chapter';
import { closeGuideModal } from '../../../stores/guides';
import { segValidation } from '../../../stores/validation';
import GuideModalHarness from './GuideModalHarness.svelte';

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

describe('AccordionGuideModal', () => {
  it('opens a code-stored text guide from the help button', async () => {
    // Guide bodies are statically imported, not fetched. The previous
    // assertion that ``fetch`` is never called only held because the user
    // is anonymous and ``recordGuideRead`` short-circuits before any
    // ``/api/guides/viewed`` POST. Don't conflate static-import behaviour
    // with the read-receipt fetch — assert the rendered body directly.
    const { getByLabelText, getByText } = render(GuideModalHarness);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(
      getByText((_, el) => el?.tagName === 'P'
        && (el.textContent ?? '').includes("the model wasn't sure its text matched the audio")),
    ).toBeTruthy());
  });

  it('renders history examples without edit controls', async () => {
    const { getByLabelText, getByText, queryByText } = render(GuideModalHarness);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(getByText('Wrong word, low confidence')).toBeTruthy());
    expect(queryByText('Undo')).toBeNull();
    expect(queryByText('Discard')).toBeNull();
  });
});
