<script lang="ts">
    /**
     * Wizard step 2 — pick the source method.
     *
     * Top horizontal toggle (links / playlist), body is the picked panel.
     * Same shape as step 1's reciter mode toggle so the two steps rhyme
     * visually. Browser uploads are deliberately excluded: 1–3 GB of audio
     * through a single-worker gunicorn Space blocks every concurrent user
     * mid-transfer, and Drive / YouTube / Archive.org are already adequate
     * hosts. Contributors host the audio themselves and hand us URLs.
     *
     * The "links" panel accepts three interchangeable input forms — bulk
     * paste, CSV / JSON drop, and per-chapter inline rows — all writing
     * into the same 114-row store array.
     *
     * This step only writes into the wizard store; the SubmitWizard shell
     * posts the assembled payload to the intake API on the final step.
     */
    import { fade, fly } from 'svelte/transition';

    import { localeStore, tr } from '$lib/i18n/locale-store';
    import * as m from '$lib/paraglide/messages';
    import { isPlausibleUrl } from '../../../../lib/utils/url';
    import { type LinkRow, submitWizard } from '../../stores/submit-wizard';

    $: state = $submitWizard;
    $: method = state.sourceMethod ?? 'links';

    $: lang = $localeStore;
    $: sourceMethodAria = tr(lang, m.dashboard_submit_source_method_aria());
    $: linksLabel = tr(lang, m.dashboard_submit_source_links_label());
    $: linksHint = tr(lang, m.dashboard_submit_source_links_hint());
    $: playlistLabel = tr(lang, m.dashboard_submit_source_playlist_label());
    $: playlistModeHint = tr(lang, m.dashboard_submit_source_playlist_hint());
    $: csvBrowse = tr(lang, m.dashboard_submit_csv_browse());
    $: exampleCsvLabel = tr(lang, m.dashboard_submit_example_csv_label());
    $: exampleJsonLabel = tr(lang, m.dashboard_submit_example_json_label());
    $: perChapterHead = tr(lang, m.dashboard_submit_per_chapter_head());
    $: rowPlaceholder = tr(lang, m.dashboard_submit_per_chapter_row_placeholder());
    $: linksInvalid = tr(lang, m.dashboard_submit_links_invalid());
    $: missingLabel = tr(lang, m.dashboard_submit_missing_label());
    $: playlistUrlLabel = tr(lang, m.dashboard_submit_playlist_url_label());
    $: playlistUrlPlaceholder = tr(lang, m.dashboard_submit_playlist_url_placeholder());
    $: playlistHint = tr(lang, m.dashboard_submit_playlist_hint());
    $: csvDropCopy = tr(lang, m.dashboard_submit_csv_drop_copy({ csv: '.csv', json: '.json' }));

    function pick(m: 'links' | 'playlist'): void {
        submitWizard.update((s) => ({ ...s, sourceMethod: m }));
    }

    function updateLink(chapter: number, url: string): void {
        submitWizard.update((s) => {
            const links = s.links.map((row) =>
                row.chapter === chapter ? { ...row, url } : row,
            );
            return { ...s, links };
        });
    }

    async function onFileDrop(e: DragEvent): Promise<void> {
        e.preventDefault();
        const file = e.dataTransfer?.files?.[0];
        if (!file) return;
        await ingestStructuredFile(file);
    }

    async function onFilePick(e: Event): Promise<void> {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (!file) return;
        await ingestStructuredFile(file);
    }

    async function ingestStructuredFile(file: File): Promise<void> {
        const text = await file.text();
        const rows: LinkRow[] = [];
        if (file.name.endsWith('.json')) {
            try {
                const json = JSON.parse(text);
                if (Array.isArray(json)) {
                    for (const r of json) {
                        const c = Number(r.chapter ?? r.number ?? r.surah);
                        const u = String(r.url ?? r.link ?? '').trim();
                        if (c >= 1 && c <= 114 && u) rows.push({ chapter: c, url: u });
                    }
                }
            } catch {
                // Bad JSON — leave rows empty, the UI's mismatched-count
                // chip already signals nothing landed.
            }
        } else {
            // CSV: chapter,url per line. Header optional.
            for (const line of text.split(/\r?\n/)) {
                const trimmed = line.trim();
                if (!trimmed || /^#/.test(trimmed)) continue;
                const [a, ...rest] = trimmed.split(',');
                const c = Number(a);
                const u = rest.join(',').trim();
                if (c >= 1 && c <= 114 && u) rows.push({ chapter: c, url: u });
            }
        }
        if (rows.length === 0) return;
        submitWizard.update((s) => {
            const map = new Map(rows.map((r) => [r.chapter, r.url]));
            const links = s.links.map((row) =>
                map.has(row.chapter) ? { chapter: row.chapter, url: map.get(row.chapter)! } : row,
            );
            return { ...s, links };
        });
    }

    $: linkCount = state.links.filter((r) => r.url.trim().length > 0).length;
    $: linkComplete = linkCount === 114;
    $: malformedChapters = state.links
        .filter((r) => r.url.trim().length > 0 && !isPlausibleUrl(r.url))
        .map((r) => r.chapter);
    $: linkAnyMalformed = malformedChapters.length > 0;
    $: presentChapters = new Set(
        state.links.filter((r) => r.url.trim().length > 0).map((r) => r.chapter),
    );
    $: missingChapters = Array.from({ length: 114 }, (_, i) => i + 1).filter(
        (c) => !presentChapters.has(c),
    );
    $: linkCountLabel = tr(lang, m.dashboard_submit_link_count({ count: linkCount }));
    $: missingCoverage = tr(
        lang,
        m.dashboard_submit_missing_coverage({
            count: missingChapters.length,
            ranges: compactRanges(missingChapters),
        }),
    );

    /** Render a sorted int list as compact ranges: [1,2,3,7] → "1–3, 7". */
    function compactRanges(nums: number[]): string {
        const xs = [...new Set(nums)].sort((a, b) => a - b);
        if (xs.length === 0) return '';
        const parts: string[] = [];
        let start = xs[0]!;
        let prev = xs[0]!;
        for (const n of xs.slice(1)) {
            if (n === prev + 1) { prev = n; continue; }
            parts.push(start === prev ? `${start}` : `${start}–${prev}`);
            start = prev = n;
        }
        parts.push(start === prev ? `${start}` : `${start}–${prev}`);
        return parts.join(', ');
    }

    function prevent(e: DragEvent): void { e.preventDefault(); }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <div class="mode-toggle" role="tablist" aria-label={sourceMethodAria}>
        <button
            type="button"
            class="mode-btn"
            class:active={method === 'links'}
            role="tab"
            aria-selected={method === 'links'}
            on:click={() => pick('links')}
        >
            <span class="mode-label">{linksLabel}</span>
            <span class="mode-hint">{linksHint}</span>
        </button>
        <button
            type="button"
            class="mode-btn"
            class:active={method === 'playlist'}
            role="tab"
            aria-selected={method === 'playlist'}
            on:click={() => pick('playlist')}
        >
            <span class="mode-label">{playlistLabel}</span>
            <span class="mode-hint">{playlistModeHint}</span>
        </button>
        <span class="mode-track" data-mode={method} aria-hidden="true"></span>
    </div>

    {#key method}
        <div class="body-pane" in:fly={{ y: 4, duration: 180 }}>
            {#if method === 'links'}
                <div class="links-grid">
                    <div class="examples">
                        <div
                            class="csv-drop"
                            on:drop={onFileDrop}
                            on:dragover={prevent}
                            role="presentation"
                        >
                            <span class="csv-icon" aria-hidden="true">⟱</span>
                            <span class="csv-copy">{csvDropCopy}</span>
                            <label class="csv-pick">
                                {csvBrowse}
                                <input type="file" accept=".csv,.json,text/csv,application/json" on:change={onFilePick} hidden />
                            </label>
                        </div>

                        <div class="example">
                            <span class="example-label">{exampleCsvLabel}</span>
                            <pre class="example-code">chapter,url
1,https://example.com/001.mp3
2,https://example.com/002.mp3
…</pre>
                        </div>
                        <div class="example">
                            <span class="example-label">{exampleJsonLabel}</span>
                            <pre class="example-code">{`[
  { "chapter": 1, "url": "https://example.com/001.mp3" },
  { "chapter": 2, "url": "https://example.com/002.mp3" },
  …
]`}</pre>
                        </div>
                    </div>

                    <div class="per-chapter">
                        <div class="pc-head">
                            <span>{perChapterHead}</span>
                            <span class="pc-count" class:complete={linkComplete} class:warn={linkAnyMalformed}>
                                {linkCountLabel}
                            </span>
                        </div>
                        <div class="pc-rows">
                            {#each state.links as row (row.chapter)}
                                <label class="pc-row">
                                    <span class="pc-num">{String(row.chapter).padStart(3, '0')}</span>
                                    <input
                                        type="url"
                                        placeholder={rowPlaceholder}
                                        value={row.url}
                                        class:has-url={row.url.trim().length > 0}
                                        class:malformed={row.url.trim().length > 0 && !isPlausibleUrl(row.url)}
                                        on:input={(e) => updateLink(row.chapter, (e.currentTarget as HTMLInputElement).value)}
                                    />
                                </label>
                            {/each}
                        </div>

                        {#if linkAnyMalformed || (linkCount > 0 && !linkComplete)}
                            <div class="coverage">
                                {#if linkAnyMalformed}
                                    <p class="cov-line err">
                                        {linksInvalid}
                                    </p>
                                {/if}
                                {#if linkCount > 0 && !linkComplete}
                                    <p class="cov-line warn">
                                        <span class="cov-label">{missingLabel}</span>
                                        {missingCoverage}
                                    </p>
                                {/if}
                            </div>
                        {/if}
                    </div>
                </div>
            {:else}
                <label class="playlist">
                    <span>{playlistUrlLabel}</span>
                    <input
                        type="url"
                        placeholder={playlistUrlPlaceholder}
                        value={state.playlistUrl}
                        on:input={(e) => submitWizard.update((s) => ({ ...s, playlistUrl: (e.currentTarget as HTMLInputElement).value }))}
                    />
                    <span class="playlist-hint">
                        {playlistHint}
                    </span>
                </label>
            {/if}
        </div>
    {/key}
</div>

<style>
    .step {
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
    }

    .mode-toggle {
        position: relative;
        display: grid;
        grid-template-columns: 1fr 1fr;
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        padding: 3px;
    }
    .mode-btn {
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: var(--s-2) var(--s-3);
        border-radius: 4px;
        color: var(--text-muted);
        text-align: start;
        background: transparent;
        border: none;
        cursor: pointer;
        transition: color var(--t-base) var(--ease-out-quart);
    }
    .mode-btn.active { color: var(--text-primary); }
    .mode-label {
        font-size: var(--fs-body);
        font-weight: 500;
    }
    .mode-hint {
        font-size: 10.5px;
        color: var(--text-faint);
    }
    .mode-track {
        position: absolute;
        top: 3px;
        bottom: 3px;
        width: calc(50% - 3px);
        inset-inline-start: 3px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 4px;
        transition: transform var(--t-base) var(--ease-out-expo);
        pointer-events: none;
    }
    .mode-track[data-mode='playlist'] { transform: translateX(100%); }
    /* Under RTL the track starts at the logical (right) edge, so the second
       mode advances toward the left — negate the slide. */
    :global([dir='rtl']) .mode-track[data-mode='playlist'] { transform: translateX(-100%); }

    .body-pane {
        display: flex;
        flex-direction: column;
        will-change: transform, opacity;
    }

    /* links */
    .links-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: var(--s-4);
    }
    @media (max-width: 720px) {
        .links-grid { grid-template-columns: 1fr; }
    }
    .examples { display: flex; flex-direction: column; gap: var(--s-3); }
    .example {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .example-label {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
    }
    .example-code {
        margin: 0;
        padding: 8px 10px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        color: var(--text-secondary);
        font: 11px/1.5 var(--font-mono);
        white-space: pre;
        overflow-x: auto;
    }

    .csv-drop {
        display: flex;
        align-items: center;
        gap: var(--s-3);
        padding: var(--s-3);
        background: var(--panel);
        border: 1px dashed var(--border-default);
        border-radius: var(--r-2);
        font-size: var(--fs-meta);
        color: var(--text-secondary);
    }
    .csv-icon {
        font-size: 18px;
        color: var(--text-faint);
        line-height: 1;
    }
    .csv-copy { flex: 1; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .csv-pick {
        color: var(--accent);
        cursor: pointer;
        text-decoration: underline;
        text-underline-offset: 3px;
    }
    .csv-pick:hover { color: var(--accent-strong); }

    .per-chapter {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        min-height: 0;
    }
    .pc-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .pc-count {
        font-family: var(--font-mono);
        font-variant-numeric: tabular-nums;
        color: var(--text-secondary);
        transition: color var(--t-base) var(--ease-out-quart);
    }
    .pc-count.complete { color: var(--state-published-fg); }
    .pc-count.warn { color: var(--state-error-fg); }
    .pc-rows {
        max-height: 260px;
        overflow-y: auto;
        padding: 4px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .pc-row {
        display: grid;
        grid-template-columns: 36px 1fr;
        align-items: center;
        gap: var(--s-2);
    }
    .pc-num {
        font-family: var(--font-mono);
        font-size: 10.5px;
        color: var(--text-faint);
        text-align: end;
        padding-inline-end: 2px;
    }
    .pc-row input {
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-1);
        color: var(--text-primary);
        padding: 4px 6px;
        font: 11.5px/1.4 var(--font-mono);
        transition: border-color var(--t-fast), background var(--t-fast);
    }
    .pc-row input:hover { border-color: var(--border-quiet); }
    .pc-row input:focus {
        outline: none;
        border-color: var(--accent);
        background: var(--canvas-inset);
    }
    .pc-row input.has-url { color: var(--text-primary); }
    .pc-row input.malformed { border-color: var(--state-error-fg); color: var(--state-error-fg); }

    .coverage { display: flex; flex-direction: column; gap: 3px; margin-top: var(--s-2); }
    .cov-line { margin: 0; font-size: 11px; line-height: 1.45; color: var(--text-muted); }
    .cov-line .cov-label {
        display: inline-block; margin-inline-end: 6px; padding: 0 6px;
        border-radius: var(--r-1); font-size: 10px; font-weight: 500;
    }
    .cov-line.err { color: var(--state-error-fg); }
    .cov-line.warn .cov-label { background: oklch(0.86 0.13 75 / 0.16); color: var(--state-error-fg); }

    /* playlist */
    .playlist {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: var(--fs-meta);
        color: var(--text-muted);
    }
    .playlist input {
        background: var(--panel);
        border: 1px solid var(--border-default);
        color: var(--text-primary);
        border-radius: var(--r-2);
        padding: 8px 10px;
        font: var(--fs-body)/1.4 var(--font-mono);
    }
    .playlist input:focus { outline: none; border-color: var(--accent); }
    .playlist-hint {
        font-size: 10.5px;
        color: var(--text-faint);
        line-height: 1.5;
    }
</style>
