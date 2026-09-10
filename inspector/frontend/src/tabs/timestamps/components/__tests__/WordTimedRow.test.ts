import { cleanup, render, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { dashPort } from '../../../../lib/playback/dash-port';
import { decodeTimestampShard } from '../../../../lib/recitation-data/compact-shards';
import { WORD_SHARD, WORD_TEXTS } from '../../../../lib/recitation-data/test-word-fixture';
import { assembleOccasion, shardOccasions } from '../../../../lib/recitation-data/ts-source';
import type { TsWordShardResponse } from '../../../../lib/types/ts-client';
import { deliveryRiwayah } from '../../stores/display';
import { loopTarget } from '../../stores/playback';
import { enterTiming, exitReportMode, staged } from '../../stores/report-mode';
import { focusWaslGroup, loadedVerse } from '../../stores/verse';
import WordTimedRow from '../WordTimedRow.svelte';

function seedVerse() {
    const shard = decodeTimestampShard(WORD_SHARD) as TsWordShardResponse;
    const data = assembleOccasion(
        'r', shardOccasions(shard)[0]!, {}, {},
        { audio_category: 'by_surah' }, '',
    );
    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: 3 });
    deliveryRiwayah.set(shard._meta.riwayah);
    return data;
}

describe('WordTimedRow', () => {
    beforeEach(() => {
        loadedVerse.set(null);
        focusWaslGroup.set(null);
        deliveryRiwayah.set('hafs');
    });

    afterEach(() => {
        vi.restoreAllMocks();
        cleanup();
        exitReportMode();
        loopTarget.set(null);
        loadedVerse.set(null);
        focusWaslGroup.set(null);
        deliveryRiwayah.set('hafs');
    });

    it('renders one word cell per word in the edition text', async () => {
        seedVerse();
        const { container } = render(WordTimedRow);
        await waitFor(() =>
            expect(container.querySelectorAll('[data-qc-word-id]')).toHaveLength(4));
        const texts = [...container.querySelectorAll('.word-text')].map((el) => el.textContent);
        expect(texts).toEqual(WORD_TEXTS);
    });

    it('renders no letter, column or sound hooks', async () => {
        // The whole point of the profile: there is nothing below the word.
        seedVerse();
        const { container } = render(WordTimedRow);
        await waitFor(() =>
            expect(container.querySelectorAll('[data-qc-word-id]')).toHaveLength(4));
        expect(container.querySelectorAll('[data-qc-column-id]')).toHaveLength(0);
        expect(container.querySelectorAll('[data-qc-sound-id]')).toHaveLength(0);
        expect(container.querySelectorAll('[data-qc-bridge-id]')).toHaveLength(0);
    });

    it('omits the U+06DD ornament for a QPC-font edition', async () => {
        // Qalun's packaged font draws the circle around the digits itself, so
        // sending the ornament too would nest two of them.
        seedVerse();
        const { container } = render(WordTimedRow);
        await waitFor(() => expect(container.querySelector('.verse-mark')).not.toBeNull());
        expect(container.querySelector('.verse-mark')?.textContent).toBe('١');
    });

    it('keeps the ornament for a Hafs word shard', async () => {
        seedVerse();
        deliveryRiwayah.set('hafs');
        const { container } = render(WordTimedRow);
        await waitFor(() => expect(container.querySelector('.verse-mark')).not.toBeNull());
        expect(container.querySelector('.verse-mark')?.textContent).toBe('۝١');
    });

    it('activates the word under the playhead', async () => {
        seedVerse();
        vi.spyOn(dashPort, 'currentTimeMs').mockReturnValue(1_000);
        const { component, container } = render(WordTimedRow);
        await waitFor(() =>
            expect(container.querySelectorAll('[data-qc-word-id]')).toHaveLength(4));
        (component as unknown as { updateHighlights: () => void }).updateHighlights();

        const active = container.querySelectorAll('[data-qc-word-id].active');
        expect(active).toHaveLength(1);
        expect(active[0]!.getAttribute('data-qc-word-id')).toBe('1');
    });

    it('activates the pause gap when the playhead sits inside it', async () => {
        seedVerse();
        vi.spyOn(dashPort, 'currentTimeMs').mockReturnValue(750);
        const { component, container } = render(WordTimedRow);
        await waitFor(() =>
            expect(container.querySelectorAll('[data-qc-boundary-id]')).toHaveLength(4));
        (component as unknown as { updateHighlights: () => void }).updateHighlights();

        expect(container.querySelector('[data-qc-boundary-id="1"]')?.classList)
            .toContain('active');
        expect(container.querySelectorAll('[data-qc-word-id].active')).toHaveLength(0);
    });

    it('stages a timing report against the word target', async () => {
        seedVerse();
        const { container } = render(WordTimedRow);
        await waitFor(() =>
            expect(container.querySelectorAll('[data-qc-word-id]')).toHaveLength(4));
        enterTiming('r', '112:1');
        container.querySelector<HTMLElement>('[data-qc-word-id="2"]')!.click();

        const entries = [...get(staged).values()];
        expect(entries).toHaveLength(1);
        expect(entries[0]!.target).toEqual({ reading_id: 'r1', kind: 'word', target_id: '2' });
    });
});
