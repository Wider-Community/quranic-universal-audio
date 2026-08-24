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

export interface BoundaryPolicy {
    span: Span;
    recordedPause: boolean;
    showMarker: boolean;
    verseEnd: boolean;
    sakt: boolean;
}

export type BoundaryPolicies = Map<string, Map<string, BoundaryPolicy>>;

const union = (spans: Span[]): Span | null => spans.length ? [
    Math.min(...spans.map((span) => span[0])),
    Math.max(...spans.map((span) => span[1])),
] : null;

const resolved = (ids: Array<string | number>, spans: Map<string, Span>): Span[] =>
    ids.flatMap((id) => {
        const span = spans.get(String(id));
        return span ? [span] : [];
    });

export function columnSpans(item: ParsedReading): Map<string, Span> {
    const sounds = new Map(item.reading.timing.sounds
        .map((row) => [String(row.sound_id), [row.start_ms, row.end_ms] as Span]));
    const owners = [...item.view.words, ...item.view.boundaries];
    const columns = new Map(owners.flatMap((owner) => owner.columns.map((column) => [
        String(column.id), column,
    ] as const)));
    const out = new Map<string, Span>();
    const cellSounds = owners.flatMap((owner) => [
        ...owner.sounds,
        ...owner.bridges.map((bridge) => bridge.sound),
    ]);
    for (const sound of cellSounds) {
        const span = sounds.get(String(sound.sound_id));
        if (!span) continue;
        for (const id of sound.column_ids.map(String)) {
            if (columns.get(id)?.silence) continue;
            const range = union([...(out.get(id) ? [out.get(id)!] : []), span]);
            if (range) out.set(id, range);
        }
    }
    for (const override of item.reading.timing.columns) {
        const id = String(override.column_id);
        if (columns.get(id)?.silence
            || override.start_ms === null
            || override.end_ms === null) {
            out.delete(id);
        } else {
            out.set(id, [override.start_ms, override.end_ms]);
        }
    }
    return out;
}

interface FlatWord {
    readingId: string;
    boundaryId: string;
    start: number;
    end: number;
    finalEnd: number;
    verseEnd: boolean;
    sakt: boolean;
}

function flatWords(parsed: ParsedReading[]): FlatWord[] {
    return parsed.flatMap((item) => {
        const timings = new Map(item.reading.timing.words.map((row) => [String(row.word_id), row]));
        const finalEnd = item.reading.parts.at(-1)?.t[1] ?? 0;
        return item.view.words.flatMap((word, index) => {
            const timing = timings.get(String(word.word_id));
            const boundary = item.view.boundaries[index];
            if (!timing || !boundary) return [];
            return [{
                readingId: item.reading.id,
                boundaryId: String(boundary.boundary_id),
                start: timing.start_ms,
                end: timing.end_ms,
                finalEnd,
                verseEnd: Boolean(boundary.verse_end),
                sakt: boundary.state === 'sakt',
            }];
        });
    });
}

export function buildBoundaryPolicies(parsed: ParsedReading[]): BoundaryPolicies {
    const words = flatWords(parsed);
    const policies: BoundaryPolicies = new Map();
    words.forEach((word, index) => {
        const next = words[index + 1];
        const end = Math.max(word.end, next?.start ?? word.finalEnd);
        const recordedPause = end > word.end;
        const reading = policies.get(word.readingId) ?? new Map<string, BoundaryPolicy>();
        reading.set(word.boundaryId, {
            span: [word.end, end],
            recordedPause,
            showMarker: recordedPause || word.verseEnd || word.sakt,
            verseEnd: word.verseEnd,
            sakt: word.sakt,
        });
        policies.set(word.readingId, reading);
    });
    return policies;
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
    const sounds = new Map<string, string[]>();
    owners.flatMap((owner) => [
        ...owner.sounds,
        ...owner.bridges.map((bridge) => bridge.sound),
    ]).forEach((sound) => {
        const id = String(sound.sound_id);
        sounds.set(id, [...new Set([
            ...(sounds.get(id) ?? []),
            ...rulesOn(item, sound.rule_occurrence_ids),
        ])]);
    });
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
    offset: number;
    cache: TimedEntityCache;
}

function bindHooks(options: BindOptions): void {
    const attribute = options.selector.slice(1, -1);
    options.container.querySelectorAll<HTMLElement>(options.selector).forEach((element) => {
        const id = element.getAttribute(attribute);
        if (!id) return;
        const word = element.closest<HTMLElement>('[data-qc-word-id]');
        const wordId = word?.dataset.qcWordId ?? '';
        const rules = options.rules?.get(id) ?? [];
        if (rules.length) element.dataset.qcRuleIds = rules.join(' ');
        const span = options.spans.get(id);
        if (!span) return;
        const entity: TimedEntity = {
            kind: options.kind,
            id,
            readingId: options.readingId,
            element,
            start: span[0] / 1000 - options.offset,
            end: span[1] / 1000 - options.offset,
            wordIndex: options.targetIndexes?.get(id) ?? options.wordIndexes.get(wordId) ?? -1,
            childIndex: options.cache.entities.length,
        };
        options.cache.entities.push(entity);
        options.cache.byElement.set(element, entity);
    });
}

function readingSpans(
    item: ParsedReading,
    wordIndexes: Map<string, number>,
    policies: BoundaryPolicies,
) {
    const words = new Map(item.reading.timing.words.map((row) => [
        String(row.word_id), [row.start_ms, row.end_ms] as Span,
    ]));
    const sounds = new Map(item.reading.timing.sounds.map((row) => [
        String(row.sound_id), [row.start_ms, row.end_ms] as Span,
    ]));
    const boundaries = new Map([...(policies.get(item.reading.id)?.entries() ?? [])]
        .map(([id, policy]) => [id, policy.span]));
    const boundaryIndexes = new Map(item.view.boundaries.map((boundary, index) => [
        String(boundary.boundary_id), wordIndexes.get(String(item.view.words[index]?.word_id)) ?? -1,
    ]));
    return { wordIndexes, words, sounds, boundaries, boundaryIndexes };
}

function bindReading(
    root: HTMLElement,
    item: ParsedReading,
    readingIndex: number,
    wordIndexes: Map<string, number>,
    policies: BoundaryPolicies,
    offset: number,
    cache: TimedEntityCache,
): void {
    const container = root.querySelector<HTMLElement>(`[data-reading-index="${readingIndex}"]`);
    if (!container) return;
    const base = readingSpans(item, wordIndexes, policies);
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
        offset, cache };
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
    const queues = new Map<string, number[]>();
    displayWords.forEach((word, index) => {
        const key = `${word.location}:${Math.round((word.start + offset) * 1000)}:${Math.round((word.end + offset) * 1000)}`;
        const values = queues.get(key) ?? [];
        values.push(index);
        queues.set(key, values);
    });
    const policies = buildBoundaryPolicies(parsed);
    parsed.forEach((item, index) => {
        const wordIndexes = new Map(item.reading.wire.analysis.result.words.map((word) => {
            const timing = item.reading.timing.words.find((row) => row.word_id === word.id);
            const key = `${word.ref}:${timing?.start_ms ?? ''}:${timing?.end_ms ?? ''}`;
            return [String(word.id), queues.get(key)?.shift() ?? -1] as const;
        }));
        bindReading(root, item, index, wordIndexes, policies, offset, cache);
    });
    return cache;
}
