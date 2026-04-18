# Inspector — CLAUDE.md

Flask SPA (port 5000) for inspecting Quran recitation alignment results. Three tabs: **Timestamps** (waveform + phoneme display), **Segments** (browse/edit alignment output), **Audio** (hierarchical recording browser). The Segments tab is a full editor — adjust boundaries, split, merge, re-reference, save back to JSONL with auto-validation.

## Running

```bash
# 1. Build the frontend (one-time / after TS changes)
cd inspector/frontend && npm install && npm run build

# 2. Run Flask — serves API + the built `frontend/dist/` SPA
python3 inspector/app.py          # http://localhost:5000

# 3. (optional) Dev mode with HMR
cd inspector/frontend && npm run dev   # http://localhost:5173
# Vite proxies /api and /audio to Flask on :5000 (see vite.config.ts)
```

## Tech Stack

- **Backend:** Python / Flask (Blueprints), no ORM
- **Frontend:** TypeScript + Vite (ES modules, bundled); strict TS (`strict: true`, `noUncheckedIndexedAccess: true`, `allowJs: false`)
- **Charts:** Chart.js (npm) + `chartjs-plugin-annotation`, registered centrally in `src/lib/utils/chart.ts`
- **CSS:** Plain CSS split by domain (no preprocessor, no CSS-in-JS), imported from `src/styles/`
- **Audio:** Web Audio API (waveform decoding/drawing), ffmpeg (server-side peak extraction)

## Code Principles

These principles were established during the modular refactor and MUST be followed:

- **Single responsibility** — every file does one thing. Prefer creating a new file over growing an existing one.
- **Small files** — target ~200-300 lines. Split or restructure when files get too big. New folders when a directory gets crowded.
- **Config-centered** — all tuneable constants, thresholds, timeouts, and magic numbers live in `config.py`. Never hardcode.
- **DRY** — no duplicated logic. Extract shared helpers to `utils/` (Python) or `lib/` (JS).
- **No dead code** — remove unused functions, variables, selectors, and imports immediately.
- **No magic numbers** — every threshold, timeout, dimension, and limit has a named constant in `config.py` or `lib/utils/constants.ts`.
- **Clean imports** — Python services never import Flask. Routes are thin (parse request → call service → jsonify). JS modules use explicit ES module imports.
- **Cache via getter/setter** (Python) — `services/cache.py` owns all cache variables. Other modules use `cache.get_*()` / `cache.set_*()`. Never use `global` for caches outside cache.py.

## File Structure

> This section should be kept up-to-date when files are added, moved, or removed.

