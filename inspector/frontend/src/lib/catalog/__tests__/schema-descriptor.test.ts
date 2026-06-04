import { describe, expect, it } from 'vitest';

import type { PublicDelivery } from '../../types/public-state';
import { buildSchemaDescriptor } from '../schema-descriptor';

function delivery(overrides: Partial<PublicDelivery> = {}): PublicDelivery {
    return {
        slug: 'test_slug',
        riwayah: 'hafs',
        style: 'murattal',
        recording_context: null,
        recording_year: null,
        source: 'mp3quran',
        channel: 'mp3quran',
        channel_name: 'mp3quran',
        source_url: null,
        audio_category: 'by_surah',
        chapter_count: 114,
        coverage_kind: 'full',
        state_since: null,
        bitrate_kbps_nominal: 128,
        bitrate_mode: 'cbr',
        total_duration_sec: null,
        bucket: 'published',
        ...overrides,
    };
}

describe('buildSchemaDescriptor', () => {
    it('orders non-status axes by overall combination count desc', () => {
        const d = buildSchemaDescriptor([
            delivery({ riwayah: 'hafs', style: 'murattal' }),
            delivery({ riwayah: 'hafs', style: 'mujawwad' }),
            delivery({ riwayah: 'warsh', style: 'mujawwad' }),
        ]);
        const riwayah = d.axes.find((a) => a.key === 'riwayah')!;
        expect(riwayah.options.map((o) => o.key)).toEqual(['hafs', 'warsh']);
        const style = d.axes.find((a) => a.key === 'style')!;
        expect(style.options.map((o) => o.key)).toEqual(['mujawwad', 'murattal']);
    });

    it('always includes a status axis in the fixed priority order', () => {
        const d = buildSchemaDescriptor([delivery()]);
        const status = d.axes.find((a) => a.key === 'status')!;
        expect(status.options.map((o) => o.key)).toEqual([
            'published',
            'under_review',
            'available_for_review',
            'requested',
            'available_for_request',
        ]);
    });

    it('includes a coverage axis with full/partial only', () => {
        const d = buildSchemaDescriptor([delivery()]);
        const coverage = d.axes.find((a) => a.key === 'coverage')!;
        expect(coverage.options.map((o) => o.key)).toEqual(['full', 'partial']);
    });

    it('omits the recording_context axis when no combination has one', () => {
        const d = buildSchemaDescriptor([delivery({ recording_context: null })]);
        expect(d.axes.find((a) => a.key === 'recording_context')).toBeUndefined();
    });

    it('includes the recording_context axis when at least one combination has one', () => {
        const d = buildSchemaDescriptor([delivery({ recording_context: 'studio' })]);
        const ax = d.axes.find((a) => a.key === 'recording_context')!;
        expect(ax.options.map((o) => o.key)).toEqual(['studio']);
    });

    it('drops the source axis (use channel instead)', () => {
        const d = buildSchemaDescriptor([delivery()]);
        expect(d.axes.find((a) => a.key === 'source')).toBeUndefined();
    });

    it('exposes a channel axis sorted by combination count desc', () => {
        const d = buildSchemaDescriptor([
            delivery({ channel: 'mp3quran' }),
            delivery({ channel: 'mp3quran' }),
            delivery({ channel: 'quranicaudio' }),
        ]);
        const ax = d.axes.find((a) => a.key === 'channel')!;
        expect(ax.options.map((o) => o.key)).toEqual(['mp3quran', 'quranicaudio']);
    });

    it('tagsOf wires axes to the correct delivery fields per axis', () => {
        // Walk every axis and assert tagsOf returns the slug for the field
        // it claims to drive — catches an accidental swap (e.g. status reading
        // from coverage_kind). The prior single-axis assertion exercised only
        // the trivial channel identity, which is true for any input.
        const row = delivery({
            channel: 'tarteel',
            riwayah: 'hafs',
            style: 'murattal',
            status: 'published',
            coverage_kind: 'full',
        });
        const d = buildSchemaDescriptor([row]);
        const expectations: Record<string, string> = {
            channel: 'tarteel',
            riwayah: 'hafs',
            style: 'murattal',
            status: 'published',
            coverage: 'full',
        };
        for (const [axisKey, expected] of Object.entries(expectations)) {
            const axis = d.axes.find((a) => a.key === axisKey);
            if (!axis) continue; // tolerate axes that aren't in this descriptor
            expect(Array.from(axis.tagsOf(row))).toContain(expected);
        }
    });
});
