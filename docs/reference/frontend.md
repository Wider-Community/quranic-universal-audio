# Frontend

Three-tab SPA at `inspector/frontend/src/`. TypeScript (strict) + Vite + Svelte 5 runes. Built to `frontend/dist/`, served by Flask (`FRONTEND_DIST` in `app.py`).

## Stack

| Concern | Choice |
|---|---|
| Language | TypeScript strict (`strict`, `noUncheckedIndexedAccess`, `noImplicitAny`, `strictNullChecks`) |
| Bundler | Vite 5, `target: es2022` |
| UI | Svelte 5 (`@sveltejs/vite-plugin-svelte` ^4, mounted via `mount()` in `main.ts`) |
| Charts | Chart.js 4 + chartjs-plugin-annotation; split into a `charts` chunk via `rollupOptions.output.manualChunks` |
| CSS | Plain CSS in `src/styles/`, imported from `main.ts` (`tokens.css` first — defines `:root` vars) |
| Audio | Web Audio API; per-tab `AudioPort` transport (`lib/playback/`) |
| Unit tests | Vitest 3 + `@testing-library/svelte` 5 + `happy-dom` |
| E2E | Playwright (`npm run test:e2e`) |
| Typecheck/lint | `tsc --noEmit`, `svelte-check` (`npm run check`), eslint flat config |

`vite.config.ts` proxies `/api` and `/audio` to Flask `:5000` during dev (`:5173`). Two-stack mode via `INSPECTOR_VITE_PORT` / `INSPECTOR_BACKEND_PORT`. Sourcemaps dev-only.

## Svelte version convention

New code is **Svelte 5 runes**: `$state` / `$derived` / `$effect` / `$props` / `$bindable`, callback props. Legacy Svelte 4 syntax (`export let`, `$:`, `createEventDispatcher`, `on:` directives, `<slot>`) still compiles via the compat shim and is migrated opportunistically (plan: `docs/planning/svelte-migration.md`). A file is fully one mode or the other — never mixed.

**Currently still legacy** (notable): `App.svelte`, `AccordionGuideModal.svelte`, and the imperative canvas/audio components.

**Deliberately exempt (stay legacy indefinitely):** `TimestampsWaveform.svelte` and the canvas/audio-imperative components (`WaveformCanvas.svelte`, `SegmentWaveformCanvas.svelte`, and the per-frame overlay drivers).

## Layered diagram

```
main.ts (mount App, import global styles, installAudioWarmup)
  └── App.svelte  (header/tab-bar, auth controls, lazy tab mount, global popover/modal/toast/bookmarks)
        ├── tabs/dashboard/DashboardTab.svelte   → views/{CatalogList,ReciterDetail} + BottomPlayer
        ├── tabs/timestamps/TimestampsTab.svelte → {components,stores,utils,services}/
        └── tabs/segments/SegmentsTab.svelte     → {components,stores,utils,domain,types,guides}/
```

Tabs are lazy-mounted (`{#if mountedTabs.has(tab)}`); once visited they stay in the DOM `hidden`, preserving state across switches. `AudioPort`s are paused on tab-leave by `applyTabSideEffects` — `segPort` (Segments) and the shared `dashPort` (Dashboard **and** Timestamps, via `BottomPlayer`); `tsPort` is defined but vestigial. `lib/` is strictly cross-tab; `lib/` never imports `tabs/`, and no tab imports another tab's dir. Audio playback internals (AudioPort, kill-switch, peaks) live in the **`inspector-audio` skill**, not here.

The **Dashboard tab** is the entry view: public reciter browse/search/filter/play for all visitors, plus admin (maintainer/owner) controls — activity rail, claim/state actions, request review. It is the default landing tab (legacy `insp_active_tab='audio'` redirects here; the old Audio tab is removed — `App.svelte::cleanupLegacyAudioKeys` sweeps `insp_aud_*` localStorage keys).

## `lib/` — cross-tab only

### `lib/actions/`

