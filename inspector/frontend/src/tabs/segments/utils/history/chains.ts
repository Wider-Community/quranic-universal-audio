import type { HistoryBatch, Segment } from '../../../../lib/types/domain';
import type {
    HistorySnapshot,
    SplitChain,
    SplitChainOp,
} from '../../types/segments';

export type { SplitChain, SplitChainOp };

/** Internal result type for `buildSplitChains`. */
export interface BuildChainsResult {
    chains: Map<string, SplitChain>;
    chainedOpIds: Set<string>;
}

interface SplitLineageEntry {
    wfStart: number;
    wfEnd: number;
    audioUrl: string;
}
type SplitLineage = Map<string, SplitLineageEntry>;

export function buildSplitLineage(allBatches: HistoryBatch[]): SplitLineage {
    const lineage: SplitLineage = new Map();
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parent = op.targets_before?.[0] as { segment_uid?: string; time_start?: number; time_end?: number; audio_url?: string } | undefined;
            if (!parent) continue;
            const parentUid = parent.segment_uid;
            const parentCtx: SplitLineageEntry = (parentUid && lineage.has(parentUid))
                ? lineage.get(parentUid)!
                : { wfStart: parent.time_start ?? 0, wfEnd: parent.time_end ?? 0, audioUrl: parent.audio_url ?? '' };
            for (const child of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                // firstHalf's UID now equals parentUid (UID preservation).
                // Recording it as its own lineage descendant would make
                // `buildSplitChains` skip every split as a chain root.
                if (child.segment_uid && child.segment_uid !== parentUid) {
                    lineage.set(child.segment_uid, parentCtx);
                }
            }
        }
    }
    return lineage;
}

export function buildSplitChains(allBatches: HistoryBatch[], splitLineage: SplitLineage): BuildChainsResult {
    const chains = new Map<string, SplitChain>();
    const chained = new Set<string>();
    const uidToChain = new Map<string, string>();

    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (op.op_type !== 'split_segment') continue;
            const parentBefore = op.targets_before?.[0] as { segment_uid?: string } | undefined;
            const parentUid = parentBefore?.segment_uid;
            if (parentUid && splitLineage.has(parentUid)) continue;
            chains.set(op.op_id, {
                rootSnap: op.targets_before?.[0] as HistorySnapshot | undefined,
                rootBatch: batch,
                ops: [{ op, batch }],
                latestDate: batch.saved_at_utc || '',
            });
            chained.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, op.op_id);
            }
        }
    }

    const _CHAIN_ABSORB_OPS = new Set(['trim_segment', 'split_segment', 'edit_reference', 'confirm_reference']);
    for (const batch of allBatches) {
        for (const op of (batch.operations || [])) {
            if (chained.has(op.op_id)) continue;
            if (!_CHAIN_ABSORB_OPS.has(op.op_type)) continue;
            const beforeUids = ((op.targets_before || []) as Array<{ segment_uid?: string }>).map((s) => s.segment_uid).filter((u): u is string => !!u);
            let chainId: string | null = null;
            for (const uid of beforeUids) { if (uidToChain.has(uid)) { chainId = uidToChain.get(uid)!; break; } }
            if (!chainId) continue;
            const chain = chains.get(chainId);
            if (!chain) continue;
            chain.ops.push({ op, batch });
            if ((batch.saved_at_utc || '') > chain.latestDate) chain.latestDate = batch.saved_at_utc || '';
            chained.add(op.op_id);
            for (const snap of (op.targets_after || []) as Array<{ segment_uid?: string }>) {
                if (snap.segment_uid) uidToChain.set(snap.segment_uid, chainId);
            }
        }
    }

    return { chains, chainedOpIds: chained };
}

export function computeChainLeafSnaps(chain: SplitChain): HistorySnapshot[] {
    const finalSnaps = new Map<string, HistorySnapshot>();
    const beforeUids = new Set<string>();
    for (const { op } of chain.ops) {
        const afterUids = new Set<string>(((op.targets_after || []) as HistorySnapshot[]).map((s) => s.segment_uid).filter((u): u is string => !!u));
        for (const snap of ((op.targets_before || []) as HistorySnapshot[])) { if (snap.segment_uid && !afterUids.has(snap.segment_uid)) beforeUids.add(snap.segment_uid); }
        for (const snap of ((op.targets_after || []) as HistorySnapshot[])) { if (snap.segment_uid) finalSnaps.set(snap.segment_uid, snap); }
    }
    return [...finalSnaps.entries()].filter(([uid]) => !beforeUids.has(uid)).map(([, snap]) => snap).sort((a, b) => a.time_start - b.time_start);
}

export function getChainBatchIds(chain: SplitChain): string[] {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (let i = chain.ops.length - 1; i >= 0; i--) {
        const batchId = chain.ops[i]?.batch?.batch_id;
        if (batchId && !seen.has(batchId)) {
            seen.add(batchId);
            ids.push(batchId);
        }
    }
    return ids;
}

export function snapToSeg(snap: HistorySnapshot, chapter: number | null): Segment {
    return {
        index: snap.index_at_save ?? 0,
        entry_idx: 0,
        chapter: chapter ?? undefined,
        audio_url: snap.audio_url || '',
        time_start: snap.time_start, time_end: snap.time_end,
        matched_ref: snap.matched_ref || '', matched_text: snap.matched_text || '',
        display_text: snap.display_text || '', confidence: snap.confidence ?? 0,
        ...(snap.wrap_word_ranges ? { wrap_word_ranges: snap.wrap_word_ranges } : {}),
        ...(snap.has_repeated_words ? { has_repeated_words: true } : {}),
    };
}
