/**
 * Tiny line-oriented parser for the project-overview content.
 *
 * Turns the markdown-ish `overview.md` (imported `?raw`) into a flat list of
 * typed blocks `OverviewContent` renders. Deliberately minimal — headings,
 * paragraphs, bullet lists, inline `**bold**` + `[text](href)` links, and one
 * custom `::lifecycle` directive whose rows render as real `StatePill`s. Lives
 * in `lib/` because the content is shared cross-tab: the dashboard `InfoModal`
 * and the segments first-edit gate (via AccordionGuideModal's `::component`)
 * both render it. Edit the wording in `overview.md`, never here.
 */
import { PUBLIC_BUCKETS, type PublicBucket } from '../../types/public-bucket';

export interface InlineToken {
    bold: boolean;
    text: string;
    /** Present on `[text](href)` link runs; renders as an external anchor. */
    href?: string;
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

// Bold link `**[text](href)**` (groups 1+2) must come BEFORE plain bold, else
// `**...**` swallows the link markup as literal text. Then `**bold**` (group 3)
// and plain `[text](href)` (groups 4+5).
const INLINE_RE =
    /\*\*\[([^\]]+)\]\(([^)]+)\)\*\*|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)]+)\)/g;
const BUCKETS = new Set<string>(PUBLIC_BUCKETS);

/** Split a line into bold / link / bold-link / plain runs. Always returns ≥1 token. */
export function parseInline(text: string): InlineToken[] {
    const tokens: InlineToken[] = [];
    let last = 0;
    for (const m of text.matchAll(INLINE_RE)) {
        const idx = m.index ?? 0;
        if (idx > last) tokens.push({ bold: false, text: text.slice(last, idx) });
        if (m[1] !== undefined) {
            tokens.push({ bold: true, text: m[1], href: m[2] });
        } else if (m[3] !== undefined) {
            tokens.push({ bold: true, text: m[3] });
        } else {
            tokens.push({ bold: false, text: m[4] ?? '', href: m[5] ?? '' });
        }
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
