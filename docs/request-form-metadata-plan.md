# Add reciter metadata to request form and update automation pipeline

## Context
Audio manifests now have complete metadata (name_en, name_ar, riwayah, style, country) across all 310 files. The request form should expose this metadata so users can verify/correct it. Notion and GitHub issue formats need matching updates.

## Files to modify
- `reciter_requests/app.py` — form UI, submission, GitHub/Notion creation
- `scripts/request_helpers.py` — Notion field extraction, GitHub fallback parsing
- `scripts/process_requests.py` — triage logic, state storage

## Changes

### 1. `reciter_requests/app.py` — Form metadata fields

**Add constants:**
- `STYLES` list + `STYLE_DISPLAY` mapping (murattal, mujawwad, muallim, children_repeat, taraweeh)
- `COUNTRIES` — full ISO 3166-1 country list (no external library needed, hardcode ~249 country names as a sorted list with "unknown" as the first/default option)
- `RIWAYAH_SLUG_TO_NAME` / `RIWAYAH_NAME_TO_SLUG` mappings built from existing `RIWAYAT` list + `riwayat.json` slugs

**Add `fetch_reciter_meta(slug, source_path)`:**
- Fetch manifest from GitHub via existing `_gh_get` (contents API)
- Parse `_meta` → return {riwayah, style, country}
- Cache with existing `_get_cached`/`_set_cached` infra, key `f"meta:{slug}"`
- For large by_ayah manifests, use raw endpoint and parse only the `_meta` portion

**Add `on_reciter_selected(reciter_value)` callback:**
- Parse reciter JSON from dropdown value
- Call `fetch_reciter_meta()`
- Convert riwayah slug → display name
- Return `gr.update()` for riwayah_dd, style_dd, country_dd

**Add UI widgets** (after riwayah dropdown):
- `gr.Markdown` note: "Metadata fields are auto-loaded from the reciter's manifest. Only modify if you are certain the current value is incorrect."
- `style_dd` — Dropdown, choices from STYLE_DISPLAY, default "Murattal", info: "Only change if certain"
- `country_dd` — Dropdown, choices from COUNTRIES (full ISO list), default "unknown", info: "Optional. Only change if confident"
- Update `riwayah_dd` info text: "Loaded from manifest. Only change if verified by listening."

**Wire callback:**
- `reciter_dd.change(fn=on_reciter_selected, inputs=[reciter_dd], outputs=[riwayah_dd, style_dd, country_dd])`

**Update submission:**
- `handle_submit` + `submit_request` gain `style`, `country` params
- GitHub issue body: add `**Style:** {style}` and `**Country:** {country}` after Riwayah line
- Notion page: add `Style` and `Country` rich_text properties
- Update `submit_btn.click` inputs list
- Update `/api/request` endpoint params

### 2. `scripts/request_helpers.py` — Extract new fields

**`notion_query_pending()`:**
- Add `"style": _notion_rich_text(props.get("Style", {}))`
- Add `"country": _notion_rich_text(props.get("Country", {}))`

### 3. `scripts/process_requests.py` — Pipeline triage updates

**Keep non-Hafs rejection** (still reject non-Hafs requests).

**Add `_load_manifest_meta(slug, source)` helper:**
- Read local manifest from `data/audio/{source}/{slug}.json`
- Return `_meta` dict or empty dict on failure

**Add metadata change flagging in triage:**
- Compare user-submitted style/riwayah/country against manifest values
- Add `metadata_flags` list to triage result with discrepancies
- Flags are informational (don't block acceptance) but appear prominently in triage output
- Riwayah change = most significant flag ("RIWAYAH CHANGE — verify by listening")

**Update `_fallback_pending_from_github()`:**
- Add regex extraction for `**Style:**` and `**Country:**` from issue body

**Store in triage state:**
- Add style, country, manifest_style, manifest_riwayah, manifest_country to state entries

### 4. Notion database — DONE
- **Style** (rich text) and **Country** (rich text) properties added via Notion MCP tool
- Existing pages unaffected (properties will be empty for old requests)

### 5. Additional automation improvements
- Future: pipeline `prepare-pr` can update manifest `_meta.country` if user provided non-"unknown" value where manifest had "unknown"
- Future: if style/riwayah changed and operator confirmed during triage, update manifest in PR

## Verification
1. Local test: `python3 reciter_requests/app.py` — verify form loads, reciter selection auto-fills metadata
2. Submit test request — verify GitHub issue has Style/Country fields
3. Verify Notion page created with Style/Country
4. Run `python3 scripts/process_requests.py triage` — verify metadata flags appear when values differ from manifest