| File | Role |
|---|---|
| `editGate.ts` | Svelte action gating any edit-trigger click on `editingMode`; passes through for `editor`/`maintainer`/`owner` (or admin-only with `{require:'admin'}`), else swallows click + surfaces `EditAffordancePopover` or sign-in modal. Capture-phase. |
| `click-outside.ts` | Action: callback on pointerdown outside the node (popover/dropup dismissal). |

### `lib/api/`

| File | Role |
|---|---|
| `index.ts` | Single fetch boundary — `fetchJson` / `fetchJsonOrNull` / `fetchArrayBuffer` typed helpers |
| `auth-client.ts` | `signIn` (→ `/api/auth/login`) / `signOut` (→ `/api/auth/logout` + reset `currentUser`) |
| `claims-client.ts` | Claim POSTs; maps 200/401/403/409 → row resolve / sign-in modal / toast |
| `dev-role.ts` | `POST /api/dev/role` (dev-mode only; 404s on Space) |
| `reciter-task.ts` | `readable` store polling `/api/reciter-task/<slug>` @30 s while subscribed |
| `public-reciters.ts` | Read-only `/api/public/*` reciter list fetchers (no auth, `max-age=30`) |
| `public-reciter-detail.ts` | Single-reciter detail; `null` on 404 |
| `public-activity.ts` | Public activity feed (`/api/public/activity`, six-event allowlist) |
| `public-activity-admin.ts` | Owner-only `DELETE /api/public/activity/<audit_id>` — global tombstone for a public-feed card. (The admin notifications rail was retired; admin awareness lives in the Admin dashboard tabs now.) |
| `requests.ts` | Request submit (contributor+) / admin review-reject / undiscard (owner) |

### `lib/playback/`

| File | Role |
|---|---|
| `audio-port.ts` | `AudioPort` — single transport chokepoint; owns `<audio>`, CBR-chapter-vs-VBR-clip src swap, file-absolute ms via `offsetMs` |
| `audio-graph.ts` | Web Audio kill-switch — sample-accurate gain ramp (`cutAudio`/`uncutAudio`) to flush OS-queued tail |
| `audio-range.ts` | `AudioRange` — one-rAF-loop `[startMs,endMs]` playback with pluggable boundary policy (stop/loop/advance) |
| `dash-port.ts` | Dashboard-tab `AudioPort` instance (`dashPort`) |
| `shadow-audio.ts` | Hidden `<audio>` for cross-chapter prewarm (validation accordion) without disturbing `segPort` |
| `constants.ts` | Playback constants (coverage padding, etc.) shared across port/range consumers |

### `lib/components/`

| Path | Role |
|---|---|
| `WaveformCanvas.svelte` | Base canvas peaks renderer; exposes canvas for imperative overlays (legacy/exempt) |
| `AudioElement.svelte` | Thin `<audio>` wrapper (safePlay, events) |
| `AudioPlayer.svelte` | Full audio player UI |
| `SearchableSelect.svelte` | Dropdown with fuzzy search + grouped options |
| `SpeedControl.svelte` | Playback speed selector |
| `Modal.svelte` | Generic modal shell — focus trap, Esc/backdrop close, body scroll lock. Its backdrop portals to `document.body` (`lib/actions/portal.ts`) so a deeply-mounted modal escapes ancestor stacking contexts (e.g. the sticky dashboard rail) and paints above fixed app chrome like `BottomPlayer`. |
| `SignInModal.svelte` / `ToastHost.svelte` | Root-mounted sign-in modal + toast host |
| `EditAffordancePopover.svelte` | Single global popover surfaced by `editGate` |
| `DevRoleSwitcher.svelte` | Dev-mode role switcher (gated on `$currentUser.dev_mode`) |
| `BookmarksPanel.svelte` | Quran.Foundation bookmarks sidebar |
| `ClaimButton.svelte`, `StatePill.svelte`, `CoveragePill.svelte`, `FilterPill.svelte`, `ReciterChip.svelte`, `ReciterRow.svelte`, `SearchInput.svelte`, `ExternalLinks.svelte` | Catalog/dashboard chips, pills, rows |
| `picker/` | `CombinationPicker` + `PickerFilterRail` / `PickerFooter` / `PickerStateTabs` / `PickerReviewStatus`. For callers holding `reviews.view`, the picker lazily fetches `/api/admin/reviews/list` on open and decorates `under_review` rows with the claimer + a marked-ready badge (`PickerReviewStatus`) — same data as the Admin → Reviews tab. Non-capable callers fire no admin fetch. |
| `player/` | `BottomPlayer`, `PlayerControls`, `PlayerProgress`, `PlayerMetaChip`, `SpeedPopover`, `SurahPopover` |

