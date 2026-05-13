import type { EditOp } from '../../../../lib/types/domain';

interface SaveSegmentPayloadPatch {
    index: number;
    segment_uid: string;
    matched_ref: string;
    matched_text: string;
    confidence: number;
    ignored_categories?: string[];
}

interface CommandResultLike {
    operation: EditOp & { type?: string; [k: string]: unknown };
    affectedChapters?: number[];
    patch?: unknown;
    [k: string]: unknown;
}

/**
 * Build a partial save payload from a `CommandResult`.
 *
 * The returned object carries the same `{segments, operations}` envelope that
 * `/api/seg/save` accepts; callers fill `segments` from the mutated chapters.
 */
export function buildPayloadFromCommandResult(result: CommandResultLike): {
    segments: SaveSegmentPayloadPatch[];
    operations: EditOp[];
    affected_chapters: number[];
} {
    const op: EditOp & { patch?: unknown } = { ...result.operation };
    if (op.patch === undefined && result.patch != null) {
        op.patch = result.patch as EditOp['patch'];
    }
    return {
        segments: [],
        operations: [op],
        affected_chapters: result.affectedChapters ?? [],
    };
}
