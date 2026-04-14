/**
 * Main entry point — mounts App.svelte, imports all tab modules for side-effect
 * registration (DOMContentLoaded handlers), and loads global styles.
 */

// Stylesheets — Vite injects these into <head> during dev and extracts them to
// a bundled CSS file in production builds.
import './styles/base.css';
import './styles/components.css';
import './styles/timestamps.css';
import './styles/segments.css';
import './styles/validation.css';
import './styles/history.css';
import './styles/stats.css';
import './styles/filters.css';
import './styles/audio-tab.css';
// Static imports — module-level code in each tab runs immediately,
// registering DOMContentLoaded handlers before the event fires.
import './timestamps/index';
import './segments/index';
import './audio/index';

import App from './App.svelte';

// Svelte 4 mount API (Svelte 5 uses mount(); Svelte 4 uses the constructor).
const app = new App({ target: document.getElementById('app')! });

export default app;