```
inspector/
├── app.py                          # Flask factory, startup, static/audio serving
├── config.py                       # ALL tuneable constants (paths, timeouts, thresholds, display)
├── constants.py                    # Domain constants (validation categories, muqattaat, qalqala, etc.)
├── requirements.txt
│
├── routes/                         # Flask Blueprints — thin request handlers
│   ├── __init__.py                 #   register_blueprints() helper
│   ├── timestamps.py               #   /api/ts/* — reciters, chapters, verses, data, random, validate
│   ├── segments_data.py            #   /api/seg/* — reciters, chapters, data, all, load
│   ├── segments_edit.py            #   /api/seg/* — save, undo-batch, undo-ops, resolve_ref
│   ├── segments_validation.py      #   /api/seg/* — validate, trigger-validation, stats, edit-history
│   ├── peaks.py                    #   /api/seg/peaks — waveform peak data
│   ├── audio_proxy.py              #   /api/seg/* — audio-proxy, cache-status, prepare, delete
│   └── audio_metadata.py           #   /api/audio/* — sources, surahs
│
├── services/                       # Business logic — no Flask imports, pure functions
│   ├── cache.py                    #   Centralized cache registry (getter/setter/invalidation for all caches)
│   ├── data_loader.py              #   Load timestamps, segments, audio URLs, surah info, QPC, DK
│   ├── validation.py               #   9-category validation engine, chapter validation counts
│   ├── save.py                     #   Save flow: atomic write, backup, edit history, rebuild segments.json
│   ├── undo.py                     #   Undo batch/ops: reversal, snapshot verification
│   ├── peaks.py                    #   Waveform peak computation via ffmpeg
│   ├── audio_proxy.py              #   Audio range decoding, downloading, local caching
│   ├── phonemizer_service.py       #   Phonemizer singleton, canonical phoneme building
│   ├── phoneme_matching.py         #   Phoneme tail matching, substitution pairs
│   └── stats.py                    #   Histogram, percentile, distribution computation
│
├── utils/                          # Pure utilities — no state, no side effects
│   ├── arabic_text.py              #   strip_quran_deco, last_arabic_letter
│   ├── references.py               #   chapter_from_ref, normalize_ref, seg_sort_key
│   ├── uuid7.py                    #   UUIDv7 generator (RFC 9562)
│   ├── io.py                       #   atomic_json_write, file_sha256, backup_file
│   └── formatting.py               #   format_ms, utc_now_iso, slug_to_name
│
└── frontend/                       # TS + Vite SPA (port 5173 dev; bundled to dist/ for Flask)
    ├── index.html                  # Vite entry — loads /src/main.ts
    ├── package.json                # deps: chart.js, chartjs-plugin-annotation, vite, typescript
    ├── tsconfig.json               # strict + noUncheckedIndexedAccess + allowJs:false
    ├── vite.config.ts              # root + proxy /api and /audio to Flask :5000
    ├── eslint.config.js
    ├── public/
    │   └── fonts/                  # DigitalKhatt Arabic font (served verbatim)
    ├── dist/                       # Build output (GITIGNORED — run `npm run build`)
    │
    └── src/
        ├── main.ts                 # Entry: mounts App.svelte, imports segments side-effect module + styles
        │
        ├── styles/                 # Styles split by domain (imported from main.ts)
        │   ├── base.css            #   Reset, body, :root vars, tabs, scrollbars
        │   ├── components.css      #   Buttons, info-bar, audio controls, searchable-select
        │   ├── timestamps.css      #   Waveform, phonemes, unified display, animation
        │   ├── segments.css        #   Segment rows, confidence colors, editing UI
        │   ├── validation.css      #   Accordions, error cards, action buttons
        │   ├── history.css         #   Edit history batches, diffs, arrows, save preview
        │   ├── stats.css           #   Chart wrappers, fullscreen overlay
        │   └── filters.css         #   Filter bar, back banner
        │
        ├── lib/                    # Shared cross-tab modules
        │   ├── api/
        │   │   └── index.ts        #   fetchJson / fetchJsonOrNull helpers (typed)
        │   ├── components/         # Reusable Svelte 4 primitives
        │   │   ├── AccordionPanel.svelte #  Shared <details> accordion wrapper
        │   │   ├── AudioElement.svelte   #  Thin <audio> wrapper (safePlay, events)
        │   │   ├── AudioPlayer.svelte    #  Full audio player UI (source + controls)
        │   │   ├── SearchableSelect.svelte # Dropdown with text search + grouped options
        │   │   ├── SpeedControl.svelte   #  Playback speed selector
        │   │   ├── ValidationBadge.svelte #  Color-coded count badge (default/warning/error)
        │   │   └── WaveformCanvas.svelte #  Canvas waveform renderer (sub-ranging support)
        │   ├── stores/
        │   │   ├── audio.ts        #   Audio tab state (reciter/surah/ayah selection)
        │   │   ├── timestamps/     #   Timestamps tab stores
        │   │   │   ├── verse.ts    #   reciters/chapters/verses selection + loadedVerse
        │   │   │   ├── display.ts  #   view mode, granularity, show-letters, show-phonemes, config
        │   │   │   └── playback.ts #   auto-mode, auto-advance guard, currentTime, tsAudioElement
        │   │   └── segments/       #   Segments tab stores
        │   │       ├── audio-cache.ts # by_surah cache download/delete UI state
        │   │       ├── chapter.ts  #   reciter/chapter selection + segAllData
        │   │       ├── config.ts   #   server-side seg config (loaded once)
        │   │       ├── dirty.ts    #   dirty chapter set + op log (unsaved mutations)
        │   │       ├── edit.ts     #   active edit mode, overlay state
        │   │       ├── filters.ts  #   filter bar predicates + derived filtered list
        │   │       ├── history.ts  #   edit history panel visibility, data, display items
        │   │       ├── navigation.ts # back-to-results banner state + savedFilterView
        │   │       ├── playback.ts #   audio playback state, continuous-play, tsAudioElement
        │   │       ├── save.ts     #   save preview visibility + data
        │   │       ├── stats.ts    #   stats panel open state + data
        │   │       └── validation.ts # validation panel open state + data
        │   ├── types/
        │   │   ├── api.ts          #   Response shapes for every /api/* endpoint
        │   │   ├── domain.ts       #   Segment, Ref, PhonemeInterval, SegmentPeaks, SurahInfo, ...
        │   │   ├── segments-waveform.ts #  SegCanvas extension types, highlight descriptors
        │   │   ├── segments.ts     #   SplitChain, HistorySnapshot, OpFlatItem and related types
        │   │   ├── stats.ts        #   ChartCfg, Distribution — shared stats chart types
        │   │   └── ui.ts           #   SelectOption, common UI types
        │   └── utils/
        │       ├── active-tab.ts   #   Active-tab state (getActiveTab/setActiveTab)
        │       ├── animation.ts    #   createAnimationLoop() — rAF loop with start/stop
        │       ├── arabic-text.ts  #   stripTashkeel, isCombiningMark, char matching
        │       ├── audio.ts        #   safePlay() — swallows AbortError on interrupted play()
        │       ├── chart.ts        #   Chart.js bootstrap (registers plugins, re-exports Chart)
        │       ├── constants.ts    #   localStorage keys (LS_KEYS), placeholder strings
        │       ├── keyboard-guard.ts # shouldHandleKey(e, tab) — shared keyboard guard helper
        │       ├── speed-control.ts  # Speed option list for SpeedControl.svelte
        │       ├── stats-chart-draw.ts # Chart.js histogram draw helpers (StatsChart)
        │       ├── surah-info.ts   #   surahInfo data + surahInfoReady promise + surahOptionText
        │       ├── svg-arrow-geometry.ts # computeArrowLayout() for history diff arrows
        │       ├── waveform-cache.ts # Normalized URL → peaks Map cache (non-reactive)
        │       ├── waveform-draw.ts  # Peak array → canvas draw (reused by all waveform contexts)
        │       ├── webaudio-peaks.ts # Client-side AudioContext + LRU cache + slice
        │       └── segments/       # Segments-tab utility modules (one concern per file)
        │           ├── audio-cache-ui.ts    # Cache download/delete API calls + store updates
        │           ├── chapter-actions.ts   # Chapter-level data load action
        │           ├── classify.ts          # Per-segment validation category classification
        │           ├── clear-per-reciter-state.ts # Reset validation/stats/history/save state on reciter change
        │           ├── conf-class.ts        # getConfClass() — CSS class from confidence score
        │           ├── constants.ts         # Label dicts, filter field IDs, op-type sets
        │           ├── edit-common.ts       # exitEditMode + _playRange passthrough
        │           ├── edit-delete.ts       # Delete segment operation
        │           ├── edit-enter.ts        # enterEditWithBuffer — entry point for trim/split
        │           ├── edit-merge.ts        # Merge adjacent segments operation
        │           ├── edit-reference.ts    # beginRefEdit / commitRefEdit
        │           ├── edit-split.ts        # Split mode: enter, drag, preview, confirm
        │           ├── edit-trim.ts         # Trim mode: enter, drag handles, preview, confirm
        │           ├── error-card-audio.ts  # Error card audio playback + animation
        │           ├── filter-fields.ts     # Filter field descriptors (label, type, ops)
        │           ├── filters-apply.ts     # Republish segment mutations to Svelte stores
        │           ├── history-actions.ts   # Edit history panel lifecycle (show/hide)
        │           ├── history-render.ts    # Push raw edit-history response to history store
        │           ├── missing-verse-context.ts # Find surrounding segments for a missing verse
        │           ├── navigation-actions.ts # jumpToSegment/Verse + filter view save/restore
        │           ├── peaks-cache.ts       # IntersectionObserver + peak fetching/indexing
        │           ├── play-range.ts        # _playRange — preview playback with animated playhead
        │           ├── playback.ts          # Audio playback, animation, highlight tracking
        │           ├── prefetch.ts          # Audio prefetch for the next displayed segment
        │           ├── reciter-actions.ts   # Reciter-level reload action
        │           ├── reciter.ts           # isBysurahReciter() helper
        │           ├── references.ts        # Ref parsing, formatting, verse markers
        │           ├── save-actions.ts      # Save flow: preview, confirm, execute
        │           ├── save-execute.ts      # POST save to server + dirty state cleanup
        │           ├── save-preview.ts      # Build save-preview data from dirty state + op log
        │           ├── split-draw.ts        # Canvas drawing for split mode
        │           ├── trim-draw.ts         # Canvas drawing for trim mode
        │           ├── undo.ts              # Batch/op/chain undo API calls + store updates
        │           ├── validation-fixups.ts # Index fixup helpers for validation results
        │           ├── validation-refresh.ts # Fetch validation + push to store
        │           ├── waveform-draw-seg.ts # Segments waveform drawing (peaks + overlays)
        │           └── waveform-utils.ts    # Peak fetch, adjacent segment lookup helpers
        │
        ├── tabs/audio/             # Audio tab — Svelte 4
        │   └── AudioTab.svelte     #   Category toggle, reciter/surah/ayah dropdowns, player, nav
        │
        ├── tabs/timestamps/        # Timestamps tab — Svelte 4 components
        │   ├── TimestampsTab.svelte #   Shell: dropdowns, audio, keyboard, CSS vars, view toggle
        │   ├── UnifiedDisplay.svelte #  Analysis view: mega-blocks + letters + phonemes + bridges
        │   ├── AnimationDisplay.svelte # Reveal-mode animation, char/word granularity
        │   ├── TimestampsWaveform.svelte # Waveform + overlays (wraps WaveformCanvas)
        │   └── TimestampsValidationPanel.svelte # 3-category accordion (uses AccordionPanel)
        │
        └── tabs/segments/          # Segments tab — Svelte 4 components
            ├── SegmentsTab.svelte  #   Tab shell + reciter/chapter selectors
            ├── ShortcutsGuide.svelte #  Keyboard shortcut reference overlay
            ├── list/               # Segment list rendering
            │   ├── SegmentsList.svelte        #  Virtualized segment list container
            │   ├── SegmentRow.svelte          #  Individual segment card (read + edit-mode props)
            │   ├── SegmentWaveformCanvas.svelte # Waveform canvas wrapper for segment rows
            │   └── Navigation.svelte          #  Back-to-results banner
            ├── filters/            # Filter bar
            │   ├── FiltersBar.svelte          #  Filter bar + active filter pills
            │   └── FilterCondition.svelte     #  Single filter condition input
            ├── stats/              # Statistics panel
            │   ├── StatsPanel.svelte          #  Statistics panel accordion shell
            │   ├── StatsChart.svelte          #  Chart.js histogram component
            │   └── ChartFullscreen.svelte     #  Fullscreen overlay for charts
            ├── audio/              # Audio controls
            │   ├── SegmentsAudioControls.svelte # Audio player + continuous-play controls
            │   └── AudioCacheBar.svelte       #  by_surah cache status + download/delete controls
            ├── edit/               # Editing mode overlays
            │   ├── EditOverlay.svelte #  Active edit mode container
            │   ├── TrimPanel.svelte   #  Trim handles + confirm
            │   ├── SplitPanel.svelte  #  Split handle + confirm + ref chaining
            │   ├── MergePanel.svelte  #  Merge confirmation
            │   ├── DeletePanel.svelte #  Delete confirmation
            │   └── ReferenceEditor.svelte # Inline ref edit + autocomplete
            ├── history/            # Edit history view
            │   ├── HistoryPanel.svelte #  Panel shell + summary stats
            │   ├── HistoryBatch.svelte #  Batch record (save event)
            │   ├── HistoryOp.svelte   #  Single op (trim/split/merge/delete/ref)
            │   ├── HistoryArrows.svelte # SVG arrows between before/after columns
            │   ├── HistoryFilters.svelte # Filter pills + sort
            │   └── SplitChainRow.svelte #  Split chain segment row in history diff
            ├── save/
            │   └── SavePreview.svelte # Save preview panel (confirm/cancel)
            └── validation/
                ├── ValidationPanel.svelte    # 11-category accordion panel
                ├── ErrorCard.svelte          # Single validation error card
                ├── GenericIssueCard.svelte   # Generic issue row (jump button + label)
                ├── MissingVersesCard.svelte  # Missing verse card with context segments
                └── MissingWordsCard.svelte   # Missing word card with context
```

