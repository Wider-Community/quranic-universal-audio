import type { GuideBlock } from './types';

const EXAMPLE_DIRECTIVE_RE = /^::example\{([^}]*)\}$/;
const COMPONENT_DIRECTIVE_RE = /^::component\{([^}]*)\}$/;
const ID_ATTR_RE = /\bid="([^"]+)"/;
const NAME_ATTR_RE = /\bname="([^"]+)"/;
// Blockquote-style callout marker (`> text`); a bare `>` is an empty line.
const CALLOUT_RE = /^>\s?(.*)$/;

function flushParagraph(lines: string[], blocks: GuideBlock[]): void {
    if (lines.length === 0) return;
    blocks.push({ type: 'paragraph', text: lines.join(' ').trim() });
    lines.length = 0;
}

function flushCallout(lines: string[], blocks: GuideBlock[]): void {
    if (lines.length === 0) return;
    blocks.push({ type: 'callout', text: lines.join(' ').trim() });
    lines.length = 0;
}

export function parseGuideSource(source: string): GuideBlock[] {
    const blocks: GuideBlock[] = [];
    const paragraph: string[] = [];
    const callout: string[] = [];

    // Any non-callout token flushes a pending callout; helper keeps the
    // per-branch bookkeeping in one place.
    const flushOpen = (): void => {
        flushParagraph(paragraph, blocks);
        flushCallout(callout, blocks);
    };

    for (const raw of source.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line) {
            flushOpen();
            continue;
        }

        const calloutMatch = CALLOUT_RE.exec(line);
        if (calloutMatch) {
            // A callout starts its own block — flush any pending paragraph,
            // then accumulate consecutive `> ` lines into one callout.
            flushParagraph(paragraph, blocks);
            callout.push((calloutMatch[1] ?? '').trim());
            continue;
        }

        if (line.startsWith('::')) {
            flushOpen();
            const component = COMPONENT_DIRECTIVE_RE.exec(line);
            if (component) {
                const name = NAME_ATTR_RE.exec(component[1] ?? '')?.[1];
                if (!name) {
                    blocks.push({ type: 'missing', message: `Component directive is missing a name: ${line}` });
                    continue;
                }
                blocks.push({ type: 'component', name });
                continue;
            }
            const example = EXAMPLE_DIRECTIVE_RE.exec(line);
            if (!example) {
                blocks.push({ type: 'missing', message: `Unsupported guide directive: ${line}` });
                continue;
            }
            const id = ID_ATTR_RE.exec(example[1] ?? '')?.[1];
            if (!id) {
                blocks.push({ type: 'missing', message: `Example directive is missing an id: ${line}` });
                continue;
            }
            blocks.push({ type: 'example', id });
            continue;
        }

        if (line.startsWith('## ')) {
            flushOpen();
            blocks.push({ type: 'heading', level: 2, text: line.slice(3).trim() });
            continue;
        }

        if (line.startsWith('# ')) {
            flushOpen();
            blocks.push({ type: 'heading', level: 1, text: line.slice(2).trim() });
            continue;
        }

        // Plain prose after a callout ends it.
        flushCallout(callout, blocks);
        paragraph.push(line);
    }

    flushOpen();
    return blocks;
}

export function guideTitleFromBlocks(blocks: readonly GuideBlock[], fallback: string): string {
    for (const block of blocks) {
        if (block.type === 'heading' && block.level === 1) {
            return block.text || fallback;
        }
    }
    return fallback;
}
