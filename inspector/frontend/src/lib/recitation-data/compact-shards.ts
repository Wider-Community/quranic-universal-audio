/** Decode compact schema-v13 storage into the Inspector's timing view. */

import {
    decodeCompact,
    type CompactCellPayload,
} from '@quranic-phonemizer/cells';

import type { TsShardMeta } from '../types/generated/schemas';
import type {
    TsBoundaryTiming,
    TsShardPart,
    TsShardReading,
    TsShardResponse,
} from '../types/ts-client';

type StoredPart = [string, number, number, number, number];
type StoredAnimation = [number | null, number | null];
type StoredAnimationMeta = [number, number[], number[], number[], string, number[], 0 | 1 | 2, number | null];
type StoredColumn = [string | number, number | null, number | null];

interface StoredReading {
    id: string;
    parts: StoredPart[];
    render: CompactCellPayload & { a: StoredAnimationMeta[] };
    timing: {
        w: Array<[number, number]>;
        s: Array<[number, number]>;
        a: StoredAnimation[];
        c: StoredColumn[];
    };
}

interface StoredShard {
    _meta: TsShardMeta;
    readings: StoredReading[];
}

function partsOf(rows: StoredPart[]): TsShardPart[] {
    return rows.map(([ref, start, end, first, count]) => ({
        ref,
        t: [start, end],
        word_ids: Array.from({ length: count }, (_, index) => first + index),
    }));
}

function boundariesOf(
    parts: TsShardPart[],
    words: Array<[number, number]>,
): TsBoundaryTiming[] {
    if (!words.length) return [];
    const first = parts[0]?.t[0] ?? words[0]![0];
    const last = parts.at(-1)?.t[1] ?? words.at(-1)![1];
    const rows: TsBoundaryTiming[] = [{
        boundary_id: 0,
        start_ms: first,
        end_ms: Math.max(first, words[0]![0]),
    }];
    for (let id = 1; id < words.length; id += 1) {
        const start = words[id - 1]![1];
        rows.push({ boundary_id: id, start_ms: start, end_ms: Math.max(start, words[id]![0]) });
    }
    const start = words.at(-1)![1];
    rows.push({ boundary_id: words.length, start_ms: start, end_ms: Math.max(start, last) });
    return rows;
}

function readingOf(raw: StoredReading): TsShardReading {
    const parts = partsOf(raw.parts);
    if (raw.timing.w.length !== raw.render.w.length
        || raw.timing.s.length !== raw.render.p.length
        || raw.timing.a.length !== raw.render.a.length) {
        throw new Error(`${raw.id}: compact timing count mismatch`);
    }
    return {
        id: raw.id,
        parts,
        wire: decodeCompact(raw.render),
        animationTokens: raw.render.a.map((meta, id) => {
            const [word_id, source_unit_ids, character_ids, paint_character_ids, text,
                sound_ids, policyCode,
                target_token_id] = meta;
            const [start_ms, end_ms] = raw.timing.a[id]!;
            const policies = ['timed', 'cohighlight_previous', 'cohighlight_next'] as const;
            const policy = policies[policyCode];
            if (!policy) throw new Error(`${raw.id}: invalid animation policy ${policyCode}`);
            return { id, word_id, source_unit_ids, character_ids, paint_character_ids,
                text, sound_ids,
                policy, target_token_id, start_ms, end_ms };
        }),
        timing: {
            words: raw.timing.w.map(([start_ms, end_ms], word_id) => ({
                word_id, start_ms, end_ms,
            })),
            sounds: raw.timing.s.map(([start_ms, end_ms], sound_id) => ({
                sound_id, start_ms, end_ms,
            })),
            boundaries: boundariesOf(parts, raw.timing.w),
            columns: raw.timing.c.map(([column_id, start_ms, end_ms]) => ({
                column_id, start_ms, end_ms,
            })),
        },
    };
}

function stitchInterReadingPauses(readings: TsShardReading[]): void {
    const ordered = [...readings].sort((a, b) =>
        (a.parts[0]?.t[0] ?? 0) - (b.parts[0]?.t[0] ?? 0),
    );
    ordered.slice(0, -1).forEach((reading, index) => {
        const boundary = reading.timing.boundaries.at(-1);
        const next = ordered[index + 1];
        const nextStart = next?.timing.words[0]?.start_ms ?? next?.parts[0]?.t[0];
        if (boundary && nextStart !== undefined) {
            boundary.end_ms = Math.max(boundary.end_ms, nextStart);
        }
    });
}

function storedShard(raw: unknown): StoredShard {
    if (!raw || typeof raw !== 'object') throw new Error('Timestamp shard is not an object');
    const shard = raw as StoredShard;
    if (shard._meta?.schema_version !== 13) throw new Error('Timestamp shard is not schema v13');
    if (shard._meta.native_schema_version !== 2) throw new Error('Native schema is not v2');
    if (shard._meta.renderer_codec_version !== 1) {
        throw new Error(`Renderer codec ${String(shard._meta.renderer_codec_version)} is unsupported`);
    }
    if (!Array.isArray(shard.readings)) throw new Error('Timestamp shard has no readings');
    return shard;
}

export function decodeTimestampShard(raw: unknown): TsShardResponse {
    const shard = storedShard(raw);
    const readings = shard.readings.map(readingOf);
    stitchInterReadingPauses(readings);
    return { _meta: shard._meta, readings };
}
