import { describe, expect, it, vi } from 'vitest';

import { makeAudioStub } from '../../../../lib/playback/__tests__/raf-harness';
import { AudioPort } from '../../../../lib/playback/audio-port';
import type { TsLoadedVerse } from '../../stores/verse';
import { loadTimestampsAudio } from '../audio-load';

vi.mock('../../../../lib/playback/audio-graph', () => ({
    cutAudio: vi.fn(),
    getAudioGraph: vi.fn(() => null),
    uncutAudio: vi.fn(),
}));

const loaded = (offsetSec: number, endSec: number): TsLoadedVerse => ({
    data: { words: [], intervals: [] } as any,
    tsSegOffset: offsetSec,
    tsSegEnd: endSec,
});

describe('loadTimestampsAudio', () => {
    it('uses AudioPort VBR clip routing and seeks in file-absolute time', async () => {
        const audio = makeAudioStub();
        const port = new AudioPort();
        port.attachElement(audio as unknown as HTMLAudioElement);
        port.setSource({
            audioUrl: 'https://cdn.example/chapter.mp3',
            cbrSrc: 'https://cdn.example/chapter.mp3',
            reciter: 'reciter_a',
            vbr: true,
        });

        const pending = loadTimestampsAudio(port, loaded(5, 7), 5, true);

        expect(audio.src).toBe(
            '/api/seg/segment-clip/reciter_a?url=https%3A%2F%2Fcdn.example%2Fchapter.mp3&start_ms=5000&end_ms=7000',
        );
        audio._fireEvent('canplay');
        await pending;

        expect(audio.currentTime).toBe(0);
        expect(audio.play).toHaveBeenCalledTimes(1);
    });
});
