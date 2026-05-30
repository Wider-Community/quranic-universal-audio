/**
 * Tiny line-oriented parser for the dashboard info modal.
 *
 * Turns the markdown-ish `overview.md` (imported `?raw`) into a flat list
 * of typed blocks the modal renders. Deliberately minimal — headings,
 * paragraphs, bullet lists, inline `**bold**`, and one custom `::lifecycle`
 * directive whose rows render as real `StatePill`s. This mirrors the
 * accordion-guide parser pattern but stays self-contained in the dashboard
 * tab (no cross-tab import). Edit the wording in `overview.md`, never here.
 */
import { PUBLIC_BUCKETS, type PublicBucket } from '../../../../lib/types/public-state';

export interface InlineToken {
    bold: boolean;
    text: string;
}

export interface LifecycleRow {
    state: PublicBucket;
    text: string;
}

export type InfoBlock =
    | { type: 'heading'; text: string }
    | { type: 'paragraph'; tokens: InlineToken[] }
    | { type: 'list'; items: InlineToken[][] }
    | { type: 'lifecycle'; rows: LifecycleRow[] };

export interface InfoDoc {
    title: string | null;
    blocks: InfoBlock[];
}

const BOLD_RE = /\*\*([^*]+)\*\*/g;
const BUCKETS = new Set<string>(PUBLIC_BUCKETS);

/** Split a line into bold / plain runs. Always returns ≥1 token. */
export function parseInline(text: string): InlineToken[] {
    const tokens: InlineToken[] = [];
    let last = 0;
    for (const m of text.matchAll(BOLD_RE)) {
        const idx = m.index ?? 0;
        if (idx > last) tokens.push({ bold: false, text: text.slice(last, idx) });
        tokens.push({ bold: true, text: m[1] });
        last = idx + m[0].length;
    }
    if (last < text.length) tokens.push({ bold: false, text: text.slice(last) });
    return tokens.length > 0 ? tokens : [{ bold: false, text }];
}

export function parseInfoDoc(src: string): InfoDoc {
    const lines = src.replace(/\r\n/g, '\n').split('\n');
    let title: string | null = null;
    const blocks: InfoBlock[] = [];

    let para: string[] = [];
    let list: string[] = [];
    let lifecycle: LifecycleRow[] | null = null;

    const flushPara = (): void => {
        if (para.length > 0) {
            blocks.push({ type: 'paragraph', tokens: parseInline(para.join(' ')) });
            para = [];
        }
    };
    const flushList = (): void => {
        if (list.length > 0) {
            blocks.push({ type: 'list', items: list.map(parseInline) });
            list = [];
        }
    };
    const flushLifecycle = (): void => {
        if (lifecycle !== null) {
            if (lifecycle.length > 0) blocks.push({ type: 'lifecycle', rows: lifecycle });
            lifecycle = null;
        }
    };
    const flushAll = (): void => {
        flushPara();
        flushList();
        flushLifecycle();
    };

    for (const raw of lines) {
        const line = raw.trim();
        if (line === '') {
            flushAll();
            continue;
        }
        if (line.startsWith('# ')) {
            flushAll();
            title = line.slice(2).trim();
            continue;
        }
        if (line.startsWith('## ')) {
            flushAll();
            blocks.push({ type: 'heading', text: line.slice(3).trim() });
            continue;
        }
        if (line === '::lifecycle') {
            flushAll();
            lifecycle = [];
            continue;
        }
        if (line.startsWith('- ')) {
            const item = line.slice(2).trim();
            if (lifecycle !== null) {
                const sep = item.indexOf(':');
                if (sep > 0) {
                    const key = item.slice(0, sep).trim();
                    const text = item.slice(sep + 1).trim();
                    if (BUCKETS.has(key)) lifecycle.push({ state: key as PublicBucket, text });
                }
                continue;
            }
            flushPara();
            list.push(item);
            continue;
        }
        // Plain paragraph line — terminates any open list / lifecycle block.
        flushList();
        flushLifecycle();
        para.push(line);
    }
    flushAll();
    return { title, blocks };
}