Shared player rule: deliberate navigation resumes playback even when the audio was paused. This includes ayah/surah steps, surah or delivery changes, progress/filmstrip/line seeks, Timestamps keyboard navigation, validation jumps, and manual shuffle/random-reciter triggers. Passive inspection (popovers, hover previews, zoom/pan, speed/download/bookmark/display toggles) must stay paused.

Recitation-animation (`lib/recitation-animation/`, mounted by `NowReciting` above the player in both Dashboard + Timestamps tabs): the `AyahFilmstrip` ayah scrubber and the `LineAnimation` teleprompter are **recitation-driven, not clock-driven**. Both map playback time → the recited word via the shared `findActiveAt` (`recitation-active.ts`): a flat per-occurrence interval timeline that returns `null` during silence gaps and travels backward on loopbacks (the raw, non-deduped occurrences the shard retains "for the filmstrip" — see [timestamps-job.md](timestamps-job.md) §1a). The filmstrip's per-verse cell bar fills to the recited word's **duration-weighted** position in the verse (`filmstrip-model.ts`), so a within-verse word loopback rewinds the bar and a cross-verse loopback scrolls the strip back (same glide in both `snap`/`hybrid` modes). The bottom `PlayerProgress` scrubber stays time-linear — only the cell bar is recitation-adaptive.

**Strip scroll motion** is unified in one controller — `createStripScroller` (`filmstrip-scroll.svelte.ts`) — shared by every motion model (`snap`/`hybrid`/`tuner`) and every play/pause path, with one curve and one set of constants, owning its own rAF so a glide animates whether or not audio is playing. Continuous progression — forward playback, live drag/scrub, and the between-verse gap-scroll below — tracks the live position **instantly** (`snap`/`follow`), so it moves at the ruler velocity (`filmstripPxPerSec`). Every *discontinuity* (within-verse rewind, multi-verse loopback, click, key, snap-center, drag-release, paused refresh) instead runs one distance-proportional **Hermite** glide (`glide`, or the `follow` catch-up), **independent of the ruler velocity** — a jump is smoothed, not replayed in time. A catch-up chasing a moving target re-plans each frame **carrying current velocity**, so it never lurches and never inherits a stale cutoff. For a **natural loopback** (the reciter re-reciting — a backward recitation jump with no audio-time seek), `AyahFilmstrip` crosses the replayed span at **one constant velocity** rather than tracking each replayed word (whose second-take pace differs from the first, which would vary the speed): a time-linear ramp from a start offset to the looped-from offset over the replay window (the rejoin read from the unit's occurrence intervals), fed to the controller — the eased `follow` catch-up does the quick hop back onto the ramp, then rides it, and instant tracking resumes at the rejoin. A **mid-verse** landing shifts the start so the velocity equals the ruler `pxPerSec` (both takes match); a **verse-start** landing pins the start and holds one constant velocity that steps to the ruler speed at the rejoin (`planRetread` / `retreadAt`). When the replay never re-reaches the looped-from word, it falls back to the plain catch-up. `AyahFilmstrip` keeps only the recitation-discontinuity *detection* (`isJump` / `SEEK_JUMP_MS`), the loopback re-tread, and the one-shot fill-bar glide (which shares the controller's `glideDur`).

