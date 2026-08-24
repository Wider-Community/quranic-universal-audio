import { groupKey, type CellView, type parse } from '@quranic-phonemizer/cells';

import type { TsShardReading, TsWord } from '../../../lib/types/ts-client';

export type EntityKind = 'word' | 'column' | 'sound' | 'group' | 'boundary' | 'bridge';

export interface TimedEntity {
    kind: EntityKind;
    id: string;
    readingId: string;
    element: HTMLElement;
    start: number;
    end: number;
    wordIndex: number;
    childIndex?: number;
}

export interface ParsedReading {
    reading: TsShardReading;
    view: CellView;
    context: ReturnType<typeof parse>['context'];
}

export interface TimedEntityCache {
    entities: TimedEntity[];
    byElement: Map<HTMLElement, TimedEntity>;
}

type Span = [number, number];

const union = (spans: Span[]): Span | null => spans.length ? [
    Math.min(...spans.map((span) => span[0])),
    Math.max(...spans.map((span) => span[1])),
] : null;

const resolved = (ids: Array<string | number>, spans: Map<string, Span>): Span[] =>
    ids.flatMap((id) => {
        const span = spans.get(String(id));
        return span ? [span] : [];
    });

function columnSpans(item: ParsedReading): Map<string, Span> {
    const units = new Map(item.reading.letters
        .filter((row) => row.start_ms != null && row.end_ms != null)
        .map((row) => [String(row.source_unit_id), [row.start_ms!, row.end_ms!] as Span]));
    const sounds = new Map(item.reading.timing.sounds
        .map((row) => [String(row.sound_id), [row.start_ms, row.end_ms] as Span]));
    const owners = [...item.view.words, ...item.view.boundaries];
    const allSounds = owners.flatMap((owner) => owner.sounds);
    const out = new Map<string, Span>();
    for (const column of owners.flatMap((owner) => owner.columns)) {
        const spans = resolved(column.source_unit_ids, units);
        for (const sound of allSounds.filter((one) => one.column_ids.includes(column.id))) {
            const span = sounds.get(String(sound.sound_id));
            if (span) spans.push(span);
        }
        const range = union(spans);
        if (range) out.set(String(column.id), range);
    }
    for (const override of item.reading.timing.columns) {
        const id = String(override.column_id);
        if (override.start_ms == null || override.end_ms == null) out.delete(id);
        else out.set(id, [override.start_ms, override.end_ms]);
    }
    return out;
}

function rulesOn(item: ParsedReading, occurrences: Array<string | number>): string[] {
    return [...new Set(occurrences.flatMap((id) => {
        const rule = item.context.occurrences[String(id)]?.rule_id;
        return rule ? [rule] : [];
    }))];
}

function entityRules(item: ParsedReading) {
    const owners = [...item.view.words, ...item.view.boundaries];
    const columns = new Map<string, string[]>(owners.flatMap((owner) => owner.columns.map((column) => {
        const rules = rulesOn(item, column.rule_occurrence_ids);
        if (column.silence && item.context.rules[column.silence]) rules.push(column.silence);
        return [String(column.id), [...new Set(rules)]] as const;
    })));
    const sounds = new Map<string, string[]>(owners.flatMap((owner) => owner.sounds.map((sound) => [
        String(sound.sound_id), rulesOn(item, sound.rule_occurrence_ids),
    ] as const)));
    const groups = new Map<string, string[]>(item.view.words.flatMap((word) => word.groups.map((group) => [
        groupKey(group),
        [...new Set([
            ...group.column_ids.flatMap((id) => columns.get(String(id)) ?? []),
            ...group.sound_ids.flatMap((id) => sounds.get(String(id)) ?? []),
        ])],
    ] as const)));
    const bridges = new Map<string, string[]>(owners.flatMap((owner) => owner.bridges.map((bridge) => [
        String(bridge.merger_id), rulesOn(item, bridge.sound.rule_occurrence_ids),
    ] as const)));
    return { columns, sounds, groups, bridges };
}

interface BindOptions {
    container: HTMLElement;
    selector: string;
    kind: EntityKind;
    spans: Map<string, Span>;
    wordIndexes: Map<string, number>;
    targetIndexes?: Map<string, number>;
    rules?: Map<string, string[]>;
    readingId: string;
    wordSpans: Map<string, Span>;
    offset: number;
    cache: TimedEntityCache;
}

