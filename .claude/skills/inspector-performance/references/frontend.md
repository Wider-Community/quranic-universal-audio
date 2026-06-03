# Frontend performance

Critical path, bundle/chunk shape, and the render-time rules. All paths under `inspector/frontend/` unless noted. The end goal is HF perf, but most FE measurements (bundle sizes, paint timings, Long Tasks, decode cost) transfer cleanly from local — see `probing.md` §local-vs-HF.

## Critical-path map

**Entry chain:** `index.html` → one ES module `/src/main.ts`. `main.ts` imports all 11 stylesheets synchronously, calls `installAudioWarmup()` (cheap — registers one-shot gesture listeners only), then `mount(App)`.

**Verified production build weights** (`dist/assets/`):

| Asset | Size | Loaded |
|---|---|---|
| `index-*.js` (main bundle — App + all 3 tabs + lib) | **774 KB** | render-blocking |
| `index-*.css` (all 11 stylesheets concatenated) | **946 KB** | render-blocking |
| `charts-*.js` (chart.js + annotation plugin) | 245 KB | lazy — gated behind StatsPanel dynamic import |
| `StatsPanel-*.js` | 8.4 KB | lazy |

**No `modulepreload` links are emitted** — the only split chunks (charts, StatsPanel) are reached via dynamic `import()`, so Vite doesn't statically preload them. Good default; nobody pays for charts on first paint.

**Tabs are NOT eager-mounted.** `App.svelte` gates each tab with the **two-layer pattern**: `mountedTabs: Set<string>` seeded with only the active tab (`App.svelte:38`), each tab wrapped `{#if mountedTabs.has(...)}` (`:142-160`) to defer first mount, then kept in DOM via `hidden={activeTab !== ...}` to preserve state across switches. A Dashboard-only visitor never mounts Timestamps or Segments — so their `onMount` fetches never fire.

**Per-tab first-interaction cost:**
- **Dashboard** — `loadCatalog()` (`catalog-data.ts`): `Promise.all([fetchPublicReciters({limit:500}), fetchPublicStats()])`, in-memory + in-flight-deduped.
- **Segments** — fires `loadQuranRefs()` (the **2.4 MB** `dk_words`+`verse_word_counts` bundle, sessionStorage-cached by content hash, version-checked), then `loadSegConfig()`, `loadReciters()`. Waveform peaks load lazily via `IntersectionObserver` (`rootMargin:200px`). The segment list is **virtualized** (`SegmentsList.svelte` + `virtualization.ts`).
- **Timestamps** — `setupZoomLifecycle()` + `init()`.

**Lazy boundaries that exist:** StatsPanel/chart.js (`{#await import(...)}` + role-gated to maintainer/owner, `SegmentsTab.svelte:347`); per-chapter peaks fetched on demand and sliced client-side; off-screen waveforms draw only when scrolled near (`unobserve` after draw).

## Contracts & invariants

1. **Block UI on minimum-viable data only.** Panels (history/stats) load on open, not on tab mount. Don't add an eager fetch to a tab's `onMount` if a user might never open that panel.
2. **`{#if mountedTabs.has(tab)}`, never bare `hidden=`.** `hidden=` keeps the component in the DOM AND fires its `onMount` (and all its fetches). The repo uses the two-layer gate; a 4th tab must follow both layers. Watch for PRs that "simplify" away the `{#if}` — that silently re-introduces cold-load fetches for users who never open the tab.
3. **Dynamic-import chunk gating.** Feature-subset code must not enter the 774 KB main bundle. Canonical example: StatsPanel/chart.js via `{#await import(...)}` + the `manualChunks` rule (`vite.config.ts:34-39`). A new heavy dep (PDF, chart, editor) gets the same treatment.
4. **Wire-shape discipline.** Catalog ships `limit=500`, filtered client-side — each field × hundreds of reciters × every visitor. Peaks travel as the **slim int8 base64 envelope** `{q:'int8', n, peaks_b64, duration_ms}`, decoded once via the single shared `b64ToInt8` (`lib/utils/peaks-decode.ts`) — ~25× lighter than the old float-list, used by both tabs so the byte interpretation can't drift.
5. **Audio preload audits.** Shell `BottomPlayer` + `SegmentsFooter` use `preload="none"`. But `AudioElement.svelte` / `AudioPlayer.svelte` default to `preload="metadata"`, and `HistoryPanel`/`SavePreview` mount them eagerly — **each fires a range/HEAD request on mount**. Prefer `preload="none"` for new playback surfaces unless metadata is needed immediately.
6. **`$effect` / reactive dependency hygiene.** Reactive blocks fire on every dependency change — guard with conditions, dedupe, subscribe to the narrowest derived value. Live cautionary example: `TimestampsTab.svelte:794-799` subscribes to a **derived, integer-deduped** `shuffleMode` "so one cycle step = one reprime — not the double-fire two boolean subscriptions caused."

