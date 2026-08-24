import { parse } from '@quranic-phonemizer/cells';
import { describe, expect, it } from 'vitest';

import { nativeReading } from '../../../../lib/recitation-data/test-native-fixture';
import { defineInspectorRule } from '../tajweed-rules';
import {
    buildBoundaryPolicies,
    columnSpans,
    type ParsedReading,
} from '../timed-entities';

function parsed(reading: ReturnType<typeof nativeReading>): ParsedReading {
    const result = parse(reading.wire, defineInspectorRule);
    return { reading, ...result };
}

describe('native timing ownership', () => {
    it('times merger presenters but never a silent presenter', () => {
        const reading = nativeReading('r1', [
            { ref: '1:1', start: 100, end: 200, text: 'a' },
            { ref: '1:1', start: 200, end: 400, text: 'b' },
        ]);
        const first = reading.wire.cells.cell_view.words[0]!.columns[0]!;
        const second = reading.wire.cells.cell_view.words[1]!.columns[0]!;
        first.owned_sound_ids = [0];
        first.presented_sound_ids = [1];
        second.owned_sound_ids = [];
        second.presented_sound_ids = [1];
        reading.wire.cells.cell_view.words[1]!.sounds[0]!.column_ids = [];

        let spans = columnSpans(parsed(reading));
        expect(spans.get(String(first.id))).toEqual([100, 400]);
        expect(spans.get(String(second.id))).toEqual([200, 400]);

        second.silence = 'orthographic_silence';
        spans = columnSpans(parsed(reading));
        expect(spans.has(String(second.id))).toBe(false);
    });

    it('derives a pause across reading boundaries and keeps verse markers static', () => {
        const first = parsed(nativeReading('r1', [
            { ref: '1:1', start: 100, end: 200, text: 'a' },
        ]));
        first.view.boundaries[0]!.verse_end = null;
        const second = parsed(nativeReading('r2', [
            { ref: '1:1', start: 350, end: 500, text: 'b' },
        ]));
        const policies = buildBoundaryPolicies([first, second]);

        expect(policies.get('r1')?.get('1')).toMatchObject({
            span: [200, 350], recordedPause: true, showMarker: true, verseEnd: false,
        });
        expect(policies.get('r2')?.get('1')).toMatchObject({
            recordedPause: false, showMarker: true, verseEnd: true,
        });
    });
});