**Silence handling.** A "pause" is just a positive timing gap between consecutive units (contiguous units share an ms-quantized boundary, so a gap means the aligner inserted `sil`/`sp` — a detected silence). Each surface surfaces it:
- **Filmstrip** — `snap` mode freezes during silence (active cell de-highlights, no needle). The **scrolling** modes (`hybrid`/`tuner`) no longer freeze: the needle stays visible but **greys** (`--text-muted`) and scrolls **continuously** across the inter-cell gap for a between-verse pause (`scrollThroughGap` interpolates offset by elapsed-silence; `nextIntervalAfter` resolves the upcoming cell). Within-verse / leading / trailing silence holds. The strip is a **fixed-scale time-ruler at one global velocity** (`config.filmstripPxPerSec`, default 12 px/s): cell width = `max(filmstripMinCellPx, canonDurSec × pxPerSec)` and inter-cell gap = `VerseCell.nextGapSec × pxPerSec` (between-verse silence, measured from the verse's real `canonEndSec` so within-verse pauses never leak in). The cursor therefore travels at this one velocity everywhere — within cells and across silences — and a given silence renders to the **same px in every surah and for every reciter** (no per-chapter normalization; the prior `maxCellPx / maxDur` anchor scaled silences to the longest verse, so they flattened on long surahs). Geometry is identical across motion modes (toggling never shifts the strip — only the cursor's motion differs). A too-short verse is **floored to `filmstripMinCellPx`** (18) so its ayah number stays legible; to keep the floor from speeding the cursor up, each cell carries a time-true span `aw = canonDurSec × pxPerSec` and the cursor crosses only that **centered** span at the ruler velocity (`offsetForReci`), the surplus `w − aw` **absorbed into the adjacent gap** (where the greyed needle already scrolls the silence). An unrecited placeholder, which has no recited time, gets a fixed visible width. A near-zero silence floors to `filmstripGapPx` (2). No max cap — a long verse is just a wide cell scrolled through at constant velocity.
- **Analysis view** (`UnifiedDisplay`) — each inter-word silence renders a small **pause bridge** between the two word columns (mirroring the `crossword-bridge` slot). While its silence plays it lights and the rest of the row dims to 70% (`.in-pause`); waveform-hover over the gap previews it. If the paused-on word carries a surfaced **waqf (stop) mark** it is lifted out of the word box into the bridge; otherwise the bridge shows the neutral two-bar pause icon.
- **Teleprompter** (`LineAnimation`) — stop marks are split out of the reveal (`build-structure.ts` → `AnimWord.clean`/`waqf`) so they never join the per-letter/word highlight, and rendered as a separate `.ra-waqf-mark` **overlay**. A combining mark is painted in the colour of whatever run it shapes into (true for HTML *and* SVG `<tspan fill>`), so to get the mark's natural font-anchored position *and* an independent colour/opacity, the overlay is a second copy of the full word in one run, `clip-path: inset(0 0 70% 0)`-clipped to the high waqf register so **only the mark paints** (the letters are clipped away → no extra ink, opacity is fully independent, no bleed into the per-letter reveal). The reveal sweep (`sweepWaqf`) adds `.revealed` (opacity→1) when the mark's own last letter is reached, and `.waqf-active` (highlight) only while a pause holds on its word — it never gets the reveal highlight.

Stop-sign detection is one shared util — `lib/utils/waqf.ts` (`splitWaqf`/`hasWaqf`), the surfaced marks being U+06D6–U+06DB **excluding** U+06D9 (لا, "do not stop"); U+06DC (saktah) is also not surfaced.

**Coverage markers.** `load-chapter.ts` derives a per-chapter `coverage` (incomplete + fully-missing verses) entirely client-side — diffing the canonical recited words against the reference word counts from the qpc verse index (`ts-source.loadQpcVerseIndex`, one memoized scan of the qpc the animation already loads; `recitation-data/coverage.ts`, mirroring the backend `select_complete_verses` gate). `buildFilmstripModel(units, weighting, coverage?)` then tags present cells `none`/`words` and inserts a `full` **placeholder cell** for each unrecited verse (no units/geometry) so the gap stays visible. In `AyahFilmstrip`, a `words` cell rings red (`--state-missing-*`, still clickable + plays), a `full` cell is a dimmed red placeholder that playback + all user-nav (click/arrow/drag, both motion modes) skip (non-clickable). The active cell's status is reported via `onActiveCell`, and `NowReciting` shows a contextual "missing words" pill in its handle row **only** while the selected verse is itself incomplete.