## Architecture

### Backend Layers

```
routes/ (Flask Blueprints)  →  services/ (business logic)  →  utils/ (pure helpers)
         ↓                              ↓                          ↑
     flask.request               services/cache.py            constants.py
     flask.jsonify               (all cache state)            config.py
```

- **Routes** parse HTTP requests, call services, return `jsonify()`. No business logic.
- **Services** own the logic. No Flask imports. Accept parameters, return plain dicts.
- **Cache** (`services/cache.py`) is the single owner of all in-memory cache state. Getter/setter/invalidation API. Other modules never use `global` for caches.
- **Utils** are pure functions with no state and no side effects.

### Frontend Layers

```
src/main.ts (entry point, CSS imports)
  └── App.svelte  →  tabs/timestamps/TimestampsTab.svelte  →  lib/stores/timestamps/
                  →  tabs/segments/SegmentsTab.svelte      →  lib/stores/segments/
                  →  tabs/audio/AudioTab.svelte            →  lib/stores/audio.ts
```

Each tab's Svelte components import from `lib/stores/` (reactive state) and `lib/utils/segments/` (imperative actions). No cross-tab imports.

- **TypeScript + Vite** — bundled ES module output in `dist/`, one hashed JS + one hashed CSS file, sourcemaps on. Dev server at `:5173` with HMR; production served by Flask at `:5000` via `dist/` staticfiles (see `app.py`'s `FRONTEND_DIST` and `/` route).
- **Strict typing** — `strict`, `noUncheckedIndexedAccess`, `noImplicitAny`, `strictNullChecks`, `allowJs:false`. Zero `@ts-nocheck` pragmas remaining in `src/`.
- **Svelte 4 tabs** — all three tabs are pure Svelte 4: stores + `bind:this` for element refs. The Segments tab additionally calls action modules in `lib/utils/segments/` for operations (edit/save/undo/validation/navigation/playback) that need to reach outside the component tree.
- **Hybrid pattern** — `WaveformCanvas.svelte` exposes a `getCanvas()` escape hatch so imperative overlay code can draw directly onto the canvas element each animation frame, avoiding costly reactive re-renders at 60fps.
- **Animation loop** — `lib/utils/animation.ts::createAnimationLoop()` wraps raw `requestAnimationFrame` chains with clean start/stop lifecycle. Used by `lib/utils/segments/playback.ts` and `TimestampsTab.svelte`.
- **Chart.js** imported from npm (`chart.js` + `chartjs-plugin-annotation`), registered once in `lib/utils/chart.ts`. Consumers import `Chart` from there, never from a global.

### Caching Strategy

**Server (Python):**
- All caches in `services/cache.py` — accessed via getter/setter functions
- **Eager** (startup): timestamp reciters, full timestamp data (parallel ThreadPoolExecutor)
- **Lazy** (first access): QPC, DK, segments, audio URLs, word counts, peaks, phonemes
- **Invalidation**: `invalidate_seg_caches(reciter)` after save/undo — clears segment cache, meta, verses, reciters

**Client (JS):**
- Tab stores (`lib/stores/`) hold reactive state; non-reactive caches live in `lib/utils/waveform-cache.ts` and `lib/utils/segments/peaks-cache.ts`
- `IntersectionObserver` for lazy waveform drawing from pre-fetched peaks
- Audio buffers cached per URL/chapter with size limits

### Route Namespaces

| Prefix | Blueprint | Purpose |
|--------|-----------|---------|
| `/api/ts/*` | `timestamps.py` | Reciters, chapters, verses, data, random, validate |
| `/api/seg/*` | `segments_*.py`, `peaks.py`, `audio_proxy.py` | Segment data, editing, validation, stats, peaks, audio cache |
| `/api/audio/*` | `audio_metadata.py` | Source hierarchy, surah/ayah URL lookup |
| `/audio/<reciter>/<file>` | `app.py` | Local audio file serving |
| `/api/surah-info` | `app.py` | Cross-tab surah metadata |

## Conventions

- **Config is the single source of truth for tuneable values.** Never hardcode display settings, thresholds, padding values, or similar constants in JS or HTML. They belong in `config.py`, are served via `/api/ts/config` or `/api/seg/config`, and JS reads them on init.
- **Timestamps** stored as milliseconds in files, converted to seconds at I/O boundary for Web Audio API.
- **Confidence colors:** Green >= 80%, Yellow 60-79%, Red < 60%.
- **Cross-verse segments** use compound keys like `"37:151:3-37:152:2"`.
- **Dark theme colors:** Background `#1a1a2e`, panels `#16213e`, Arabic text gold `#f0a500`, phonemes blue `#4361ee`, letters teal `#2ec4b6`.
- **localStorage keys:** All prefixed `insp_*`, defined in `frontend/src/lib/utils/constants.ts` as `LS_KEYS`.
- **Segment UIDs:** UUIDv7 assigned on first server load, persisted in `detailed.json`. Split/merge create new UIDs client-side (`crypto.randomUUID()`).

## Segments Editing Operations

| Operation | Confidence After | Module |
|-----------|-----------------|--------|
| **Trim** | Unchanged | `lib/utils/segments/edit-trim.ts` |
| **Split** | Unchanged until ref edit → 1.0 | `lib/utils/segments/edit-split.ts` |
| **Merge** | 1.0 | `lib/utils/segments/edit-merge.ts` |
| **Edit Reference** | 1.0 | `lib/utils/segments/edit-reference.ts` |
| **Delete** | N/A | `lib/utils/segments/edit-delete.ts` |
| **Auto-fill** | 1.0 | `lib/utils/segments/edit-reference.ts` (via commitRefEdit) |
| **Ignore** | Unchanged | `lib/utils/segments/save-actions.ts` (adds to ignored_categories) |

## Segments Validation Categories

Accordions appear in this order (empty categories hidden):

| Category | Detection | Key module |
|----------|-----------|------------|
| Failed Alignments | Empty `matched_ref` | `lib/utils/segments/validation-fixups.ts` |
| Missing Verses | Verse has zero coverage | `services/validation.py` (server) |
| Missing Words | Gap in word indices | `services/validation.py` (server) |
| Structural Errors | Time/word ordering issues | `services/validation.py` (server) |
| Low Confidence | `confidence < 0.80` | `lib/utils/segments/classify.ts` |
| Detected Repetitions | `wrap_word_ranges` set | `lib/utils/segments/classify.ts` |
| May Require Boundary Adj | 1-word segment (filtered) | `lib/utils/segments/classify.ts` |
| Cross-verse | Start ayah != end ayah | `lib/utils/segments/classify.ts` |
| Audio Bleeding | by_ayah: verse mismatch | `lib/utils/segments/classify.ts` |
| Muqatta'at | Huruf muqatta'at verse | `lib/utils/segments/classify.ts` |
| Qalqala | Last letter is qalqala | `lib/utils/segments/classify.ts` |

## Save Flow

1. Client: `lib/utils/segments/save-execute.ts` → `POST /api/seg/save/<reciter>/<chapter>`
2. Server: `services/save.py` → validation_before snapshot → mutate segments → atomic write `detailed.json` → file hash → rebuild `segments.json` → validation_after snapshot → append `edit_history.jsonl` → invalidate caches
3. Client: refresh UI, trigger validation log

## Edit History

Append-only JSONL at `data/recitation_segments/<reciter>/edit_history.jsonl`. Batch records (save) and revert records (undo). Server filters out undone batches. Client renders via `lib/utils/segments/history-render.ts` + `history-actions.ts` into the `lib/stores/segments/history.ts` store, displayed by `tabs/segments/history/` components (HistoryPanel, HistoryBatch, HistoryOp, HistoryArrows, HistoryFilters, SplitChainRow). Canonical `SplitChain` + `OpFlatItem` + `HistorySnapshot` types live in `lib/types/segments.ts`.

## Dependencies

- **Python:** Flask (see `requirements.txt`)
- ffmpeg
- **Client (npm):** `chart.js`, `chartjs-plugin-annotation`; devDeps: `typescript`, `vite`, `@types/*`, `eslint` + `@typescript-eslint/*`. See `inspector/frontend/package.json`.
- **Client (platform):** Web Audio API, Fetch, IntersectionObserver
- **Optional:** `quranic_phonemizer` (for reference text resolution)
