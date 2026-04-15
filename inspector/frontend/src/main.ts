/**
 * Main entry point — mounts App.svelte, imports all tab modules for side-effect
 * registration (DOMContentLoaded handlers), and loads global styles.
 */

// Stylesheets — Vite injects these into <head> during dev and extracts them to
// a bundled CSS file in production builds.
// Note: audio-tab.css is ported to scoped <style> in tabs/audio/AudioTab.svelte (Wave 11b).
import './styles/base.css';
import './styles/components.css';
import './styles/filters.css';
import './styles/history.css';
import './styles/segments.css';
import './styles/stats.css';
import './styles/timestamps.css';
import './styles/validation.css';
// Static imports — module-level code in each tab runs immediately,
// registering DOMContentLoaded handlers before the event fires.
// NOTE: timestamps/index is intentionally not imported — the Wave-4
// Svelte conversion (TimestampsTab.svelte) supersedes it. The .ts files
// remain on disk for bisect clarity but are deleted in sub-wave 4b.
// NOTE: audio/index.ts removed — AudioTab.svelte (Wave 11b) supersedes it.
import './segments/index';

import App from './App.svelte';

// Svelte 4 mount API (Svelte 5 uses mount(); Svelte 4 uses the constructor).
const app = new App({ target: document.getElementById('app')! });

export default app;
