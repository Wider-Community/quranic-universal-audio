/**
 * Requests Tab — submit reciter segmentation requests and view pipeline status.
 * POSTs to the Reciter Requests HF Space API; no local tokens needed.
 */

(function () {
    const reciterSelect = document.getElementById('req-reciter-select');
    const minSilenceInput = document.getElementById('req-min-silence');
    const nameInput = document.getElementById('req-name');
    const emailInput = document.getElementById('req-email');
    const notesInput = document.getElementById('req-notes');
    const submitBtn = document.getElementById('req-submit-btn');
    const submitStatus = document.getElementById('req-submit-status');
    const processedContainer = document.getElementById('req-processed-table');
    const statusContainer = document.getElementById('req-status-table');

    let SPACE_URL = '';
    let reqReciterSS = null;

    document.addEventListener('DOMContentLoaded', init);

    async function init() {
        try {
            const cfg = await fetch('/api/req/config').then(r => r.json());
            SPACE_URL = cfg.space_url;
        } catch (e) {
            console.error('Failed to load request config:', e);
            return;
        }
        await surahInfoReady;
        reqReciterSS = new SearchableSelect(reciterSelect);

        submitBtn.addEventListener('click', submitRequest);

        loadReciters();
        loadProcessed();
        loadRequests();
    }

    // ── Reciter dropdown ────────────────────────────────────────────
    async function loadReciters() {
        reciterSelect.innerHTML = '<option value="">Loading reciters...</option>';
        try {
            const resp = await fetch(SPACE_URL + '/api/reciters', {
                signal: AbortSignal.timeout(60000),
            });
            const data = await resp.json();
            populateReciters(data.reciters || []);
        } catch (e) {
            reciterSelect.innerHTML = '<option value="">Failed to load (Space may be starting up)</option>';
            console.error('Failed to load reciters:', e);
        }
    }

    function populateReciters(reciters) {
        reciterSelect.innerHTML = '<option value="">-- Select reciter --</option>';

        // Group by source
        const groups = {};
        for (const r of reciters) {
            if (r.has_pending_request) continue;
            const src = r.source || 'unknown';
            if (!groups[src]) groups[src] = [];
            groups[src].push(r);
        }

        for (const [source, recs] of Object.entries(groups).sort()) {
            const og = document.createElement('optgroup');
            og.label = source;
            for (const r of recs.sort((a, b) => a.name.localeCompare(b.name))) {
                const opt = document.createElement('option');
                opt.value = JSON.stringify({
                    slug: r.slug,
                    name: r.name,
                    source: r.source,
                });
                opt.textContent = r.name;
                og.appendChild(opt);
            }
            reciterSelect.appendChild(og);
        }

        if (reqReciterSS) reqReciterSS.refresh();
    }

    // ── Processed reciters reference ────────────────────────────────
    async function loadProcessed() {
        processedContainer.innerHTML = '<p style="color:#888">Loading...</p>';
        try {
            const resp = await fetch(SPACE_URL + '/api/processed', {
                signal: AbortSignal.timeout(60000),
            });
            const data = await resp.json();
            renderProcessed(data.reciters || []);
        } catch (e) {
            processedContainer.innerHTML = '<p style="color:#888">Failed to load</p>';
        }
    }

    function renderProcessed(reciters) {
        if (!reciters.length) {
            processedContainer.innerHTML = '<p style="color:#888">No processed reciters yet</p>';
            return;
        }
        let html = '<table class="req-table"><thead><tr>'
            + '<th>Reciter</th><th>Source</th><th>Min Silence</th>'
            + '</tr></thead><tbody>';
        for (const r of reciters) {
            html += '<tr>'
                + `<td>${esc(r.name)}</td>`
                + `<td>${esc(String(r.audio_source || '?'))}</td>`
                + `<td>${esc(String(r.min_silence_ms || '?'))}ms</td>`
                + '</tr>';
        }
        html += '</tbody></table>';
        processedContainer.innerHTML = html;
    }

    // ── Request status dashboard ────────────────────────────────────
    async function loadRequests() {
        statusContainer.innerHTML = '<p style="color:#888">Loading...</p>';
        try {
            const resp = await fetch(SPACE_URL + '/api/requests', {
                signal: AbortSignal.timeout(60000),
            });
            const data = await resp.json();
            renderRequests(data.requests || []);
        } catch (e) {
            statusContainer.innerHTML = '<p style="color:#888">Failed to load</p>';
        }
    }

    function renderRequests(requests) {
        if (!requests.length) {
            statusContainer.innerHTML = '<p style="color:#888">No requests yet</p>';
            return;
        }
        let html = '<table class="req-table"><thead><tr>'
            + '<th>Reciter</th><th>Status</th><th>Submitted</th><th>Updated</th><th></th>'
            + '</tr></thead><tbody>';
        for (const r of requests) {
            const name = r.title.replace('[request] ', '');
            const badge = `<span class="req-badge req-badge-${r.status}">${r.status}</span>`;
            html += '<tr>'
                + `<td>${esc(name)}</td>`
                + `<td>${badge}</td>`
                + `<td>${esc(r.created_at)}</td>`
                + `<td>${esc(r.updated_at)}</td>`
                + `<td><a href="${esc(r.url)}" target="_blank" class="req-link">View</a></td>`
                + '</tr>';
        }
        html += '</tbody></table>';
        statusContainer.innerHTML = html;
    }

    // ── Submit request ──────────────────────────────────────────────
    async function submitRequest() {
        const reciterJson = reciterSelect.value;
        if (!reciterJson) {
            showStatus('Please select a reciter.', 'error');
            return;
        }
        const name = nameInput.value.trim();
        if (!name) {
            showStatus('Please enter your name.', 'error');
            return;
        }
        const email = emailInput.value.trim();
        if (!email || !email.includes('@')) {
            showStatus('Please enter a valid email.', 'error');
            return;
        }

        let info;
        try {
            info = JSON.parse(reciterJson);
        } catch {
            showStatus('Invalid reciter selection.', 'error');
            return;
        }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting...';

        try {
            const resp = await fetch(SPACE_URL + '/api/request', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reciter_slug: info.slug,
                    reciter_name: info.name,
                    audio_source: info.source,
                    min_silence_ms: parseInt(minSilenceInput.value) || 500,
                    requester_name: name,
                    requester_email: email,
                    notes: notesInput.value.trim(),
                }),
                signal: AbortSignal.timeout(60000),
            });

            const data = await resp.json();

            if (data.status === 'created') {
                const url = data.issue_url || '';
                showStatus(
                    `Request submitted! <a href="${esc(url)}" target="_blank">Track status</a>. `
                    + 'You\'ll receive email updates on status changes.',
                    'success'
                );
                // Refresh lists
                loadReciters();
                loadRequests();
            } else if (data.status === 'duplicate') {
                const url = data.existing_issue_url || '';
                showStatus(
                    `This reciter already has a pending request. `
                    + `<a href="${esc(url)}" target="_blank">View existing request</a>.`,
                    'warning'
                );
            } else {
                showStatus(data.message || 'Request failed.', 'error');
            }
        } catch (e) {
            showStatus(
                'Failed to submit. The request service may be starting up — please try again in a minute.',
                'error'
            );
            console.error('Submit failed:', e);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Request';
        }
    }

    // ── Helpers ─────────────────────────────────────────────────────
    function showStatus(html, type) {
        submitStatus.hidden = false;
        submitStatus.className = 'req-submit-status req-status-' + type;
        submitStatus.innerHTML = html;
    }

    function esc(s) {
        const el = document.createElement('span');
        el.textContent = s;
        return el.innerHTML;
    }
})();
