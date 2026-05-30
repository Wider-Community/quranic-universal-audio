import { describe, expect, it } from 'vitest';

import { type InfoBlock, parseInfoDoc, parseInline } from '../info-doc';

const SRC = `# About Title

Intro paragraph one
spanning two source lines.

## How it works

A single body paragraph.

## Lifecycle

Lead-in line.

::lifecycle
- available_for_request: Catalogued, not requested.
- requested: Pipeline running.
- bogus_bucket: Should be dropped.
- published: Live in the dataset.

## Tabs

- **Dashboard** — the front door.
- Plain item.
`;

describe('parseInline', () => {
    it('splits bold runs and preserves surrounding text', () => {
        const tokens = parseInline('**Dashboard** — the front door.');
        expect(tokens).toEqual([
            { bold: true, text: 'Dashboard' },
            { bold: false, text: ' — the front door.' },
        ]);
    });

    it('always returns at least one token', () => {
        expect(parseInline('plain')).toEqual([{ bold: false, text: 'plain' }]);
    });

    it('parses a markdown link into an href run with surrounding text', () => {
        expect(parseInline('Feel free to [open an issue](https://x.test/i) or reach out.')).toEqual([
            { bold: false, text: 'Feel free to ' },
            { bold: false, text: 'open an issue', href: 'https://x.test/i' },
            { bold: false, text: ' or reach out.' },
        ]);
    });
});

describe('parseInfoDoc', () => {
    const doc = parseInfoDoc(SRC);

    it('extracts the leading # as the title', () => {
        expect(doc.title).toBe('About Title');
    });

    it('joins wrapped paragraph lines with a space', () => {
        const para = doc.blocks.find(
            (b): b is Extract<InfoBlock, { type: 'paragraph' }> => b.type === 'paragraph',
        );
        expect(para?.tokens.map((t) => t.text).join('')).toBe(
            'Intro paragraph one spanning two source lines.',
        );
    });

    it('renders headings', () => {
        const headings = doc.blocks
            .filter((b): b is Extract<InfoBlock, { type: 'heading' }> => b.type === 'heading')
            .map((b) => b.text);
        expect(headings).toEqual(['How it works', 'Lifecycle', 'Tabs']);
    });

    it('collects lifecycle rows and drops unknown buckets', () => {
        const life = doc.blocks.find(
            (b): b is Extract<InfoBlock, { type: 'lifecycle' }> => b.type === 'lifecycle',
        );
        expect(life?.rows.map((r) => r.state)).toEqual([
            'available_for_request',
            'requested',
            'published',
        ]);
        expect(life?.rows[0]?.text).toBe('Catalogued, not requested.');
    });

    it('parses a normal list with inline bold after the lifecycle block', () => {
        const lists = doc.blocks.filter(
            (b): b is Extract<InfoBlock, { type: 'list' }> => b.type === 'list',
        );
        const tabs = lists.at(-1);
        expect(tabs?.items[0]?.[0]).toEqual({ bold: true, text: 'Dashboard' });
        expect(tabs?.items[1]).toEqual([{ bold: false, text: 'Plain item.' }]);
    });
});