### `lib/catalog/`, `lib/refs/`, `lib/icons/`

| Path | Role |
|---|---|
| `catalog/schema-descriptor.ts` | Schema descriptor for the dashboard secondary facet rail (operates on combinations/`PublicDelivery`) |
| `refs/quran-refs.ts` | `dk_words` + `verse_word_counts` behind one content-hashed endpoint; fetched once per browser, shared via store |
| `icons/Icon.svelte` + `*.svg` | Inline SVG icons via `{@html}` (`currentColor` cascade) |

### `lib/types/`

| File | Role |
|---|---|
| `generated/schemas.ts` | **Codegen'd FE data contracts** — `scripts/codegen/regen_fe_types.py` over `qua_shared/schemas/fe_types.py` (Pydantic → JSON Schema → TS). Never hand-edit; CI `schema-codegen-check` gates it. The `bucket/` artefact shapes (`Segment`, `EditOp`, `PeakBucket`, `HistoryBatch`, `PhonemeInterval`, …) **and** the `wire/` `seg`/`ts`/`public`/`audio` request/response shapes are now modeled there and codegen'd. |
| `view-models.ts` | **FE-only** view-models + derived reads with no single wire producer: the editor's working `Segment` superset, the `EditOp`/`EditOpPatch`/`HistoryBatch` history views, `GenerationBoundary`/`HistorySummary` rollups, `Actor`, the `Ref`/`VerseRef` string aliases, and the derived `/api/seg/*` reads (`SegEditHistoryResponse`, `SegStatsResponse`, …). |
| `peaks-transport.ts` | **FE-only** waveform transport — `PeakBucket`/`AudioPeaks`/`SegmentPeaks`, including the flag-gated `Int8Array` drawer branch (no wire model). |
| `ts-client.ts` | **FE-only** Timestamps-tab client types — the `TsVerseData` verse model, slim `TsCatalog*` projection, positional shard reads (`TsShardWord`/`SegmentEntry`/`TsShardResponse`), `SurahInfo*`, and the deprecated legacy `Ts*Response` shapes. |
| `public-bucket.ts` | **FE-only** public-bucket display vocabulary — `PublicBucket`/`AdminBucket`, the `PUBLIC_BUCKET_LABELS`/`PUBLIC_BUCKETS`/`BUCKET_PRIORITY` tables, `bucketRank`, and `CoverageKind`. |
| `ui.ts` | Shared UI types for components |

### `lib/stores/` (cross-tab)

| File | Role |
|---|---|
| `current-user.ts` | `currentUser` writable (loaded from `/api/me`); `isSignedIn()`; derived `isAdmin` (maintainer\|owner), `isOwner`; `loadCurrentUser()` / `resetCurrentUser()`. Dashboard-level gating. |
| `editing-mode.ts` | `editingMode` writable (`view`/`editor`/`maintainer`/`owner` + `viewReason`); pure `syncEditingMode(user,task)`; derived `editingDisabled`, `isAdmin`. Reciter-scoped gating — see `editGate`. |
| `edit-popover.ts` | State for the `editGate`-surfaced popover (`showEditPopover`) |
| `sign-in-modal.ts` | `openSignInModal` state |
| `toast.ts` | Toast queue |
| `bookmarks.ts` | Bookmarks panel toggle |
| `player-context.ts` | Cross-tab bottom-player context |

### `lib/utils/`

