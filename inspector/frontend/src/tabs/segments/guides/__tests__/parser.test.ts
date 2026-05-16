import { describe, expect, it } from 'vitest';

import { parseGuideSource } from '../parser';

describe('accordion guide parser', () => {
  it('preserves text, example, text, and two examples in order', () => {
    const blocks = parseGuideSource(`
# Title

First paragraph.

::example{id="one"}

Second paragraph.

::example{id="two"}
::example{id="three"}
`);

    expect(blocks).toEqual([
      { type: 'heading', level: 1, text: 'Title' },
      { type: 'paragraph', text: 'First paragraph.' },
      { type: 'example', id: 'one' },
      { type: 'paragraph', text: 'Second paragraph.' },
      { type: 'example', id: 'two' },
      { type: 'example', id: 'three' },
    ]);
  });

  it('turns malformed directives into non-crashing placeholder blocks', () => {
    const blocks = parseGuideSource('::example{}');

    expect(blocks).toEqual([
      { type: 'missing', message: 'Example directive is missing an id: ::example{}' },
    ]);
  });
});
