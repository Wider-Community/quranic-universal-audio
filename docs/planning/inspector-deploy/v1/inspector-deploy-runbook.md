# Inspector Deploy Runbook

Operational companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md) and [`inspector-data-storage.md`](inspector-data-storage.md). Those are decision docs; this is the action doc — what to actually do, in order, when standing up the deployed Inspector.

Audience: anyone executing a deploy phase or maintaining the live Spaces. Does not duplicate architectural rationale — for "why this design" go to the parent docs; this doc owns "how to operate it."

## 1. Hosting target — HF Spaces, free tier

The Inspector deploys as a Hugging Face Space using the Docker SDK on free **CPU-basic** tier (2 vCPU shared, 16 GB RAM, ephemeral disk, 48-hour idle sleep). Same operational pattern as the existing project Spaces (`Quran-reciter-requests`, `Quran-phoneme-mfa`, `quranic-universal-aligner`). Zero new ops surface.

Two Spaces:

| Purpose | Slug | URL | Tracks |
|---|---|---|---|
| Production | `hetchyy/quranic-inspector` | `https://hetchyy-quranic-inspector.hf.space` | `main` branch |
| Development | `hetchyy/quranic-inspector-dev` | `https://hetchyy-quranic-inspector-dev.hf.space` | `dev` branch |

URLs are stable across rebuilds, sleep/wake, restarts, and config changes. They only change if the Space is renamed or moved between owners. Custom domain (`inspector.your-domain.com` via CNAME → `hf.space`) is supported and free if you ever want it.

**Sleep behaviour on free tier:**
- 48-hour idle timeout, not configurable.
- Wake-up on first request: 30–60 s for sleep state, up to ~2 min for paused state.
- For an active project, sleep is effectively never reached — any anonymous viewer or reviewer keeps it warm.

**Rebuild behaviour:**
- Push to the Space repo → HF queues build → ~1–5 min build time → swap to new container.
- **No zero-downtime swap on free tier.** Active users get 503s during the build window.
- Active reviewer mid-edit: their next save POST returns 503 until rebuild completes; scratch dir is on the old container's `/tmp` and gone. Up to one debounce window (≤5 min) of unflushed edits lost. Anything debounce-flushed is on the PR branch and survives.
- Mitigation: don't deploy during peak review hours; frontend shows "deploy in progress, your edits will replay from PR branch on reload" banner on 503.