| File | Role |
|---|---|
| `active-tab.ts` | Active-tab store + get/set |
| `constants.ts` | `LS_KEYS`, `TAB_NAMES` |
| `animation.ts` | `createAnimationLoop()` — rAF loop with start/stop |
| `chart.ts` | Chart.js bootstrap (registers plugins) |
| `audio.ts` | `safePlay()` (swallows AbortError), `audioSrcMatches` |
| `audio-warmup.ts` | First-gesture audio decoder/output warm-up |
| `preconnect.ts` | DNS preconnect helper |
| `peaks-fetch.ts` | Cross-tab `/api/seg/segment-peaks` fetch |
| `peaks-view.ts` | Peaks-shape adapter (legacy nested `[min,max][]` vs int8) |
| `waveform-cache.ts` | Normalized-URL → peaks Map (non-reactive) |
| `waveform-draw.ts` | Peaks → canvas draw (`drawWaveformPeaks`) |
| `arabic-text.ts` | `stripTashkeel`, combining-mark helpers |
| `waqf.ts` | Quranic waqf (stop) marks — `splitWaqf`/`hasWaqf` (U+06D6–U+06DB, excludes لا U+06D9 + saktah U+06DC). Shared by the analysis pause bridge + teleprompter stop-sign handling |
| `fuzzy-match.ts` | Arabic-normalizing search: memoized `normalizeArabic`, `match`, and `filterByFields` (the shared multi-field filter behind every reciter/option search bar) |
| `list-virtualization.ts` | Pure prefix-sum windowing helpers for variable-height virtual lists (CatalogTable + SegmentsList) |
| `surah-info.ts` | `surahInfo` data + ready promise + `surahOptionText` |
| `grouped-reciters.ts` | Grouped reciter dropdown options |
| `keyboard-guard.ts` | `shouldHandleKey(e, tab)` |
| `derived-eq.ts` | Deep-equality derived store helper |
| `svg-arrow-geometry.ts` | `computeArrowLayout()` for history diff arrows |
| `word-boundary.ts` | Word-boundary helpers |
| `speed-control.ts` | Speed option list |
| `formatting.ts` | `_formatBytes` |
| `facets.ts` | Faceted-count helper (history filters, dashboard rail, picker) |
| `visible-poll.ts` | Page-Visibility-aware polling |
| `relative-time.ts` | "3 hours ago" labels for activity/detail |
| `axis-labels.ts` | Resolve schema axis/tag keys → human labels |
| `delivery-label.ts` | Catalog vocab slug → display name |
| `delivery-sort.ts` | Canonical combination sort order used by reciter detail, player switcher, and dashboard row play defaults |
| `countries.ts` | ISO-3166-1 alpha-2 list (build-time embedded) |

## Tabs

### `tabs/dashboard/`

Entry view: public catalog browse/search/filter/play + admin controls.

| Path | Role |
|---|---|
| `DashboardTab.svelte` | Root — `CatalogList` + `ReciterDetail` modal + `BottomPlayer` |
| `views/CatalogList.svelte` | List view; filters on combinations, grouped back by reciter |
| `views/ReciterDetail.svelte` | Reciter detail modal (flat combination table, status-priority sort) |
| `components/CatalogTable.svelte` | Virtualized reciter list (own scroll container; windowing via `lib/utils/list-virtualization.ts`) |
| `components/DetailHeader.svelte`, `FactsList.svelte`, `StateTimeline.svelte` | Detail/table pieces |
| `components/ActivityRail.svelte` | Public activity feed (owner-visible delete affordance on each card) |
| `components/RequestForm.svelte`, `submit/{SubmitWizard,StepReciter,StepSource,StepDetails}.svelte` | Request/submit flow |
| `stores/catalog-data.ts` | Full public reciter roster (paginated) + stats, cached in-memory; visibility-aware poll skips no-op refreshes |
| `stores/dashboard-state.ts` | Filter/sort/search + detail-modal flag (mounted at root, survives modal) |
| `stores/submit-wizard.ts` | Submit-recitation wizard FE state (3-step) |

### `tabs/timestamps/`

Waveform + phoneme display for published reciters (plus owner preview of generated-but-unreleased shards — the read-path honors the `timestamps.view_unreleased` capability; see [timestamps-job.md](timestamps-job.md)). Shards are temporal segment-array `.json.gz` (every recited segment raw, recitation order; served as a byte pass-through). `ts-source.ts` groups segments by verse and reduces each verse to its canonical (completing) occasion for the default per-verse clip.

