/**
 * Main entry point -- tab switching, tab module imports.
 * Single <script type="module"> loaded by index.html.
 *
 * Static imports ensure all tab modules register their DOMContentLoaded
 * handlers before the event fires (modules execute before DOMContentLoaded).
 */

// Stylesheets — order matches the original <link> tag order in index.html.
// Vite injects these into <head> during dev and extracts them to a bundled
// CSS file in production builds.
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

import { getActiveTab, setActiveTab } from './lib/utils/active-tab';
import { LS_KEYS } from './lib/utils/constants';

function setupTabSwitching(): void {
    const panels = ['timestamps', 'segments', 'audio'];
    document.querySelectorAll<HTMLElement>('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            if (!tab) return;
            setActiveTab(tab);
            const current = getActiveTab();
            localStorage.setItem(LS_KEYS.ACTIVE_TAB, current);
            panels.forEach(p => {
                const panel = document.getElementById(p + '-panel');
                if (panel) panel.hidden = (current !== p);
            });
            // Pause audio from other tabs (use getElementById to avoid importing tab state)
            if (current !== 'timestamps') {
                const tsAudio = document.getElementById('audio-player') as HTMLAudioElement | null;
                if (tsAudio) tsAudio.pause();
            }
            if (current !== 'segments') {
                const segAudio = document.getElementById('seg-audio-player') as HTMLAudioElement | null;
                if (segAudio) segAudio.pause();
                // valCardAudio is created dynamically by error-card-audio.ts;
                // we find it via the DOM by checking all <audio> elements in the segments panel
                const segPanel = document.getElementById('segments-panel');
                if (segPanel) {
                    segPanel.querySelectorAll<HTMLAudioElement>('audio').forEach(a => { if (a.id !== 'seg-audio-player') a.pause(); });
                }
            }
            if (current !== 'audio') {
                const audPlayer = document.getElementById('aud-player') as HTMLAudioElement | null;
                if (audPlayer) audPlayer.pause();
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupTabSwitching();

    // Restore active tab last
    const savedTab = localStorage.getItem(LS_KEYS.ACTIVE_TAB);
    if (savedTab) {
        const tabBtn = document.querySelector<HTMLElement>(`.tab-btn[data-tab="${savedTab}"]`);
        if (tabBtn) tabBtn.click();
    }
});
