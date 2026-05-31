<script lang="ts">
    /**
     * Throwaway prototyping surface for the recitation animation.
     * Loads real shard + audio (dev backend / bucket mount) and exposes every
     * RecitationAnimConfig knob as a live control. Not shipped.
     */
    import { onMount } from 'svelte';

    import {
        AyahFilmstrip,
        AyahPicker,
        buildChapterRecitation,
        DEFAULT_RECITATION_CONFIG,
        EASING_OPTIONS,
        FILMSTRIP_MOTIONS,
        RecitationSection,
        type AnimUnit,
        type AssembledVerse,
        type AyahBoundary,
        type RecitationAnimConfig,
    } from '../../src/lib/recitation-animation';
    import type { TsManifestResponse } from '../../src/lib/types/api';
    import { demoRecitation } from './fixture';
    import {
        assembleVerseFromShard,
        chapterVerseRefs,
        loadChapterShard,
        loadDk,
        loadManifest,
        loadQpc,
        reciterAudioFromManifest,
        resolveAudioUrl,
    } from '../../src/tabs/timestamps/services/ts_client';

    let config = $state<RecitationAnimConfig>({ ...DEFAULT_RECITATION_CONFIG });

    let manifest: TsManifestResponse | null = null;
    let reciters = $state<string[]>([]);
    let reciter = $state('');
    let chapters = $state<number[]>([]);
    let chapter = $state(1);
    let audioOverride = $state('');

    let units = $state<AnimUnit[]>([]);
    let ayahs = $state<AyahBoundary[]>([]);
    let audioCategory = $state('');
    let loading = $state(false);
    let error = $state('');

    let mode = $state<'live' | 'demo'>('demo');
    let audioEl = $state<HTMLAudioElement | undefined>(undefined);
    let playing = $state(false);
    let posMs = $state(0);
    let durationMs = $state(0);
    let contentEndMs = 0;
    let demoT = 0; // ms virtual clock for demo mode (read each frame, not reactive)

    let section = $state<{ refresh: () => void } | undefined>(undefined);
    let filmstrip = $state<{ refresh: () => void } | undefined>(undefined);
    let hoverMs = $state<number | null>(null);
    let pickerOpen = $state(false);
    let showExport = $state(false);

    const getTimeMs = (): number =>
        mode === 'demo' ? demoT : audioEl ? audioEl.currentTime * 1000 : 0;

    // Demo virtual transport: advance the clock while playing (no <audio>).
    $effect(() => {
        if (mode !== 'demo' || !playing) return;
        let raf = 0;
        let prev = -1;
        const loop = (ts: number): void => {
            if (prev >= 0) {
                demoT += ts - prev;
                posMs = demoT;
                if (demoT >= durationMs) {
                    demoT = durationMs;
                    posMs = demoT;
                    playing = false;
                    return;
                }
            }
            prev = ts;
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    });
    const pct = $derived(durationMs > 0 ? Math.min(100, (posMs / durationMs) * 100) : 0);
    const verseNums = $derived(ayahs.map((a) => a.ayah));
    // Current ayah = the last boundary whose start has passed (ayahs are sorted
    // ascending by startMs). Plain loop — `findLast` isn't in the es2022 lib.
    const currentAyah = $derived.by(() => {
        let cur: number | null = null;
        for (const a of ayahs) {
            if (a.startMs <= posMs) cur = a.ayah;
            else break;
        }
        return cur;
    });
    const exportJson = $derived(JSON.stringify(config, null, 2));

    onMount(async () => {
        loadDemo(); // always have something to show / tune
        try {
            manifest = await loadManifest();
            reciters = Object.keys(manifest.reciters).sort();
            if (reciters.length) {
                reciter = reciters[0]!;
                selectReciter();
            }
        } catch (e) {
            error = `manifest unavailable — demo only (start the dev backend; the playground proxies to it via the launch config): ${String(e)}`;
        }
    });

    function loadDemo(): void {
        const rec = demoRecitation();
        mode = 'demo';
        units = rec.units;
        ayahs = rec.ayahs;
        contentEndMs = rec.contentEndMs;
        durationMs = rec.contentEndMs;
        audioCategory = 'by_surah';
        demoT = 0;
        posMs = 0;
        playing = false;
    }

    function selectReciter(): void {
        const block = manifest?.reciters?.[reciter];
        chapters = block?.ts_chapters ? [...block.ts_chapters].sort((a, b) => a - b) : [];
        chapter = chapters[0] ?? 1;
    }

    async function loadChapter(): Promise<void> {
        if (!manifest || !reciter) return;
        loading = true;
        error = '';
        playing = false;
        mode = 'live';
        try {
            const [shard, qpc, dk] = await Promise.all([
                loadChapterShard(reciter, chapter),
                loadQpc(),
                loadDk(),
            ]);
            const ra = reciterAudioFromManifest(manifest, reciter);
            if (!ra) throw new Error('reciter not advertised in manifest');
            audioCategory = ra.audio_category;
            const verses: AssembledVerse[] = [];
            for (const ref of chapterVerseRefs(shard)) {
                const data = assembleVerseFromShard(reciter, shard, ref, qpc, dk, ra);
                if (data) verses.push({ verseRef: ref, data });
            }
            const rec = buildChapterRecitation(reciter, chapter, verses);
            units = rec.units;
            ayahs = rec.ayahs;
            contentEndMs = rec.contentEndMs;
            durationMs = rec.contentEndMs;

            const cdn = resolveAudioUrl(ra.url_template, shard._meta.audio_urls, chapter, 1);
            const url =
                audioOverride.trim()
                || (cdn.startsWith('/api/')
                    ? cdn
                    : `/api/seg/audio-proxy/${encodeURIComponent(reciter)}?url=${encodeURIComponent(cdn)}`);
            if (audioEl) {
                audioEl.src = url;
                audioEl.load();
            }
            playing = false;
            posMs = 0;
        } catch (e) {
            error = `load failed: ${String(e)}`;
            units = [];
            ayahs = [];
        } finally {
            loading = false;
        }
    }

    function toggle(): void {
        if (mode === 'demo') {
            if (demoT >= durationMs) demoT = 0;
            playing = !playing;
            return;
        }
        if (!audioEl) return;
        if (playing) audioEl.pause();
        else void audioEl.play();
    }
    function onTime(): void {
        if (mode === 'live') posMs = getTimeMs();
    }
    function onMeta(): void {
        if (mode !== 'live') return;
        const d = audioEl?.duration ?? 0;
        durationMs = Number.isFinite(d) && d > 0 ? d * 1000 : contentEndMs;
    }
    function seekMs(ms: number): void {
        const clamped = Math.max(0, ms);
        posMs = clamped;
        if (mode === 'demo') {
            demoT = clamped;
            if (!playing) {
                section?.refresh();
                filmstrip?.refresh();
            }
            return;
        }
        if (!audioEl) return;
        audioEl.currentTime = clamped / 1000;
        if (audioEl.paused) {
            section?.refresh();
            filmstrip?.refresh();
        }
    }
    function barMsAt(e: { clientX: number; currentTarget: EventTarget | null }): number {
        const el = e.currentTarget as HTMLElement;
        const rect = el.getBoundingClientRect();
        const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        return ratio * durationMs;
    }
    /** Start of the ayah spanning `ms` (ayahs sorted ascending). */
    function ayahStartAtTime(ms: number): number {
        let start = ms;
        for (const a of ayahs) {
            if (a.startMs <= ms) start = a.startMs;
            else break;
        }
        return start;
    }
    function onBarClick(e: MouseEvent): void {
        const ms = barMsAt(e);
        // Hybrid/snap quantize bar seeks to ayah starts, like cell clicks; tuner
        // seeks to the exact time.
        seekMs(config.filmstripMotion === 'tuner' ? ms : ayahStartAtTime(ms));
    }
    function onBarHover(e: PointerEvent): void {
        hoverMs = config.filmstripShow ? barMsAt(e) : null;
    }
    function seekToAyah(v: number): void {
        const b = ayahs.find((a) => a.ayah === v);
        if (b) seekMs(b.startMs);
        pickerOpen = false;
    }
    function fmt(ms: number): string {
        const t = Math.max(0, Math.floor(ms / 1000));
        const m = Math.floor(t / 60);
        const s = t % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }
    /** Best-effort CSS-color → #rrggbb for the native color input. Passes hex
     *  through, converts rgb(); var()/oklch fall back to a cyan so the picker
     *  still opens (picking writes a real hex back). */
    function resolveHex(c: string): string {
        if (/^#[0-9a-fA-F]{6}$/.test(c)) return c;
        const m = c.match(/^rgba?\(([^)]+)\)/);
        if (m && m[1]) {
            const [r, g, b] = m[1].split(',').map((s) => parseInt(s.trim(), 10));
            return '#' + [r, g, b].map((n) => (n ?? 0).toString(16).padStart(2, '0')).join('');
        }
        return '#5cc8e6';
    }
    function resetConfig(): void {
        config = { ...DEFAULT_RECITATION_CONFIG };
    }
    async function copyExport(): Promise<void> {
        try {
            await navigator.clipboard.writeText(exportJson);
        } catch {
            /* ignore */
        }
    }
</script>

<div class="shell">
    <aside class="panel">
        <h1>Recitation animation <span class="tag">playground</span></h1>
        <p class="hint">Throwaway. Tune, then lock values into <code>config.ts</code>.</p>

        <fieldset>
            <legend>Timing (ms)</legend>
            {#each [['wordRevealMs', 'word reveal', 0, 1200], ['charRevealMs', 'char reveal', 0, 800], ['clearFadeMs', 'clear fade', 0, 1200], ['leadMs', 'lead (early)', -400, 400]] as [key, label, min, max]}
                <label class="row">
                    <span>{label}</span>
                    <input type="range" min={min} max={max} step="10" bind:value={config[key as 'wordRevealMs']} />
                    <em>{config[key as 'wordRevealMs']}</em>
                </label>
            {/each}
            <div class="row">
                <span>easing</span>
                <div class="pills">
                    {#each EASING_OPTIONS as o}
                        <button
                            type="button"
                            class="pill"
                            class:on={config.easing === o.value}
                            onclick={() => (config.easing = o.value)}
                        >{o.label}</button>
                    {/each}
                </div>
            </div>
        </fieldset>

        <fieldset>
            <legend>Effects</legend>
            <div class="row"><span>highlight</span>
                <input type="text" bind:value={config.highlightColor} />
                <input
                    type="color"
                    class="cpick"
                    value={resolveHex(config.highlightColor)}
                    oninput={(e) => (config.highlightColor = e.currentTarget.value)}
                />
            </div>
            <div class="row"><span>base text</span>
                <input type="text" bind:value={config.baseColor} />
                <input
                    type="color"
                    class="cpick"
                    value={resolveHex(config.baseColor)}
                    oninput={(e) => (config.baseColor = e.currentTarget.value)}
                />
            </div>
            <label class="row"><span>reached opacity</span><input type="range" min="0" max="1" step="0.02" bind:value={config.reachedOpacity} /><em>{config.reachedOpacity}</em></label>
            <label class="row"><span>unreached opacity</span><input type="range" min="0" max="1" step="0.02" bind:value={config.unreachedOpacity} /><em>{config.unreachedOpacity}</em></label>
            <label class="row">
                <span>active emphasis</span>
                <input
                    type="range" min="0" max="800" step="10"
                    value={config.granularity === 'char' ? config.charActiveEmphasisMs : config.wordActiveEmphasisMs}
                    oninput={(e) => {
                        const v = +e.currentTarget.value;
                        if (config.granularity === 'char') config.charActiveEmphasisMs = v;
                        else config.wordActiveEmphasisMs = v;
                    }}
                />
                <em>{config.granularity === 'char' ? config.charActiveEmphasisMs : config.wordActiveEmphasisMs}</em>
                <span class="gtag">{config.granularity}</span>
            </label>
            <label class="row"><span>active scale</span><input type="range" min="1" max="1.5" step="0.01" bind:value={config.activeScale} /><em>{config.activeScale}</em><span class="gtag">word</span></label>
            <label class="row"><span>active glow px</span><input type="range" min="0" max="30" step="1" bind:value={config.activeGlowPx} /><em>{config.activeGlowPx}</em></label>
            <label class="row"><span>active stroke</span><input type="range" min="0" max="3" step="0.25" bind:value={config.activeStrokePx} /><em>{config.activeStrokePx}</em></label>
            <div class="row"><span>stroke color</span>
                <input type="text" bind:value={config.activeStrokeColor} />
                <input type="color" class="cpick" value={resolveHex(config.activeStrokeColor)} oninput={(e) => (config.activeStrokeColor = e.currentTarget.value)} />
            </div>
            <label class="row"><span>base stroke</span><input type="range" min="0" max="3" step="0.25" bind:value={config.baseStrokePx} /><em>{config.baseStrokePx}</em></label>
            <div class="row"><span>base stroke col</span>
                <input type="text" bind:value={config.baseStrokeColor} />
                <input type="color" class="cpick" value={resolveHex(config.baseStrokeColor)} oninput={(e) => (config.baseStrokeColor = e.currentTarget.value)} />
            </div>
        </fieldset>

        <fieldset>
            <legend>Typography</legend>
            <label class="row col"><span>font family</span><input type="text" bind:value={config.fontFamily} /></label>
            <label class="row"><span>font size</span><input type="range" min="16" max="72" step="1" bind:value={config.fontSizePx} /><em>{config.fontSizePx}</em></label>
            <label class="row"><span>line height</span><input type="range" min="1" max="3" step="0.05" bind:value={config.lineHeight} /><em>{config.lineHeight}</em></label>
            <label class="row"><span>word spacing</span><input type="range" min="0" max="30" step="1" bind:value={config.wordSpacingPx} /><em>{config.wordSpacingPx}</em></label>
            <label class="row"><span>letter spacing</span><input type="range" min="-2" max="8" step="0.5" bind:value={config.letterSpacingPx} /><em>{config.letterSpacingPx}</em></label>
        </fieldset>

        <fieldset>
            <legend>Behaviour</legend>
            <div class="row"><span>granularity</span>
                <div class="pills">
                    {#each ['word', 'char'] as g}
                        <button
                            type="button"
                            class="pill"
                            class:on={config.granularity === g}
                            onclick={() => (config.granularity = g as 'word' | 'char')}
                        >{g}</button>
                    {/each}
                </div>
            </div>
            <label class="check"><input type="checkbox" bind:checked={config.clearOnOverflow} /> clear on overflow</label>
            <label class="check"><input type="checkbox" bind:checked={config.clearOnAyahEnd} /> clear on ayah end</label>
            <label class="check"><input type="checkbox" bind:checked={config.centerLine} /> center line</label>
            <label class="check"><input type="checkbox" bind:checked={config.showAyahMarker} /> show ۝ ayah marker</label>
            <label class="check"><input type="checkbox" bind:checked={config.autoExpandOnPlay} /> auto-expand on play</label>
            <label class="check"><input type="checkbox" bind:checked={config.collapsedByDefault} /> collapsed by default</label>
        </fieldset>

        <fieldset>
            <legend>Filmstrip</legend>
            <label class="check"><input type="checkbox" bind:checked={config.filmstripShow} /> show filmstrip</label>
            <div class="row"><span>motion</span>
                <div class="pills">
                    {#each FILMSTRIP_MOTIONS as m}
                        <button
                            type="button"
                            class="pill"
                            class:on={config.filmstripMotion === m.value}
                            onclick={() => (config.filmstripMotion = m.value)}
                        >{m.label}</button>
                    {/each}
                </div>
            </div>
            <label class="row"><span>proportional</span><input type="range" min="0" max="1" step="0.05" bind:value={config.filmstripProportional} /><em>{config.filmstripProportional}</em></label>
            <label class="row"><span>min cell px</span><input type="range" min="24" max="80" step="1" bind:value={config.filmstripMinCellPx} /><em>{config.filmstripMinCellPx}</em></label>
            <label class="row"><span>max cell px</span><input type="range" min="60" max="240" step="2" bind:value={config.filmstripMaxCellPx} /><em>{config.filmstripMaxCellPx}</em></label>
            <label class="row"><span>gap px</span><input type="range" min="0" max="16" step="1" bind:value={config.filmstripGapPx} /><em>{config.filmstripGapPx}</em></label>
            <label class="row"><span>height px</span><input type="range" min="28" max="72" step="2" bind:value={config.filmstripHeightPx} /><em>{config.filmstripHeightPx}</em></label>
        </fieldset>

        <div class="actions">
            <button onclick={resetConfig}>Reset</button>
            <button onclick={() => (showExport = !showExport)}>{showExport ? 'Hide' : 'Export'} config</button>
        </div>
        {#if showExport}
            <textarea class="export" readonly rows="10">{exportJson}</textarea>
            <button onclick={copyExport}>Copy JSON</button>
        {/if}
    </aside>

    <main class="stage">
        <div class="loader">
            <select bind:value={reciter} onchange={() => { selectReciter(); }}>
                {#each reciters as r}<option value={r}>{r}</option>{/each}
            </select>
            <select bind:value={chapter}>
                {#each chapters as c}<option value={c}>Surah {c}</option>{/each}
            </select>
            <input class="override" type="text" placeholder="audio URL override (optional)" bind:value={audioOverride} />
            <button onclick={loadChapter} disabled={loading || !reciters.length}>{loading ? 'Loading…' : 'Load live'}</button>
            <button onclick={loadDemo}>Demo</button>
            <span class="cat" class:warn={mode === 'demo'}>{mode}{audioCategory ? ` · ${audioCategory}` : ''}</span>
        </div>
        {#if error}<div class="err">{error}</div>{/if}
        {#if audioCategory && audioCategory !== 'by_surah'}
            <div class="warnbox">by_ayah times are per-verse-file relative — chapter-absolute alignment is only guaranteed for by_surah. Expect drift.</div>
        {/if}

        <div class="screen">
            <div class="meta">{units.length} words · {ayahs.length} ayahs · {fmt(durationMs)}</div>
        </div>

        <div class="faux-player">
            {#if units.length}
                <RecitationSection
                    bind:this={section}
                    {units}
                    {config}
                    {getTimeMs}
                    {playing}
                    context={`Surah ${chapter}`}
                    onSeekToWord={seekMs}
                />
            {/if}
            {#if ayahs.length}
                <AyahFilmstrip
                    bind:this={filmstrip}
                    {ayahs}
                    {durationMs}
                    {getTimeMs}
                    {playing}
                    {config}
                    {hoverMs}
                    onSeek={seekMs}
                />
            {/if}
            <div
                class="bar"
                role="slider"
                tabindex="0"
                aria-label="seek"
                aria-valuemin={0}
                aria-valuemax={durationMs}
                aria-valuenow={posMs}
                onclick={onBarClick}
                onpointermove={onBarHover}
                onpointerleave={() => (hoverMs = null)}
                onkeydown={(e) => {
                    if (e.key === 'ArrowLeft') seekMs(posMs - 5000);
                    else if (e.key === 'ArrowRight') seekMs(posMs + 5000);
                }}
            >
                <div class="track"><div class="fill" style="width:{pct}%"></div></div>
            </div>
            <div class="row2">
                <button class="play" onclick={toggle} aria-label="play/pause">{playing ? '❚❚' : '►'}</button>
                <span class="time">{fmt(posMs)} / {fmt(durationMs)}</span>
                <div class="picker-wrap">
                    <button onclick={() => (pickerOpen = !pickerOpen)} disabled={!verseNums.length}>Ayah {currentAyah ?? '—'}</button>
                    {#if pickerOpen}
                        <div class="picker-pop">
                            <AyahPicker verses={verseNums} value={currentAyah} onChange={seekToAyah} />
                        </div>
                    {/if}
                </div>
            </div>
        </div>

        <audio
            bind:this={audioEl}
            preload="metadata"
            onplay={() => (playing = true)}
            onpause={() => (playing = false)}
            ontimeupdate={onTime}
            onloadedmetadata={onMeta}
        ></audio>
    </main>
</div>

<style>
    .shell {
        display: grid;
        grid-template-columns: 360px 1fr;
        height: 100vh;
        overflow: hidden;
    }
    .panel {
        overflow-y: auto;
        overflow-x: hidden; /* no horizontal scrollbar in the controls sidebar */
        padding: var(--s-4);
        border-right: 1px solid var(--border-default);
        background: var(--panel);
    }
    /* Let flex inputs shrink below their intrinsic width so a row never forces
     *  the sidebar wider than it is (default min-width:auto would). */
    .row > input,
    .row > .pills {
        min-width: 0;
    }
    h1 { font-size: var(--fs-h3); margin: 0 0 var(--s-1); }
    .tag {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--accent);
        border: 1px solid var(--accent);
        border-radius: var(--r-1);
        padding: 1px 4px;
        vertical-align: middle;
    }
    .hint { color: var(--text-muted); font-size: var(--fs-meta); margin: 0 0 var(--s-3); }
    code { font-family: var(--font-mono); color: var(--text-secondary); }
    fieldset {
        /* Fieldsets default to min-inline-size:min-content, which makes them
         *  grow past the panel to fit a wide row. Reset so they obey the panel
         *  width and rows shrink to fit (no horizontal scroll/clip). */
        min-inline-size: 0;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        margin: 0 0 var(--s-3);
        padding: var(--s-2) var(--s-3) var(--s-3);
    }
    legend { font-size: var(--fs-meta); color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.05em; padding: 0 var(--s-1); }
    .row { display: flex; align-items: center; gap: var(--s-2); margin-top: 6px; font-size: var(--fs-meta); color: var(--text-secondary); }
    .row > span:first-child { width: 96px; flex: 0 0 auto; }
    .row.col { flex-direction: column; align-items: stretch; gap: 3px; }
    .row.col > span { width: auto; }
    .row input[type='range'] { flex: 1; }
    .row input[type='text'] { flex: 1; background: var(--canvas-inset); border: 1px solid var(--border-quiet); color: var(--text-primary); border-radius: var(--r-1); padding: 3px 6px; }
    .row em { width: 44px; text-align: right; font-style: normal; font-family: var(--font-mono); color: var(--text-faint); }
    .cpick {
        width: 28px;
        height: 24px;
        padding: 0;
        border: 1px solid var(--border-default);
        border-radius: var(--r-1);
        background: transparent;
        cursor: pointer;
        flex: 0 0 auto;
    }
    .cpick::-webkit-color-swatch-wrapper { padding: 2px; }
    .cpick::-webkit-color-swatch { border: none; border-radius: 2px; }
    .gtag {
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--accent);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        padding: 1px 5px;
        flex: 0 0 auto;
    }
    .pills { display: flex; flex-wrap: wrap; gap: 4px; flex: 1; }
    .pill {
        padding: 4px 9px;
        font-size: 10.5px;
        color: var(--text-secondary);
        background: var(--canvas-inset);
        border: 1px solid var(--border-quiet);
        border-radius: 999px;
        cursor: pointer;
        transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast);
    }
    .pill:hover { border-color: var(--border-strong); color: var(--text-primary); }
    .pill.on { border-color: var(--accent); color: var(--accent); background: var(--accent-tint); }
    .check { display: flex; align-items: center; gap: var(--s-2); margin-top: 6px; font-size: var(--fs-meta); color: var(--text-secondary); }
    .actions { display: flex; gap: var(--s-2); margin-top: var(--s-2); }
    .actions button, .loader button, .row2 button, .picker-wrap button {
        background: var(--panel-2); border: 1px solid var(--border-default); color: var(--text-primary);
        padding: 5px var(--s-3); border-radius: var(--r-2); cursor: pointer;
    }
    .actions button:hover { border-color: var(--border-strong); }
    .export { width: 100%; margin-top: var(--s-2); font-family: var(--font-mono); font-size: 11px; background: var(--canvas-inset); color: var(--text-secondary); border: 1px solid var(--border-quiet); border-radius: var(--r-2); }

    .stage { display: flex; flex-direction: column; min-width: 0; background: var(--canvas); }
    .loader { display: flex; gap: var(--s-2); align-items: center; padding: var(--s-3); border-bottom: 1px solid var(--border-default); flex-wrap: wrap; }
    .loader select, .loader .override { background: var(--canvas-inset); border: 1px solid var(--border-quiet); color: var(--text-primary); border-radius: var(--r-2); padding: 4px var(--s-2); }
    .loader .override { flex: 1; min-width: 180px; }
    .cat { font-family: var(--font-mono); font-size: 10px; padding: 2px 6px; border-radius: var(--r-1); background: var(--state-published-bg); color: var(--state-published-fg); }
    .cat.warn { background: var(--state-available-bg); color: var(--state-error-fg); }
    .err { padding: var(--s-2) var(--s-3); color: var(--state-error-fg); font-size: var(--fs-meta); }
    .warnbox { margin: var(--s-2) var(--s-3); padding: var(--s-2); font-size: var(--fs-meta); color: var(--state-error-fg); border: 1px solid var(--border-quiet); border-radius: var(--r-2); }

    .screen { flex: 1; display: flex; align-items: flex-end; justify-content: center; padding: var(--s-6); }
    .meta { color: var(--text-faint); font-size: var(--fs-meta); font-family: var(--font-mono); }

    .faux-player {
        position: relative;
        background: var(--panel);
        border-top: 1px solid var(--border-default);
        padding: 0 var(--s-4) var(--s-3);
        box-shadow: 0 -8px 24px oklch(0 0 0 / 0.25);
    }
    .bar { position: relative; height: 16px; display: flex; align-items: center; cursor: pointer; margin: var(--s-2) 0; }
    .track { position: relative; width: 100%; height: 3px; background: var(--canvas-inset); }
    .fill { height: 100%; background: var(--accent); }
    .row2 { display: flex; align-items: center; gap: var(--s-3); }
    .play { width: 40px; }
    .time { font-family: var(--font-mono); font-size: var(--fs-meta); color: var(--text-muted); }
    .picker-wrap { position: relative; margin-left: auto; }
    .picker-pop {
        position: absolute; bottom: calc(100% + var(--s-2)); right: 0;
        width: min(380px, 60vw); padding: var(--s-2);
        background: var(--panel); border: 1px solid var(--border-default);
        border-radius: var(--r-3); box-shadow: 0 16px 48px oklch(0 0 0 / 0.45); z-index: 50;
    }
</style>
