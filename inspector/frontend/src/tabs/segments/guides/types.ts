import type { EditOp, PeakBucket } from '../../../lib/types/domain';

export interface GuidePeakRecord {
    op_id: string;
    url: string;
    start_ms: number;
    end_ms: number;
    duration_ms: number;
    peaks: PeakBucket[];
}

export interface GuideExample {
    id: string;
    title: string;
    description?: string;
    render: 'history_op' | 'edit_chain';
    chapter: number | null;
    operations: EditOp[];
    peaks?: GuidePeakRecord[];
}

export type GuideBlock =
    | { type: 'heading'; level: 1 | 2; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'example'; id: string }
    | { type: 'missing'; message: string };
