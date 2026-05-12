import type { EditOp } from '../../../../lib/types/domain';
import type { GuideExample, GuidePeakRecord } from '../types';

const AUDIO_URL = 'https://example.test/guide-audio.mp3';
const PEAKS: GuidePeakRecord[] = [
    {
        op_id: 'guide-op-ref',
        url: AUDIO_URL,
        start_ms: 1000,
        end_ms: 4200,
        duration_ms: 3200,
        peaks: [[-0.1, 0.2], [-0.24, 0.32], [-0.12, 0.18], [-0.18, 0.28]],
    },
    {
        op_id: 'guide-op-trim',
        url: AUDIO_URL,
        start_ms: 5200,
        end_ms: 9000,
        duration_ms: 3800,
        peaks: [[-0.06, 0.14], [-0.2, 0.34], [-0.28, 0.4], [-0.1, 0.16]],
    },
    {
        op_id: 'guide-op-split',
        url: AUDIO_URL,
        start_ms: 10000,
        end_ms: 15400,
        duration_ms: 5400,
        peaks: [[-0.08, 0.2], [-0.22, 0.38], [-0.3, 0.42], [-0.14, 0.24], [-0.26, 0.36]],
    },
];

function op(overrides: Partial<EditOp>): EditOp {
    return {
        op_id: 'guide-op',
        op_type: 'edit_reference',
        op_context_category: 'low_confidence',
        fix_kind: 'manual',
        started_at_utc: '',
        applied_at_utc: '',
        ready_at_utc: '',
        targets_before: [],
        targets_after: [],
        ...overrides,
    };
}

export const guideExamples: Readonly<Record<string, GuideExample>> = Object.freeze({
    low_conf_reference_correction: {
        id: 'low_conf_reference_correction',
        title: 'Reference correction',
        description: 'The audio matches the next word range, so only the reference changes.',
        render: 'history_op',
        chapter: 1,
        operations: [
            op({
                op_id: 'guide-op-ref',
                op_type: 'edit_reference',
                targets_before: [{
                    segment_uid: 'guide-ref-before',
                    index_at_save: 4,
                    audio_url: AUDIO_URL,
                    time_start: 1200,
                    time_end: 3900,
                    matched_ref: '1:1:1-1:1:2',
                    matched_text: '',
                    confidence: 0.51,
                }],
                targets_after: [{
                    segment_uid: 'guide-ref-after',
                    index_at_save: 4,
                    audio_url: AUDIO_URL,
                    time_start: 1200,
                    time_end: 3900,
                    matched_ref: '1:1:2-1:1:3',
                    matched_text: '',
                    confidence: 0.91,
                }],
            }),
        ],
        peaks: PEAKS.filter((p) => p.op_id === 'guide-op-ref'),
    },
    low_conf_trim_timing: {
        id: 'low_conf_trim_timing',
        title: 'Timing trim',
        description: 'The text is already right, but the segment starts too early.',
        render: 'history_op',
        chapter: 1,
        operations: [
            op({
                op_id: 'guide-op-trim',
                op_type: 'trim_segment',
                targets_before: [{
                    segment_uid: 'guide-trim-before',
                    index_at_save: 5,
                    audio_url: AUDIO_URL,
                    time_start: 5400,
                    time_end: 8800,
                    matched_ref: '1:2:1-1:2:2',
                    matched_text: '',
                    confidence: 0.56,
                }],
                targets_after: [{
                    segment_uid: 'guide-trim-after',
                    index_at_save: 5,
                    audio_url: AUDIO_URL,
                    time_start: 6100,
                    time_end: 8600,
                    matched_ref: '1:2:1-1:2:2',
                    matched_text: '',
                    confidence: 0.83,
                }],
            }),
        ],
        peaks: PEAKS.filter((p) => p.op_id === 'guide-op-trim'),
    },
    low_conf_split_phrase: {
        id: 'low_conf_split_phrase',
        title: 'Split a long phrase',
        description: 'A long low-confidence segment can be clearer as two smaller segments.',
        render: 'edit_chain',
        chapter: 1,
        operations: [
            op({
                op_id: 'guide-op-split',
                op_type: 'split_segment',
                targets_before: [{
                    segment_uid: 'guide-split-before',
                    index_at_save: 6,
                    audio_url: AUDIO_URL,
                    time_start: 10200,
                    time_end: 15200,
                    matched_ref: '1:3:1-1:3:4',
                    matched_text: '',
                    confidence: 0.58,
                }],
                targets_after: [
                    {
                        segment_uid: 'guide-split-left',
                        index_at_save: 6,
                        audio_url: AUDIO_URL,
                        time_start: 10200,
                        time_end: 12500,
                        matched_ref: '1:3:1-1:3:2',
                        matched_text: '',
                        confidence: 0.84,
                    },
                    {
                        segment_uid: 'guide-split-right',
                        index_at_save: 7,
                        audio_url: AUDIO_URL,
                        time_start: 12500,
                        time_end: 15200,
                        matched_ref: '1:3:3-1:3:4',
                        matched_text: '',
                        confidence: 0.86,
                    },
                ],
            }),
        ],
        peaks: PEAKS.filter((p) => p.op_id === 'guide-op-split'),
    },
});

export function getGuideExample(id: string): GuideExample | null {
    return guideExamples[id] ?? null;
}
