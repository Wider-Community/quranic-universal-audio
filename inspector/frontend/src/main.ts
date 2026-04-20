/**
 * Main entry point — mounts App.svelte and loads global styles.
 */

// Stylesheets — Vite injects these into <head> during dev and extracts them to
// a bundled CSS file in production builds.
import './styles/base.css';
import './styles/components.css';
import './styles/filters.css';
import './styles/history.css';
import './styles/segments.css';
import './styles/stats.css';
import './styles/timestamps.css';
import './styles/validation.css';

import App from './App.svelte';
import { installAudioWarmup } from './lib/utils/audio-warmup';

// Hook the first user gesture to warm the browser's audio decoder + output
// device, so the first chapter Play click doesn't pay that cold cost.
installAudioWarmup();

// Svelte 4 mount API (Svelte 5 uses mount(); Svelte 4 uses the constructor).
const app = new App({ target: document.getElementById('app')! });

export default app;
