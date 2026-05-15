import { cleanup, fireEvent, render, waitFor } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { makeSegment } from '../../../__tests__/helpers/make-segment';
import { segAllData } from '../../../stores/chapter';
import { segValidation } from '../../../stores/validation';
import ValidationPanel from '../ValidationPanel.svelte';

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
});

describe('ValidationPanel accordion guide modal', () => {
  it('opens a code-stored text guide from the help button without fetching', async () => {
    vi.stubGlobal('fetch', vi.fn());
    const { getByLabelText, getByText } = render(ValidationPanel);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(getByText('Listen first. Low confidence is a signal to check the segment, not an automatic instruction to edit it.')).toBeTruthy());
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders history examples without edit controls', async () => {
    const { getByLabelText, getByText, queryByText } = render(ValidationPanel);

    await fireEvent.click(getByLabelText('Open guide for Low Confidence'));

    await waitFor(() => expect(getByText('Reference correction')).toBeTruthy());
    expect(queryByText('Undo')).toBeNull();
    expect(queryByText('Discard')).toBeNull();
  });
});