## Good patterns (teach these)

- **Two-layer tab gating** (`App.svelte:38-160`) — defer *mount* (and its fetches), not just *visibility*.
- **In-flight + result dedupe stores** (`catalog-data.ts`, `quran-refs.ts`) — a module-level `inflight` promise + populated-check short-circuit; concurrent callers share one round-trip, re-renders don't refetch.
- **Content-hash sessionStorage cache for big immutable bundles** (`quran-refs.ts`) — version endpoint `no-cache`, payload immutable + hash-keyed, old-hash entries swept. The 2.4 MB bundle is fetched once per browser per deploy.
- **Slim int8 peaks + single shared decoder** — compute-once server-side, ship compact, decode once per chapter (~0.175 ms), then each verse is a ~2µs array slice vs 289–762 ms ffmpeg. Bounded LRU (`CHAPTER_PEAKS_CACHE=8`).
- **IntersectionObserver lazy waveforms + list virtualization** — off-screen rows do zero peak/render work.
- **Audio warmup on first gesture** (`lib/utils/audio-warmup.ts`) — play+pause a 250-byte silent MP3 to absorb the one-time decoder/output-device cold cost before the user's real Play.

## Antipatterns / regrets / forward guidance

- **946 KB single CSS file** — all 11 stylesheets imported synchronously in `main.ts` concatenate into one render-blocking file, *larger than the JS bundle*, and it is **not** lazy. "Had we route-split CSS by tab (or leaned harder on component-scoped styles) first," Dashboard-only visitors wouldn't download Segments/Timestamps/validation/history CSS. This is the single biggest first-paint payload. Flag any new top-level `.css` import in `main.ts`.
- **774 KB monolithic JS** — `vite.config.ts` has exactly one `manualChunks` rule (charts). Everything else (all 3 tabs, all of `lib/`) is one chunk. The `{#if mountedTabs}` gate defers *execution*, but the *code still ships*. "Had we set per-tab dynamic-import boundaries first" (e.g. `import('./tabs/segments/SegmentsTab.svelte')` on first visit, mirroring StatsPanel), a Dashboard visitor would download far less JS. Strong candidate when bundle size becomes a complaint.
- **2.4 MB quran-refs on Segments mount** — mitigated (Segments-only, sessionStorage-cached) but still an all-at-once decode + heap cost the first time. Don't widen it; per-chapter ref slices would have made it incremental.
- **`preload="metadata"` default proliferation** — every mounted instance fires a network request; `HistoryPanel`/`SavePreview` mount them eagerly. Default to `preload="none"`.
- **Over-firing `$effect`/reactive blocks** — the shuffle double-fire is the cautionary tale: two boolean subscriptions instead of one derived-deduped value doubled work per cycle step. On a single-worker backend, an extra FE fetch per fire compounds per concurrent user.
- **~3 MB peaks heap** — even with int8, holding many decoded chapters + per-segment covering-range caches grows the heap. Keep caches bounded (`CHAPTER_PEAKS_CACHE=8`; `resetWaveformState()` clears per-reciter); never hold unbounded per-segment peak arrays. (History peaks are now `Int8Array` too — only the Tier-2 ffmpeg fallback still yields `PeakBucket[]`.)

## Measuring FE perf

Most FE numbers come from driving the live stack with Playwright/Chrome MCP — see `probing.md` for the exact `browser_evaluate` recipes (cold-load nav/paint timing, heaviest-resource breakdown, Long-Task observer, payload-size diff). For **build-only size diffs** (no browser), `ls -l inspector/frontend/dist/assets/` after `npm run build` gives chunk byte counts directly — the fastest way to confirm a dependency didn't leak into the 774 KB main chunk.
