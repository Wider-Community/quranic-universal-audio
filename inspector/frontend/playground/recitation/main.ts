/**
 * Throwaway playground entry — NOT part of the production build.
 *
 * Served by Vite dev only (the prod build's rollup input is just index.html).
 * Mounts the recitation-animation components against real shard + audio data
 * (via the dev backend / bucket mount) with a live control panel so the look,
 * easings, latencies, icons, and styling can be tuned, then locked into
 * `lib/recitation-animation/config.ts`.
 */
import { mount } from 'svelte';

import '../../src/styles/tokens.css';
// base.css carries the DigitalKhatt @font-face (→ /fonts/DigitalKhattV2.otf)
// the dataset's display text is designed for. In the real app it's loaded
// globally; the playground pulls it in so live + demo text render correctly.
import '../../src/styles/base.css';
import Playground from './Playground.svelte';

const target = document.getElementById('app');
if (!target) throw new Error('playground: #app missing');

mount(Playground, { target });
