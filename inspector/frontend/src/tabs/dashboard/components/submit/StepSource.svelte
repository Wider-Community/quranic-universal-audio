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
     * Submit is a no-op until backend lands, so every interaction is local
     * state only. Playlist URL is captured but never parsed.
     */
    import { fade, fly } from 'svelte/transition';

    import { type LinkRow, submitWizard } from '../../stores/submit-wizard';

    $: state = $submitWizard;
    $: method = state.sourceMethod ?? 'links';

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
    $: linkAnyMalformed = state.links.some(
        (r) => r.url.trim().length > 0 && !/^https?:\/\//i.test(r.url.trim()),
    );

    function prevent(e: DragEvent): void { e.preventDefault(); }
</script>

<div class="step" in:fade={{ duration: 180 }}>
    <div class="mode-toggle" role="tablist" aria-label="Source method">
        <button
            type="button"
            class="mode-btn"
            class:active={method === 'links'}
            role="tab"
            aria-selected={method === 'links'}
            on:click={() => pick('links')}
        >
            <span class="mode-label">Direct links</span>
            <span class="mode-hint">114 URLs · paste, drop, or per chapter</span>
        </button>
        <button
            type="button"
            class="mode-btn"
            class:active={method === 'playlist'}
            role="tab"
            aria-selected={method === 'playlist'}
            on:click={() => pick('playlist')}
        >
            <span class="mode-label">Playlist</span>
            <span class="mode-hint">YouTube · SoundCloud · Archive · Drive folder</span>
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
                            <span class="csv-copy">
                                Drop <span class="m">.csv</span> or <span class="m">.json</span>, or
                            </span>
                            <label class="csv-pick">
                                browse
                                <input type="file" accept=".csv,.json,text/csv,application/json" on:change={onFilePick} hidden />
                            </label>
                        </div>

                        <div class="example">
                            <span class="example-label">CSV — header optional</span>
                            <pre class="example-code">chapter,url
1,https://example.com/001.mp3
2,https://example.com/002.mp3
…</pre>
                        </div>
                        <div class="example">
                            <span class="example-label">JSON</span>
                            <pre class="example-code">{`[
  { "chapter": 1, "url": "https://example.com/001.mp3" },
  { "chapter": 2, "url": "https://example.com/002.mp3" },
  …
]`}</pre>
                        </div>
                    </div>

                    <div class="per-chapter">
                        <div class="pc-head">
                            <span>Per chapter</span>
                            <span class="pc-count" class:complete={linkComplete} class:warn={linkAnyMalformed}>
                                {linkCount} / 114
                            </span>
                        </div>
                        <div class="pc-rows">
                            {#each state.links as row (row.chapter)}
                                <label class="pc-row">
                                    <span class="pc-num">{String(row.chapter).padStart(3, '0')}</span>
                                    <input
                                        type="url"
                                        placeholder="https://…"
                                        value={row.url}
                                        class:has-url={row.url.trim().length > 0}
                                        on:input={(e) => updateLink(row.chapter, (e.currentTarget as HTMLInputElement).value)}
                                    />
                                </label>
                            {/each}
                        </div>
                    </div>
                </div>
            {:else}
                <label class="playlist">
                    <span>Playlist URL</span>
                    <input
                        type="url"
                        placeholder="https://youtube.com/playlist?list=…"
                        value={state.playlistUrl}
                        on:input={(e) => submitWizard.update((s) => ({ ...s, playlistUrl: (e.currentTarget as HTMLInputElement).value }))}
                    />
                    <span class="playlist-hint">
                        For a Google Drive folder, share it as
                        <em>anyone with the link can view</em> and name the
                        files so chapter order is unambiguous
                        (<span class="m">001.mp3</span> … <span class="m">114.mp3</span>).
                        We fetch via yt-dlp once the ingest pipeline lands.
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
        text-align: left;
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
        left: 3px;
        background: var(--panel);
        border: 1px solid var(--border-quiet);
        border-radius: 4px;
        transition: transform var(--t-base) var(--ease-out-expo);
        pointer-events: none;
    }
    .mode-track[data-mode='playlist'] { transform: translateX(100%); }

    .body-pane {
        display: flex;
        flex-direction: column;
        will-change: transform, opacity;
    }

    .m { font-family: var(--font-mono); color: var(--text-secondary); }

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
        text-align: right;
        padding-right: 2px;
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
        max-width: 60ch;
    }
</style>
