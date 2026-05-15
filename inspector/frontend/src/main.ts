/**
 * Main entry point — mounts App.svelte and loads global styles.
 */

// Stylesheets — Vite injects these into <head> during dev and extracts them to
// a bundled CSS file in production builds.
//
// tokens.css MUST stay first: it defines :root custom properties consumed by
// every subsequent stylesheet. tokens.css has no selectors, so this position
// can never override base.css.
import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/filters.css';
import './styles/history.css';
import './styles/segments.css';
import './styles/stats.css';
import './styles/timestamps.css';
import './styles/validation.css';
import './styles/combination-picker.css';

import { mount } from 'svelte';

import App from './App.svelte';
import { installAudioWarmup } from './lib/utils/audio-warmup';

// Hook the first user gesture to warm the browser's audio decoder + output
// device, so the first chapter Play click doesn't pay that cold cost.
installAudioWarmup();

// Svelte 5 mount API. App.svelte and its descendants still use legacy
// runes-free syntax (export let / on:click / $:); they keep working in
// Svelte 5 via the compatibility shim until the migration plan in
// docs/svelte-5-migration.md walks each file forward to runes.
const app = mount(App, { target: document.getElementById('app')! });

export default app;
