/**
 * Analysis-view render harness (dev / screenshot tool). Mounts the REAL
 * `UnifiedDisplay` for one reciter:verse straight from shards via the REAL
 * `ts-source` assembly — no SPA, no audio, no waveform, no progress-bar math.
 *
 * Driven by URL params: `?reciter=<slug>&ref=45:32[&words=1-3]`. `/api` is
 * proxied to a backend (set `INSPECTOR_API_TARGET` to the dev Space so no local
 * Flask is needed). Because it imports the production component + assembly,
 * there is zero rendering drift — TypeScript fails the build if their API moves.
 *
 * Driven headlessly by `.claude/skills/inspector-playwright/scripts/shoot.mjs`,
 * which waits for `document.body.dataset.ready` and screenshots `#app`.
 */
import '../src/styles/tokens.css';
import '../src/styles/base.css';
import '../src/styles/timestamps.css';

import { mount } from 'svelte';

import {
    assembleVerseFromShard,
    loadChapterShard,
    loadDk,
    loadManifest,
    loadQpc,
    reciterAudioFromManifest,
} from '../src/lib/recitation-data/ts-source';
import UnifiedDisplay from '../src/tabs/timestamps/components/UnifiedDisplay.svelte';
import { loadedVerse } from '../src/tabs/timestamps/stores/verse';

async function render(): Promise<void> {
    const p = new URLSearchParams(location.search);
    const reciter = p.get('reciter');
    const ref = p.get('ref'); // e.g. "45:32"
    if (!reciter || !ref) throw new Error('need ?reciter=<slug>&ref=<surah:verse>');
    const chapter = parseInt(ref.split(':')[0] ?? '0', 10);

    const manifest = await loadManifest();
    const reciterAudio = reciterAudioFromManifest(manifest, reciter);
    if (!reciterAudio) throw new Error(`reciter not advertised by the TS manifest: ${reciter}`);

    const [shard, qpc, dk] = await Promise.all([
        loadChapterShard(reciter, chapter),
        loadQpc(),
        loadDk(),
    ]);

    // Exactly the app's call (load-chapter.ts) — chapterAudioUrl is unused for render.
    const data = assembleVerseFromShard(reciter, shard, ref, qpc, dk, reciterAudio, '');
    if (!data) throw new Error(`no verse ${ref} in ${reciter} chapter ${chapter}`);

    // Optional narrow word range (1-based, inclusive): `&words=1-3` or `&words=2`.
    const range = p.get('words');
    if (range) {
        const [a, b] = range.split('-').map((n) => parseInt(n, 10));
        data.words = data.words.slice(a - 1, (Number.isNaN(b) ? a : b));
    }

    loadedVerse.set({ data, tsSegOffset: 0, tsSegEnd: Number.MAX_SAFE_INTEGER });
    mount(UnifiedDisplay, { target: document.getElementById('app')! });

    // Let web fonts + recomputeRowGap (ResizeObserver) settle before flagging ready.
    await (document as unknown as { fonts?: { ready: Promise<unknown> } }).fonts?.ready;
    requestAnimationFrame(() =>
        requestAnimationFrame(() => { document.body.dataset.ready = '1'; }),
    );
}

render().catch((e) => {
    document.body.dataset.error = String(e?.message ?? e);
     
    console.error(e);
});