| Path | Role |
|---|---|
| `TimestampsTab.svelte` | Shell — reciter/chapter/verse cascade, config→CSS vars, view toggle, keyboard, waveform animation (imperative) |
| `components/` | `UnifiedDisplay`, `AnimationDisplay`, `TimestampsWaveform` (exempt), `TimestampsControls`, `TimestampsAudio`, `TimestampsKeyboard`, `TimestampsViewControls`, `TimestampsShortcutsGuide`, `TranslationLangSelect`, `WordTranslation` |
| `services/ts_client.ts` | Shard-fetch data layer (manifest + per-chapter shards; local Flask + HF CDN same shape) |
| `utils/` | `constants.ts`, `loop-target.ts`, `zoom.ts`, `range-spec.ts`, `audio-load.ts` |

**Stores:** `verse.ts` (reciter/chapter/verse selection + `loadedVerse` + `validationData`), `display.ts` (view mode, granularity, show-tashkeel/phonemes; localStorage-persisted), `playback.ts` (auto-play, `currentTime`; defines `tsPort` but the tab plays through the shared `dashPort`), `zoom.ts` (slice-relative visible window).

### `tabs/segments/`

Full WIP editor — trim/split/merge/re-reference, auto-validation on save.

| Path | Role |
|---|---|
| `SegmentsTab.svelte` + `ShortcutsGuide.svelte` | Shell — dropdowns, filter bar, nav banner, list, CSS-var config, keyboard |
| `components/list/` | `SegmentsList`, `SegmentWaveformCanvas` (exempt), `Navigation`, `TimeEdit`, `TimeRange` (windowing math in shared `lib/utils/list-virtualization.ts`) |
| `components/filters/` | `FiltersBar`, `FilterCondition` |
| `components/edit/` | `EditOverlay`, `MergePanel`, `DeletePanel` |
| `components/history/` | `HistoryBatch`, `HistoryOp`, `HistoryArrows`, `EditChainRow` |
| `components/save/` | `SavePreview` |
| `components/stats/` | `StatsPanel`, `StatsChart`, `ChartFullscreen` |
| `components/validation/` | `ErrorCard`, `MissingWordsCard`, `MissingVersesCard`, `AccordionGuideModal` (legacy) |
| `components/footer/` | tab footer |
| `domain/` | `identity.ts`, `inverse-patch.ts` (paired with backend `domain/`), `registry.ts` (issue registry — paired with backend), `sorting.ts` (accordion sort abstraction) |
| `types/` | `segments.ts`, `stats.ts` |
| `guides/` | Accordion help-modal guide system — see `accordion-guides.md` |

**Stores:** `segments.ts` (normalized state by uid, IS-7), `edit.ts` (bundled 8-field edit state + `activeTrimBoundary` + `splitPreviewSelection`), `history.ts` (edit-history view), `validation.ts` (`SegValidateResponse`), `validation-sort.ts` (per-accordion sort prefs, localStorage `insp_seg_val_sorts`), `save.ts` (save-preview), `autosave.ts` (localStorage pref), `active-actions.ts` (focused-row action bundle for keyboard dispatch), `chapter.ts`, `chapter-meta.ts`, `config.ts`, `dirty.ts`, `filters.ts`, `navigation.ts`, `playback.ts` (`segPort`), `stats.ts`, `accordion-pin.ts`, `merge-redirect.ts`, `undo-pending.ts`.

**`utils/` (grouped):** `accordion-nav.ts` (DOM-read card sequence for ↑/↓ + autoplay inside an open accordion), `data/` (selection/filter/reciter/chapter actions, config loader, references, per-reciter state clear), `edit/` (trim/split/merge/delete/ignore/reference/setIsWasl/auto-fix/enter/common), `history/` (loader/actions/chains/items/render), `playback/` (`playback.ts` playhead overlay, `play-range.ts`, `range-spec.ts`, `preview.ts`, `resolvers.ts`, `source.ts`, `warmup.ts`, `row-registry.ts`), `save/` (payload/preview/execute/undo/actions), `validation/` (classified-issues, conf-class, card-lead-seg, missing-verse-context, refresh, resolve-issue, split-group, stale), `waveform/` (`draw-seg.ts`, `split-draw.ts`, `trim-draw.ts`, `op-peaks.ts`, `peaks-cache.ts`, `utils.ts`).