**When to leave free tier:** see [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers (p95 > 1.5 s sustained, memory > 800 MB, GitHub rate consumption > 50%/h, or > 50 concurrent active reviewers). Migration target is Fly.io shared-cpu-2x@2GB ($5/mo always-on); same image, `fly launch --image registry/...`.

## 2. HF Space setup

### Per Space (do twice — dev first, then prod)

1. Create the Space at `https://huggingface.co/new-space`:
   - Name: `quranic-inspector-dev` or `quranic-inspector`
   - License: same as the main project
   - SDK: **Docker**
   - Hardware: CPU basic (free)
   - Visibility: Public

2. Configure the Space's `README.md` frontmatter (this lives in the **Space repo**, not the main monorepo):

   ```yaml
   ---
   title: Quran Inspector
   emoji: 📖
   colorFrom: green
   colorTo: blue
   sdk: docker
   app_port: 5000
   pinned: false
   short_description: Inspect & edit Quran recitation alignment results
   ---
   ```

3. Add Space secrets via Settings → Variables and secrets:

   | Secret | Source | Notes |
   |---|---|---|
   | `INSPECTOR_GITHUB_APP_ID` | GitHub App registration (§3) | Same App for dev + prod |
   | `INSPECTOR_GITHUB_APP_PRIVATE_KEY` | App's downloaded `.pem`, full PEM contents | Different installation per Space if isolating writes |
   | `INSPECTOR_INTERNAL_SECRET` | Random 32-byte hex | Cache-invalidate webhook auth, separate per Space |
   | `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` | GitHub App user-to-server credentials | If using user OAuth flow |
   | `INSPECTOR_HF_TOKEN` | HF access token (read-only) | Only if accessing private dataset paths; not needed for public dataset |
   | `INSPECTOR_ALLOWED_SLUGS_REGEX` | `^_test_` for dev, **unset for prod** | Gates write endpoints to test reciters in dev |

   Env vars (non-secret) are also set in the same panel — see [`inspector-data-storage.md`](inspector-data-storage.md) §6 for the full list. Most have sensible deployed defaults from the Dockerfile and don't need to be set in Space settings.

### Verifying the Space is live

After first push (§4):

```bash
curl -fsS https://hetchyy-quranic-inspector-dev.hf.space/healthz
# expect: 200 with JSON like {"status":"ok","commit":"<sha>","mode":"deployed"}
```

If 503, watch the Space's build log via the web UI Settings → Logs. Common causes: Dockerfile syntax error, missing static file in COPY list, gunicorn binding to wrong port (must be 5000 to match `app_port`).

## 3. GitHub App setup

One App registered against the repo, two installations (one for dev workflows, one for prod) so write authorization is independently revocable.

1. **Register the App** at `https://github.com/settings/apps/new` (or org-level if the repo is in an org):
   - Name: `Quranic Inspector` (or similar; this name appears on commits as the committer)
   - Homepage URL: the prod Space URL
   - Webhook: disabled (Inspector polls; no webhook needed for app-level events)
   - **Permissions:**
     - Repository: Contents (Read & Write), Pull requests (Read & Write), Metadata (Read), Issues (Read & Write — for `repository_dispatch` and label mirroring), Members (Read — for collaborator-status check during claim flow)
     - Account: Email addresses (Read), Profile (Read) — for OAuth user-to-server identification
   - **Subscribe to events:** none (we don't use webhook events)
   - User authorization callback URL: `https://hetchyy-quranic-inspector{,-dev}.hf.space/auth/callback` (one entry per Space; GitHub Apps allow multiple callback URLs)
   - Where can this App be installed: Only on this account
   - Generate and download the private key (`.pem`) — store it in a password manager; you'll paste it as `INSPECTOR_GITHUB_APP_PRIVATE_KEY` in Space secrets.

2. **Install the App** on the repo. Each install gets an `installation_id`; record both (one for dev, one for prod) — they go in the corresponding Space's secrets if you ever need to scope by installation.

3. **Test the App's auth path** locally before deploying:
   ```bash
   python scripts/test_github_app_auth.py --app-id $APP_ID --private-key-path ./inspector-app.pem
   # Should print a fresh installation token + a successful GET against the repo
   ```

4. **Rate-limit budget:** the App gets 5,000 req/h authenticated. Anonymous viewers don't burn this budget for completed reciters (HF CDN direct); only under-review reads + write commits do. Realistic peak: ~3,000 req/h with 10 concurrent users browsing under-review reciters.

## 4. Upload pipeline

The Space repos receive a **selective subset** of the main monorepo, not the whole tree. One image, two profiles — same Dockerfile works for local Docker (data bind-mounted at `/data`) and the deployed Space (data baked into `/app/data` and fetched on demand for everything else). See [`inspector-data-storage.md`](inspector-data-storage.md) §7.

### What gets pushed

```
hetchyy/quranic-inspector/                   # Space repo root = Docker build context
├── README.md                                # Space frontmatter (§2 step 2)
├── Dockerfile                               # the inspector/Dockerfile, copied to root
├── .dockerignore                            # IMPORTANT: at Space repo root (build context root)
├── inspector/                               # backend + frontend dist
│   ├── app.py
│   ├── config.py constants.py
│   ├── adapters/  domain/  routes/  services/  utils/
│   └── frontend/dist/                       # PRE-BUILT — built at upload time, src/ excluded
├── validators/                              # imported by inspector via sys.path
├── scripts/
│   ├── __init__.py
│   └── lib/                                 # shared lib (segments_shards, timestamps_shards, reciter_task...)
└── data/                                    # static reference only (~89 MB)
    ├── surah_info.json
    ├── qpc_hafs.json
    ├── digital_khatt_v2_script.json
    ├── phoneme_sub_costs.json
    ├── reciters_index.json
    ├── riwayat.json
    ├── sources.json
    ├── styles.json
    ├── .audio_meta.json
    ├── .audio_durations.json
    └── audio_catalog.json.gz                # consolidated 391 manifests, compact + gzipped (~6 MB)
```

### What does NOT get pushed

- `inspector/frontend/src/`, `node_modules/`, `tests/`, vite config — frontend is built once during upload, only `dist/` ships
- `data/audio/` raw 67 MB of per-source manifests — replaced by `audio_catalog.json.gz`
- `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/` — fetched at runtime
- `.github/`, `.local/`, `docs/`, `reciter_requests/`, validator test trees — irrelevant to runtime

### Upload alias scripts (gitignored from main repo)

Mirrors the existing `upload-mfa-dev` / `upload-mfa` pattern. Each alias does:

```bash
# upload-inspector-dev: push current dev branch contents to the dev Space repo
set -euo pipefail

# 1. Build the frontend
(cd inspector/frontend && npm install && npm run build)

# 2. Build the consolidated audio catalog
python scripts/build_audio_catalog.py --output data/audio_catalog.json.gz

# 3. rsync the selective tree into a local clone of the Space repo
SPACE_REPO=~/.local/spaces/inspector-dev
git -C "$SPACE_REPO" reset --hard origin/main
rsync -av --delete \
  --include='inspector/***' \
  --exclude='inspector/frontend/src/' \
  --exclude='inspector/frontend/node_modules/' \
  --exclude='inspector/tests/' \
  --include='validators/***' \
  --include='scripts/__init__.py' \
  --include='scripts/lib/***' \
  --include='data/surah_info.json' \
  --include='data/qpc_hafs.json' \
  --include='data/digital_khatt_v2_script.json' \
  --include='data/phoneme_sub_costs.json' \
  --include='data/reciters_index.json' \
  --include='data/riwayat.json' \
  --include='data/sources.json' \
  --include='data/styles.json' \
  --include='data/.audio_meta.json' \
  --include='data/.audio_durations.json' \
  --include='data/audio_catalog.json.gz' \
  --include='inspector/Dockerfile' \
  --include='.dockerignore' \
  --include='README.md' \
  --exclude='*' \
  ./ "$SPACE_REPO/"

# 4. Move the Dockerfile to the Space repo root so it's the build context root
mv "$SPACE_REPO/inspector/Dockerfile" "$SPACE_REPO/Dockerfile"

# 5. Commit + push
cd "$SPACE_REPO"
git add -A
git commit -m "deploy from $(git -C - rev-parse HEAD 2>/dev/null || echo unknown)"
git push hf-space main
```

`upload-inspector` is identical except it points at the prod Space and pushes from `main` instead of `dev`.

The aliases live in your shell config or `.local/scripts/`, gitignored from the main repo (same pattern as `upload-mfa*`).

### `.dockerignore` placement

`docker build` uses the `.dockerignore` at the **build context root**. With the upload pipeline above, the Space repo root is the build context, so `.dockerignore` lives at the Space repo root. The repo's `inspector/.dockerignore` is dead weight in deploy mode; if the local `docker-compose.yml` builds with `-f inspector/Dockerfile .` (context = main repo root), then the **main repo root** also needs a `.dockerignore` for local-build hygiene. Both `.dockerignore` files contain the same rules — keep them in sync, or symlink in the upload pipeline.

## 5. Test environment conventions

Dev Space writes to the **same monorepo as prod** — no fork. Discipline-based isolation:

| Convention | Enforcement |
|---|---|
| Test reciter slugs prefixed `_test_` | `INSPECTOR_ALLOWED_SLUGS_REGEX=^_test_` in dev Space settings rejects writes to non-test slugs |
| Test contributor accounts | Invited as repo collaborators only during dev cycles; remove after |
| Test PR branches `reciter/_test_*` | `pr-uniqueness.yml` blocks merge of `_test_*` reciters into `main` |
| Test reciters never appear in `data/reciters_index.json` for prod | `list_reciters.py` filters by slug regex; `RECITERS.md` excludes them |

To create a test reciter:
1. Add `_test_<purpose>` to `data/reciter_catalog.json` (catalog file, not state file).
2. Run `process_requests.py` to generate the alignment job (or manually scaffold a minimal `data/recitation_segments/_test_<purpose>/` tree).
3. Open a PR onto branch `reciter/_test_<purpose>` and verify the dev Space picks it up via github-fetch.
4. Test the claim → edit → release flow against the dev Space, signed in as a test contributor account.
5. **Do NOT merge** test PRs into `main`. Close them when done.

## 6. Smoke tests per phase

Run after every phase deploy to dev Space, then prod Space.

### Phase 1 — Read-only deploy

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Health
curl -fsS $SPACE/healthz | jq

# Anonymous reciter list
curl -fsS $SPACE/api/reciter-task/saad_al_ghamdi | jq '.state'  # expect "completed" or similar

# HF CDN read path (browser-direct, but verify the URL the frontend would generate)
HF_URL=https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs/resolve/main/inspector/segments/saad_al_ghamdi/segments.json.gz
curl -fsSI $HF_URL | head -5

# Image discipline check
docker run --rm hetchyy/quranic-inspector:latest sh -c '
  find /app/data \( -path "*/recitation_segments/*" -o -path "*/timestamps/*" \) -print | head -1
' | grep -q . && echo "FAIL: image bloat" || echo "OK: image clean"
```

**Acceptance:**
- p99 cold-page-load for completed reciter ≤ 800 ms
- Image size ≤ 400 MB
- `data/recitation_segments/` empty in running container
- gunicorn process visible in container, not werkzeug

### Phase 2 — PR-branch reads

```bash
# Pick an under-review reciter (one with an open PR)
SLUG=$(gh pr list --state open --json headRefName -q '.[0].headRefName' | sed 's|reciter/||')

# Backend serves under-review data
curl -fsS $SPACE/api/seg/data/$SLUG/1 | jq '.segments | length'

# Single-flight: hit it 10× concurrently, expect 1 GitHub fetch in logs
for i in {1..10}; do curl -fsS "$SPACE/api/seg/data/$SLUG/1" >/dev/null & done; wait
# Inspect Space logs: grep "github_fetch upstream" → expect 1 line, not 10
```

**Acceptance:**
- Under-review p99 ≤ 1.5 s cold, ≤ 50 ms warm
- 10 concurrent requests → 1 GitHub fetch (single-flight working)
- PR branch push → website reflects within 30 s

### Phase 3 — Auth + claim flow

```bash
# Sign in via the website with a test contributor account
# Click Claim on an _test_* available reciter
# Verify:
#   - GitHub OAuth screen appears
#   - After authorize, page returns to dev Space with claim active
#   - data/reciter_state.json on the dev branch has been updated by the workflow
#   - Lock banner appears for other anonymous tabs
```

**Acceptance:**
- Claim flow completes in ≤ 3 clicks (Claim → Authorize → done)
- Returning user with active session: 1 click
- State file updated within 10 s of claim
- Concurrent claim attempts: only first succeeds, others get 409

### Phase 5a — Writes

```bash
# Logged in as the assigned reviewer for an _test_* reciter
# Make a small edit (trim a segment), verify:
#   - Save POST returns 200
#   - Within 30 s of pause, a commit appears on reciter/_test_*
#   - Commit author = reviewer's GH login (per email convention)
#   - Commit committer = the App
#   - All 4-5 files updated atomically
```

**Acceptance:**
- Edit → PR-branch commit ≤ 30 s after pause
- Author attribution correct
- Backend restart mid-session: re-fetch from PR branch on next save, no corruption
- Save during `ready_for_merge`: 410 with clear message

## 7. Rollback procedure

### Quick rollback (revert to a prior Space build)

```bash
# In the Space repo (NOT main monorepo)
cd ~/.local/spaces/inspector-prod
git log --oneline | head -5  # find the SHA to roll back to
git reset --hard <prior-sha>
git push --force hf-space main  # this triggers a new build with the old contents
```

Rebuild takes ~1–5 min; users see 503 during. Active reviewers' unflushed scratch is lost — same as any rebuild.

### Kill switch (disable writes immediately)

```bash
# In the Space settings, set INSPECTOR_ALLOWED_SLUGS_REGEX=^$  (matches nothing)
# Restart Space (Settings → Restart)
# All write endpoints now 403; reads continue.
```

Faster than a rollback, narrower in effect. Use when the bug is in the write path specifically.

### Full disable (take Inspector offline)

```bash
# Settings → Pause Space
# Site returns 503 to everyone.
```

Use when the bug is severe and needs investigation before letting traffic in. Don't forget to unpause when fixed — and pre-warn users via Discord/issue if the outage will be long.

### GitHub App nuclear option

If the App is compromised or misbehaving, **disable the installation** in the repo's Settings → Integrations → installed GitHub Apps → quranic-inspector → Configure → Suspend or Uninstall. Inspector backend then can't read or write GitHub at all; all routes that touch github-fetch return 503 cleanly. HF static reads keep working.

## 8. Concrete file structures

Three structures the team needs to keep in sync. Architectural docs reference these by cross-link.

### HF dataset structure (`hetchyy/quranic-universal-ayahs`)

Existing additions in **bold**:

```
hetchyy/quranic-universal-ayahs/
├── manifest.json.gz                          # existing — extend with inspector_shard_hashes per reciter
├── data/...                                  # existing — per-verse audio + word timestamps
├── timestamps/<slug>/<chapter>.json.gz       # existing — TS chapter shards (browser→HF)
├── segments/<slug>/<chapter>.json.gz         # existing — slim shards for Aligner preload
├── _resources/
│   ├── qpc_hafs.json.gz                      # existing — also baked into Inspector image
│   ├── digital_khatt_v2_script.json.gz       # existing — also baked into Inspector image
│   └── DigitalKhattV2.otf                    # existing — also baked into Inspector image
└── inspector/                                # NEW namespace — Inspector full-fidelity reads
    └── segments/<slug>/
        ├── segments.json.gz                  # full file, per-reciter (not chapter-sharded)
        ├── detailed.json.gz                  # full schema, ~1 MB gz from 5 MB raw
        ├── edit_history.jsonl.gz             # per-reciter, ~1-2 MB gz from 8 MB raw
        ├── edit_history_peaks.jsonl.gz       # per-reciter, ~300 KB gz
        └── low_confidence_v2.json.gz         # tiny
```

**Storage budget:** ~300 completed reciters × ~3-5 MB gz/reciter ≈ **1-2 GB** added to the existing dataset.

**Build target:** `build_reciter.py --build-inspector-segments <slug>` — gzip + upload + hash-diff against `manifest.reciters.<slug>._build.inspector_shard_hashes`. Mirrors the `--build-timestamps` and `--build-segments` patterns.

**Workflow trigger:** extend `sync-dataset.yml` per-slug step + the existing weekly full sweep. Fires on `segments-pr-merged.yml` (single-slug refresh after merge).

### HF Space repo structure (`hetchyy/quranic-inspector{,-dev}`)

What lands in each Space repo via the upload pipeline (§4):

```
hetchyy/quranic-inspector/
├── README.md                          # Space frontmatter (sdk: docker, app_port: 5000)
├── Dockerfile                         # repo's inspector/Dockerfile, copied to root
├── .dockerignore                      # at Space repo root = build context root
├── inspector/                         # backend code
│   ├── app.py  config.py  constants.py
│   ├── adapters/  domain/  routes/  services/  utils/
│   └── frontend/dist/                 # PRE-BUILT, src/ never pushed
├── validators/
├── scripts/
│   ├── __init__.py
│   └── lib/
└── data/                              # static reference only (~89 MB)
    ├── surah_info.json  qpc_hafs.json  digital_khatt_v2_script.json
    ├── phoneme_sub_costs.json  reciters_index.json
    ├── riwayat.json  sources.json  styles.json
    ├── .audio_meta.json  .audio_durations.json
    └── audio_catalog.json.gz          # consolidated 391 manifests, ~6 MB
```

Secrets live in HF Space settings, **not** in the pushed tree. See §2 secrets table.

### `/tmp` on the running container

Ephemeral filesystem, lost on rebuild/restart. All paths configurable via env vars in [`inspector-data-storage.md`](inspector-data-storage.md) §6.

```
/tmp/
├── inspector-scratch/                 # per-active-reviewer working dir (INSPECTOR_SCRATCH_DIR)
│   └── <slug>/                        # one subtree per reciter currently being edited
│       └── data/recitation_segments/<slug>/
│           ├── segments.json
│           ├── detailed.json
│           ├── edit_history.jsonl
│           ├── edit_history_peaks.jsonl
│           └── low_confidence_v2.json
│
├── inspector-cache/                   # peak/canonical-phoneme cache (INSPECTOR_CACHE_DIR)
│   └── <slug>/
│       ├── peaks/                     # disk-backed peaks cache for warm-rescue across requests
│       └── canonical_phonemes.json    # was .pkl in local mode; JSON in deployed
│
└── inspector-sessions/                # only if using filesystem-backed Flask sessions
                                       # (cookie-signed sessions don't need this)
```

**Lifecycle per directory:**

| Path | Created | Cleared |
|---|---|---|
| `inspector-scratch/<slug>/` | Reviewer's first save on a claimed reciter — github-fetch materialises 5 files | (a) reviewer releases claim → flush + rmtree, (b) periodic GC every ~5 min drops slugs whose `state.reciters[slug].assignee` no longer matches an active session, (c) container restart |
| `inspector-cache/<slug>/peaks/` | First peaks compute for that segment | TTL eviction in-process; container restart wipes |
| `inspector-cache/<slug>/canonical_phonemes.json` | First validator run that needs phonemes | Same as peaks |
| `inspector-sessions/` (if used) | OAuth login | Server-side session expiry, container restart |

**Disk pressure check:**
- Scratch: 9–19 MB × ≤10 concurrent reviewers ≈ 200 MB worst case
- Peaks cache: ~200 KB per region × hundreds per active reciter ≈ 50–100 MB
- Phonemes JSON: <1 MB per reciter × N cached
- **Total tmp footprint: <500 MB realistic, <1 GB worst case** — comfortable on HF CPU-basic.

## 9. Maintenance procedures

### Bumping the GitHub App's private key

1. Generate a new key in the App's settings.
2. Update `INSPECTOR_GITHUB_APP_PRIVATE_KEY` in dev Space settings first; restart dev Space; verify auth still works via `/healthz` and a test claim.
3. Update prod Space; restart; verify.
4. Revoke the old key in the App's settings.

Do not rotate dev and prod simultaneously — keep one as a known-good reference during the swap.

### Forcing a Space rebuild

```bash
# Push an empty commit to the Space repo
cd ~/.local/spaces/inspector-prod
git commit --allow-empty -m "force rebuild"
git push hf-space main
```

Or via the HF UI: Settings → Factory rebuild (clears any HF-side build cache too).

### Cache-invalidate a single slug

```bash
curl -fsS -X POST \
  -H "X-Internal-Secret: $INSPECTOR_INTERNAL_SECRET" \
  "https://hetchyy-quranic-inspector.hf.space/api/internal/cache-invalidate?slug=<slug>"
```

Drops both raw LRU and parsed-cache entries for that slug. Useful when an external CLI push to a PR branch doesn't trigger an automatic invalidation.

### Cache-invalidate everything

```bash
curl -fsS -X POST \
  -H "X-Internal-Secret: $INSPECTOR_INTERNAL_SECRET" \
  "https://hetchyy-quranic-inspector.hf.space/api/internal/cache-invalidate-all"
```

Use rarely. Forces all subsequent requests to refetch.

### Diagnosing slow requests

1. Space → Logs panel — search for slow request log lines (gunicorn logs request durations by default).
2. Most likely culprits in order: (a) ffmpeg fork on cold peaks, (b) cold validator run, (c) cold `detailed.json` fetch + parse, (d) GitHub rate-limit throttle.
3. Verify cache health: `curl /api/internal/cache-stats` (admin endpoint, gated by `INSPECTOR_INTERNAL_SECRET`) returns hit/miss ratios per layer.

## 10. Phase-by-phase checklist

Reference for "what should be true after Phase N before moving to Phase N+1." Acceptance criteria details are in [`inspector-data-storage.md`](inspector-data-storage.md) §9 and the [parent plan](inspector-deployment-plan.md) §10.

- [ ] **Phase 0** — slug-first identity convention adopted; `data/reciter_catalog.json` + `data/reciter_state.json` exist; `update-reciter-state.yml` workflow is sole writer.
- [ ] **Phase 1** — dev Space deployed, anonymous-load smoke test passes, gunicorn-gthread running, `audio_catalog.json.gz` baked in, HF dataset has `inspector/segments/<slug>/...` for currently-eligible reciters.
- [ ] **Phase 2** — under-review reciter renders via github-fetch, single-flight verified, edit affordances hidden globally.
- [ ] **Phase 3** — claim flow ≤ 3 clicks for new contributors, ≤ 1 for returning, state file updated within 10 s, lock works.
- [ ] **Phase 5a** — one volunteer round-trips an edit on a `_test_*` reciter, commit attribution correct, restart-mid-session is harmless.
- [ ] **Phase 5b** — new commits land without `file_hash_after`; CI passes; `.bak` files do not appear in PR branches.
- [ ] **Phase 6** — `pr-uniqueness.yml`, `inspector-deploy.yml`, cache-invalidate webhook all live; `find_segments_pr.py` deleted; contributor docs point at the website.
