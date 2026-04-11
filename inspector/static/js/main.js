/**
 * Main entry point -- tab switching, tab module imports.
 * Single <script type="module"> loaded by index.html.
 *
 * Static imports ensure all tab modules register their DOMContentLoaded
 * handlers before the event fires (modules execute before DOMContentLoaded).
 */

import { LS_KEYS } from './shared/constants.js';

// Static imports — module-level code in each tab runs immediately,
// registering DOMContentLoaded handlers before the event fires.
import './timestamps.js';
import './segments.js';
import './audio/index.js';

let activeTab = 'timestamps';

export function getActiveTab() {
    return activeTab;
}

function setupTabSwitching() {
    const panels = ['timestamps', 'segments', 'audio'];
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            activeTab = btn.dataset.tab;
            localStorage.setItem(LS_KEYS.ACTIVE_TAB, activeTab);
            panels.forEach(p => {
                document.getElementById(p + '-panel').hidden = (activeTab !== p);
            });
            // Pause audio from other tabs (use getElementById to avoid importing tab state)
            if (activeTab !== 'timestamps') {
                const tsAudio = document.getElementById('audio-player');
                if (tsAudio) tsAudio.pause();
            }
            if (activeTab !== 'segments') {
                const segAudio = document.getElementById('seg-audio-player');
                if (segAudio) segAudio.pause();
                // valCardAudio is a module-scoped variable in segments.js;
                // we find it via the DOM by checking all <audio> elements in the segments panel
                const segPanel = document.getElementById('segments-panel');
                if (segPanel) {
                    segPanel.querySelectorAll('audio').forEach(a => { if (a.id !== 'seg-audio-player') a.pause(); });
                }
            }
            if (activeTab !== 'audio') {
                const audPlayer = document.getElementById('aud-player');
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
        const tabBtn = document.querySelector(`.tab-btn[data-tab="${savedTab}"]`);
        if (tabBtn) tabBtn.click();
    }
});