**Keyboard shortcuts** (`shortcuts/` + `utils/keyboard.ts`): `shortcuts/defaults.ts` is the catalogue (id · label · context · default key · rebindable); `shortcuts/store.svelte.ts` holds user overrides (localStorage `insp_seg_shortcuts`, runes `$state`) and the `resolve(token, context)` reverse lookup. `handleSegmentsKey` picks a context — `edit` (trim/split: ←/→ stepper, Tab cycles cursor/region, Enter/Escape), `accordion` (a validation accordion is open: ↑/↓ + autoplay walk the `accordion-nav` sequence, G/C/L/F act on the focused card), or `default` — then dispatches the resolved action. Row/card edit actions (A/S/E/G/L/F/C) route through the `active-actions` registry, which the primary SegmentRow publishes; accordion cards forward their ignore/auto-fill/toggle-context callbacks via SegmentRow's `onCard*` props. The footer `ShortcutsGuide.svelte` (left of the speed control) is the reference + inline rebinder; the old reference accordion in `GuidesGateModal` is gone.

**Validation accordion sorts** (`domain/sorting.ts` + `stores/validation-sort.ts`): a declarative, FE-only sort abstraction. Each registry row declares the sort options it offers via `IssueDefinition.sorts` (e.g. Low Confidence → `confidence` (default) + `quran_order`; Missing Words → `quran_order` + `word_count`; Cross-verse → `quran_order` + `verse_count`; Repetitions → `quran_order` + `rep_split_count`); Missing Verses and the non-registry Flagged accordion offer none. `sorting.ts` owns the key extractors (`quran_order` reads `(chapter, seg_index)`, falling back to `verse_key`/`ref`; counts read the relevant field; `rep_split_count` reads `refs.length` from the auto-split map) and `sortItems`, which orders by the active `(kind, dir)` and breaks ties with the *other* offered option ascending. `ValidationPanel` renders one pill per option in the accordion header — click to select, re-click the active pill to flip ▲/▼ — and applies the sort in `projectVisible`. Choice + direction persist globally (not per-reciter) in `valSortPrefs`; `resolveSort` falls back to the registry default and rejects a stored kind a category no longer offers. The `sorts` field is deliberately absent from the Python registry and its parity snapshot.

## Hybrid imperative canvas pattern

Canvas waveform components expose the raw `<canvas>` so overlay code draws directly each animation frame, avoiding reactive re-renders at 60 fps. Drivers:
- `tabs/segments/utils/playback/playback.ts` (playhead overlay)
- `tabs/segments/utils/waveform/{split-draw,trim-draw}.ts` (edit overlays)
- `TimestampsTab.svelte` / `TimestampsWaveform.svelte` (waveform animation)

These components stay Svelte-4 legacy by design (`docs/planning/svelte-migration.md` exempt list). `lib/utils/animation.ts::createAnimationLoop()` wraps the rAF lifecycle.

## Client caching

| Cache | Location | Invalidation |
|---|---|---|
| Segment peaks | `tabs/segments/utils/waveform/peaks-cache.ts` (lazy via IntersectionObserver) | reciter/chapter change |
| Audio peaks (cross-tab) | `lib/utils/waveform-cache.ts` (Map keyed by normalized URL) | manual |
| Quran refs bundle | `lib/refs/quran-refs.ts` (one content-hashed fetch/browser) | content hash (never per-session) |
| Catalog list + stats | `tabs/dashboard/stores/catalog-data.ts` (in-memory snapshot) | first read only |
| Audio transport/prewarm | per-tab `AudioPort` + `lib/playback/shadow-audio.ts` | tab-switch / chapter change |

## Build outputs

`frontend/dist/` is gitignored. `npm run build` = `tsc --noEmit && vite build` → hashed JS + CSS, Chart.js in a separate `charts` chunk. Run before launching Flask in production mode.
