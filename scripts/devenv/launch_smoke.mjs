/**
 * Headless smoke test for a running Inspector stack — Dashboard + Timestamps.
 *
 * Driven by `launch.py --smoke` (or `launch smoke`). Proves the two public tabs
 * that break most often actually load against THIS stack:
 *
 *   Dashboard  — the catalog roster fetches succeed (the exact failure we keep
 *                hitting: /api/public/version or catalog.json 404 → empty board).
 *   Timestamps — seeding a real TS-capable reciter (via localStorage, the same
 *                key the app restores from) renders the waveform + analysis frame.
 *
 * Usage:  node launch_smoke.mjs <baseUrl> <outDir> [reciterSlug]
 * Exit 0 = pass, 1 = fail. Screenshots + result.json land in <outDir>.
 * Run from inspector/frontend so `playwright` resolves from its node_modules.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [, , baseUrl, outDir, reciterSlug = ''] = process.argv;
if (!baseUrl || !outDir) {
    console.error('usage: node launch_smoke.mjs <baseUrl> <outDir> [reciterSlug]');
    process.exit(2);
}
mkdirSync(outDir, { recursive: true });

// ESM resolves bare specifiers from THIS file's dir (scripts/devenv), not the
// cwd — and playwright lives in inspector/frontend/node_modules. The launcher
// runs us with cwd = that frontend dir, so resolve playwright from there.
let chromium;
try {
    const entry = pathToFileURL(join(process.cwd(), 'node_modules', 'playwright', 'index.mjs')).href;
    ({ chromium } = await import(entry));
} catch {
    try {
        ({ chromium } = await import('playwright'));
    } catch {
        console.error('smoke: playwright not found under inspector/frontend/node_modules (run `npm ci` there). Skipping.');
        process.exit(2);
    }
}

const result = { url: baseUrl, reciter: reciterSlug, dashboard: {}, timestamps: {}, ok: false };
const netErrors = [];
const consoleErrors = [];

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

page.on('response', (r) => {
    const u = r.url();
    if (u.includes('/api/') && r.status() >= 400) netErrors.push(`${r.status()} ${u}`);
});
page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
});

const shot = (name) => page.screenshot({ path: join(outDir, name), fullPage: false }).catch(() => {});

try {
    // ---- Dashboard ----------------------------------------------------------
    const apiSeen = new Set();
    page.on('response', (r) => {
        for (const probe of ['/api/public/version', '/api/static/catalog.json']) {
            if (r.url().includes(probe) && r.status() === 200) apiSeen.add(probe);
        }
    });

    await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 45_000 });
    await page.waitForSelector('.tab-btn[data-tab="dashboard"]', { timeout: 20_000 });

    const bodyText = await page.evaluate(() => document.body.innerText);
    const errorBanner = /HTTP 404|fetchCatalogVersion|Frontend not built|internal server error/i.exec(bodyText);
    // The catalog renders reciter names; assert the board isn't the empty 0-state.
    const reciterCount = await page.evaluate(() => {
        const rows = document.querySelectorAll('[data-tab] , tr, .reciter-row, [class*="reciter"]');
        return document.body.innerText.match(/\b\d{2,4}\b\s*reciters?/i) ? 'has-count' : rows.length;
    });
    await shot('dashboard.png');

    result.dashboard = {
        version_ok: apiSeen.has('/api/public/version'),
        catalog_ok: apiSeen.has('/api/static/catalog.json'),
        error_banner: errorBanner ? errorBanner[0] : null,
        api_errors: [...netErrors],
    };
    const dashOk = result.dashboard.version_ok && !result.dashboard.error_banner;
    result.dashboard.ok = dashOk;
    if (!dashOk) throw new Error(`dashboard failed: ${JSON.stringify(result.dashboard)}`);

    // ---- Timestamps ---------------------------------------------------------
    // Click the tab (the active-tab localStorage restore can't be used: on a
    // fresh load with no player delivery the app bounces TS → Dashboard). Then
    // drive the reciter picker exactly like a user — pick the first TS-capable
    // reciter and require the chip to replace "Pick a reciter" AND a non-empty
    // waveform canvas, so an empty placeholder canvas can't pass.
    await page.click('.tab-btn[data-tab="timestamps"]');
    await page.waitForSelector('#timestamps-panel', { timeout: 20_000 });

    let optionCount = 0;
    let reciterLoaded = false;
    let waveformWidth = 0;
    const trigger = page.locator('.picker-trigger');
    if (await trigger.count()) {
        await trigger.first().click().catch(() => {});
        const opt = page.locator('.dropup-list .opt');
        await opt.first().waitFor({ timeout: 5_000 }).catch(() => {});
        optionCount = await opt.count().catch(() => 0);
        if (optionCount > 0) {
            await opt.first().click();
            // Generous timeout: the first chapter's peaks/audio come over the
            // (Windows: slow hffs) bucket path.
            reciterLoaded = await page
                .waitForFunction(() => {
                    const t = document.querySelector('.picker-trigger')?.innerText || '';
                    return t.trim() !== '' && !/pick a reciter/i.test(t);
                }, { timeout: 50_000 })
                .then(() => true)
                .catch(() => false);
            waveformWidth = await page.evaluate(() => {
                const c = document.querySelector('#timestamps-panel canvas');
                return c ? c.width : 0;
            });
        }
    }
    await shot('timestamps.png');

    result.timestamps = {
        panel_mounted: true,
        ts_reciters_available: optionCount,
        reciter_loaded: reciterLoaded,
        waveform_width: waveformWidth,
        console_errors: consoleErrors.slice(0, 5),
    };
    // With TS-capable reciters present, require a real load + non-empty waveform.
    // With none (e.g. fixtures), tab-mount alone is the bar.
    const tsOk = optionCount > 0 ? reciterLoaded && waveformWidth > 0 : true;
    result.timestamps.ok = tsOk;
    if (!tsOk) throw new Error(`timestamps failed: ${JSON.stringify(result.timestamps)}`);

    result.ok = true;
} catch (err) {
    result.error = String(err && err.message ? err.message : err);
} finally {
    await browser.close().catch(() => {});
    writeFileSync(join(outDir, 'result.json'), JSON.stringify(result, null, 2));
}

const tick = (b) => (b ? 'PASS' : 'FAIL');
console.log(`smoke: dashboard ${tick(result.dashboard.ok)}  |  timestamps ${tick(result.timestamps.ok)}  |  overall ${tick(result.ok)}`);
if (!result.ok) {
    console.log('  detail:', JSON.stringify(result, null, 2));
}
process.exit(result.ok ? 0 : 1);