function bindHooks(options: BindOptions): void {
    const attribute = options.selector.slice(1, -1);
    options.container.querySelectorAll<HTMLElement>(options.selector).forEach((element, index) => {
        const id = element.getAttribute(attribute);
        if (!id) return;
        const word = element.closest<HTMLElement>('[data-qc-word-id]');
        const wordId = word?.dataset.qcWordId ?? '';
        const span = options.spans.get(id) ?? options.wordSpans.get(wordId);
        if (!span) return;
        const rules = options.rules?.get(id) ?? [];
        if (rules.length) element.dataset.qcRuleIds = rules.join(' ');
        const entity: TimedEntity = {
            kind: options.kind,
            id,
            readingId: options.readingId,
            element,
            start: span[0] / 1000 - options.offset,
            end: span[1] / 1000 - options.offset,
            wordIndex: options.targetIndexes?.get(id) ?? options.wordIndexes.get(wordId) ?? -1,
            childIndex: index,
        };
        options.cache.entities.push(entity);
        options.cache.byElement.set(element, entity);
    });
}

function readingSpans(item: ParsedReading, displayIndex: Map<string, number>) {
    const wordIndexes = new Map(item.reading.wire.analysis.result.words.map((word) => [
        String(word.id), displayIndex.get(word.ref) ?? -1,
    ]));
    const words = new Map(item.reading.timing.words.map((row) => [
        String(row.word_id), [row.start_ms, row.end_ms] as Span,
    ]));
    const sounds = new Map(item.reading.timing.sounds.map((row) => [
        String(row.sound_id), [row.start_ms, row.end_ms] as Span,
    ]));
    const boundaries = new Map(item.reading.timing.boundaries.map((row) => [
        String(row.boundary_id), [row.start_ms, row.end_ms] as Span,
    ]));
    const boundaryIndexes = new Map(item.view.boundaries.map((boundary, index) => [
        String(boundary.boundary_id), displayIndex.get(item.view.words[index]?.location ?? '') ?? -1,
    ]));
    return { wordIndexes, words, sounds, boundaries, boundaryIndexes };
}

function bindReading(
    root: HTMLElement,
    item: ParsedReading,
    readingIndex: number,
    displayIndex: Map<string, number>,
    offset: number,
    cache: TimedEntityCache,
): void {
    const container = root.querySelector<HTMLElement>(`[data-reading-index="${readingIndex}"]`);
    if (!container) return;
    const base = readingSpans(item, displayIndex);
    const columns = columnSpans(item);
    const rules = entityRules(item);
    const groups = new Map<string, Span>();
    item.view.words.flatMap((word) => word.groups).forEach((group) => {
        const span = union(resolved(group.column_ids, columns));
        if (span) groups.set(groupKey(group), span);
    });
    const bridges = new Map<string, Span>();
    [...item.view.words, ...item.view.boundaries].flatMap((owner) => owner.bridges)
        .forEach((bridge) => {
            const span = base.sounds.get(String(bridge.sound.sound_id));
            if (span) bridges.set(String(bridge.merger_id), span);
        });
    const common = { container, wordIndexes: base.wordIndexes, readingId: item.reading.id,
        wordSpans: base.words, offset, cache };
    bindHooks({ ...common, selector: '[data-qc-word-id]', kind: 'word', spans: base.words });
    bindHooks({ ...common, selector: '[data-qc-column-id]', kind: 'column', spans: columns, rules: rules.columns });
    bindHooks({ ...common, selector: '[data-qc-sound-id]', kind: 'sound', spans: base.sounds, rules: rules.sounds });
    bindHooks({ ...common, selector: '[data-qc-group-key]', kind: 'group', spans: groups, rules: rules.groups });
    bindHooks({ ...common, selector: '[data-qc-boundary-id]', kind: 'boundary', spans: base.boundaries,
        targetIndexes: base.boundaryIndexes });
    bindHooks({ ...common, selector: '[data-qc-bridge-id]', kind: 'bridge', spans: bridges, rules: rules.bridges });
}

export function buildTimedEntityCache(
    root: HTMLElement,
    parsed: ParsedReading[],
    displayWords: TsWord[],
    offset: number,
): TimedEntityCache {
    const cache: TimedEntityCache = { entities: [], byElement: new Map() };
    const displayIndex = new Map(displayWords.map((word, index) => [word.location, index]));
    parsed.forEach((item, index) => bindReading(root, item, index, displayIndex, offset, cache));
    return cache;
}
