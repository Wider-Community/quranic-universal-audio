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

  it('parses blockquote lines into a callout block and joins consecutive lines', () => {
    const blocks = parseGuideSource(`
Intro paragraph.

> By the end this should be zero
> — resolved or ignored.

::example{id="one"}
`);

    expect(blocks).toEqual([
      { type: 'paragraph', text: 'Intro paragraph.' },
      { type: 'callout', text: 'By the end this should be zero — resolved or ignored.' },
      { type: 'example', id: 'one' },
    ]);
  });

  it('ends a callout when plain prose follows without a blank line', () => {
    const blocks = parseGuideSource(`> Goal line.
Back to prose.`);

    expect(blocks).toEqual([
      { type: 'callout', text: 'Goal line.' },
      { type: 'paragraph', text: 'Back to prose.' },
    ]);
  });

  it('turns malformed directives into non-crashing placeholder blocks', () => {
    const blocks = parseGuideSource('::example{}');

    expect(blocks).toEqual([
      { type: 'missing', message: 'Example directive is missing an id: ::example{}' },
    ]);
  });
});
