import type { GuideBlock } from './types';

const EXAMPLE_DIRECTIVE_RE = /^::example\{([^}]*)\}$/;
const COMPONENT_DIRECTIVE_RE = /^::component\{([^}]*)\}$/;
const ID_ATTR_RE = /\bid="([^"]+)"/;
const NAME_ATTR_RE = /\bname="([^"]+)"/;

function flushParagraph(lines: string[], blocks: GuideBlock[]): void {
    if (lines.length === 0) return;
    blocks.push({ type: 'paragraph', text: lines.join(' ').trim() });
    lines.length = 0;
}

export function parseGuideSource(source: string): GuideBlock[] {
    const blocks: GuideBlock[] = [];
    const paragraph: string[] = [];

    for (const raw of source.split(/\r?\n/)) {
        const line = raw.trim();
        if (!line) {
            flushParagraph(paragraph, blocks);
            continue;
        }

        if (line.startsWith('::')) {
            flushParagraph(paragraph, blocks);
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
            flushParagraph(paragraph, blocks);
            blocks.push({ type: 'heading', level: 2, text: line.slice(3).trim() });
            continue;
        }

        if (line.startsWith('# ')) {
            flushParagraph(paragraph, blocks);
            blocks.push({ type: 'heading', level: 1, text: line.slice(2).trim() });
            continue;
        }

        paragraph.push(line);
    }

    flushParagraph(paragraph, blocks);
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
