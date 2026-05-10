# Inspector Deploy Runbook (v2)

Operational companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). Those are decision docs; this is the action doc — what to actually do, in order, when standing up the deployed Inspector.

Audience: anyone executing a deploy phase or maintaining the live Spaces. Does not duplicate architectural rationale.

## 1. Hosting target — HF Spaces, free tier, with HF Bucket mount

The Inspector deploys as a Hugging Face Space using the Docker SDK on free **CPU-basic** tier (2 vCPU shared, 16 GB RAM, ephemeral disk). Each Space has one **HF Storage Bucket** mounted as a read-write volume — that's the working store for in-flight reciter data, the state file, and the audit log.

Two Spaces, two buckets:

| Purpose | Space | Bucket | URL |
|---|---|---|---|
| Production | `hetchyy/quranic-inspector` | `hetchyy/quranic-inspector-wip` | `https://hetchyy-quranic-inspector.hf.space` |
| Development | `hetchyy/quranic-inspector-dev` | `hetchyy/quranic-inspector-wip-dev` | `https://hetchyy-quranic-inspector-dev.hf.space` |

URLs are stable across rebuilds, sleep/wake, restarts, and config changes. They only change if the Space is renamed or moved between owners.

**Sleep behaviour on free tier:** 48-hour idle timeout, not configurable. Wake-up: 30–60 s for sleep state. For an active project, sleep is effectively never reached.

**Rebuild behaviour:** push to the Space repo → HF queues build → ~1–5 min build time → swap to new container. **No zero-downtime swap on free tier.** Active users get 503s during the build window. Active reviewer mid-edit: their next save POST returns 503 until rebuild completes; bucket persists across rebuilds (that's the whole point), so re-fetching the page after rebuild picks up where they left off.

**When to leave free tier:** see [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers. Migration target: HF CPU-upgrade ($0.03/h) or Fly.io shared-cpu-2x@2GB.

## 2. HF Space + Bucket setup

### Per environment (do twice — dev first, then prod)

#### Step 1: Create the Bucket

```bash
hf buckets create hetchyy/quranic-inspector-wip-dev   # public is fine; dev
hf buckets create hetchyy/quranic-inspector-wip       # public; prod
```

Or via the Hub UI: `https://huggingface.co/new-bucket`.

**Public** is acceptable — the bucket holds in-flight reciter data, which is intentionally publicly viewable per the parent doc's "anonymous viewing of in-review data" default. Switch to private if you want maintainer-only viewing of in-flight work.

#### Step 2: Pre-seed the Bucket with state file

One-shot script that walks current GitHub state and writes initial bucket entries:

```bash
HF_TOKEN=<your-token> python scripts/migrate_state_to_bucket.py \
  --bucket hetchyy/quranic-inspector-wip-dev \
  --owners-snapshot data/inspector_owners.json
```

Creates:
- `<bucket>/state/reciter_state.json` — seeded from current data tree + open issues
- `<bucket>/state/audit.jsonl` — single seed entry (`migrated_from_v1`)

#### Step 3: Create the Space

`https://huggingface.co/new-space`:
- Name: `quranic-inspector-dev` or `quranic-inspector`
- License: same as the main project
- SDK: **Docker**
- Hardware: CPU basic (free)
- Visibility: Public

#### Step 4: Attach the Bucket as a Volume

In the Space settings → Storage Buckets section:
- Click "Attach bucket"
- Select `hetchyy/quranic-inspector-wip-dev` (or `-wip` for prod)
- Mount path: `/data/inspector-bucket`
- Access mode: **Read & Write**

Or programmatically via the [`huggingface_hub` Spaces guide](https://huggingface.co/docs/huggingface_hub/main/en/guides/manage-spaces#mount-volumes-in-your-space).

#### Step 5: Configure Space `README.md` frontmatter

Lives in the **Space repo**, pushed via the upload pipeline (§4):

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

# HF OAuth — auto-creates the OAuth client and injects credentials as env vars
hf_oauth: true
hf_oauth_expiration_minutes: 480
# hf_oauth_authorized_org: hetchyy   # uncomment if restricting login to org members
---
```

Adding `hf_oauth: true` injects:

- `OAUTH_CLIENT_ID`
- `OAUTH_CLIENT_SECRET`
- `OPENID_PROVIDER_URL`
- `OAUTH_SCOPES`

as runtime env vars. No separate OAuth client registration needed.

#### Step 6: Add Space secrets

Settings → Variables and secrets:

| Secret | Source | Notes |
|---|---|---|
| `INSPECTOR_HF_TOKEN` | HF user token with **write** scope on the bucket's namespace | Used for bucket writes + HF Jobs API calls. **Different per Space** — dev Space has its own token; prod has another. Rotate quarterly. |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN` | GitHub PAT with `repo` scope on the project repo | Used to fire `repository_dispatch` events for `update-reciters.yml` and `release.yml`. Rotate quarterly. |
| `INSPECTOR_FORWARD_SECRET` | Random 32-byte hex | HMAC for the GH Actions → Inspector forward webhook (Reciter Requests intake). Separate per Space. |
| `INSPECTOR_SESSION_SECRET` | Random 32-byte hex | HMAC for signed session cookies. Separate per Space. |
| `INSPECTOR_ALLOWED_SLUGS_REGEX` | `^_test_` for dev, **unset for prod** | Gates write endpoints to test reciters in dev |
| `INSPECTOR_BUCKET_REPO` | `hetchyy/quranic-inspector-wip-dev` (dev) or `-wip` (prod) | For audit log file paths and admin diagnostic UI |

Env vars (non-secret) come from the Dockerfile `ENV` block; most don't need overriding.

### Verifying the Space is live

After first push (§4):

```bash
curl -fsS https://hetchyy-quranic-inspector-dev.hf.space/healthz | jq
# Expect:
# {
#   "status": "ok",
#   "commit": "<sha>",
#   "mode": "deployed",
#   "bucket_mounted": true,
#   "state_loaded": true,
#   "reciters_count": 287
# }
```

If `bucket_mounted: false`: the Space settings → Storage Buckets section probably didn't pick up the mount. Restart the Space.

If `state_loaded: false`: bucket has no `state/reciter_state.json` — re-run the migration script (§Step 2).

If 503 entirely: watch the Space's build log via Settings → Logs. Common causes: Dockerfile syntax error, missing static file in COPY list, gunicorn binding to wrong port.

## 3. HF OAuth — what's set up automatically

`hf_oauth: true` in the Space frontmatter is the only setup needed. HF takes care of:

- OAuth client registration (visible in the Space settings, but not separately editable)
- Callback URL (`/auth/callback` by convention, configured via `SPACE_HOST` env var)
- Token issuance, refresh, revocation
- User profile data via `/api/whoami` on the user's token

What we add on top:

- Inspector backend's `/api/auth/login` redirects to `https://huggingface.co/oauth/authorize?...` with our client id and CSRF state.
- `/api/auth/callback` exchanges the code for tokens, fetches `/api/whoami`, creates a server-side session record `{ login, hf_user_id, expires_at }`, sets a signed session cookie.
- `/api/auth/logout` clears the session cookie + server-side record.
- `/api/me` returns the user's identity from session.

The user's HF access token is **never used by Inspector backend** for bucket writes — those use `INSPECTOR_HF_TOKEN` (the Space's own token). The user token only confirms identity at sign-in.

### Restricting access to specific HF orgs

If you want only org members to be able to sign in (e.g., maintainer-only Inspector):

```yaml
hf_oauth_authorized_org: hetchyy
```

Or list multiple:

```yaml
hf_oauth_authorized_org:
  - hetchyy
  - some-other-org
```

For a public contributor flow, leave unset.

## 4. Upload pipeline

The Space repos receive a **selective subset** of the main monorepo, not the whole tree.

### What gets pushed

```
hetchyy/quranic-inspector/                   # Space repo root = Docker build context
├── README.md                                # Space frontmatter (hf_oauth, app_port, etc.)
├── Dockerfile                               # the inspector/Dockerfile, copied to root
├── .dockerignore                            # at Space repo root
├── inspector/                               # backend + frontend dist
│   ├── app.py
│   ├── config.py constants.py
│   ├── adapters/ domain/ routes/ services/ utils/
│   └── frontend/dist/                       # PRE-BUILT — built at upload time, src/ excluded
├── validators/
├── scripts/
│   ├── __init__.py
│   └── lib/
└── data/                                    # static reference only (~89 MB)
    ├── surah_info.json  qpc_hafs.json  digital_khatt_v2_script.json
    ├── phoneme_sub_costs.json  reciters_index.json
    ├── riwayat.json  sources.json  styles.json
    ├── .audio_meta.json  .audio_durations.json
    ├── audio_catalog.json.gz                # consolidated 391 manifests
    ├── inspector_owners.json                # baked-in fallback for role resolution
    └── inspector_maintainers.json           # if exists; same
```

### What does NOT get pushed

- `inspector/frontend/src/`, `node_modules/`, `tests/`, vite config — frontend is built once during upload, only `dist/` ships
- `data/audio/` raw 67 MB of per-source manifests — replaced by `audio_catalog.json.gz`
- `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/` — fetched at runtime (HF dataset / bucket)
- `.github/`, `.local/`, `docs/`, `reciter_requests/`, validator test trees

### Upload pipeline implementation

`inspector-deploy.yml` GH Actions workflow handles the upload (see [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §6):

```yaml
# .github/workflows/inspector-deploy.yml (excerpt)
on:
  push:
    branches: [main, dev]
    paths:
      - 'inspector/**'
      - 'validators/**'
      - 'scripts/lib/**'
      - 'data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,reciters_index,riwayat,sources,styles,inspector_owners,inspector_maintainers}.json'
      - 'data/.audio_meta.json'
      - 'data/.audio_durations.json'
      - 'data/audio/**'
      - 'inspector/Dockerfile'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - name: Build frontend
        run: cd inspector/frontend && npm ci && npm run build
      - name: Build audio catalog
        run: python scripts/build_audio_catalog.py --output data/audio_catalog.json.gz
      - name: Push to HF Space
        env:
          HF_TOKEN: ${{ secrets.HF_DEPLOY_TOKEN }}
        run: ./scripts/upload_inspector.sh ${{ github.ref_name == 'main' && 'prod' || 'dev' }}
```

`scripts/upload_inspector.sh` (rsync subset → Space repo → push):

```bash
#!/usr/bin/env bash
set -euo pipefail
ENV="${1:-dev}"
SPACE_REPO_NAME="hetchyy/quranic-inspector${ENV/prod/}${ENV/dev/-dev}"
SPACE_REPO_DIR="$(mktemp -d)"

git clone "https://huggingface.co/spaces/$SPACE_REPO_NAME" "$SPACE_REPO_DIR"
cd "$SPACE_REPO_DIR"
git config user.email "deploy@hetchyy.org"
git config user.name "inspector-deploy"
git remote set-url origin "https://hetchyy:${HF_TOKEN}@huggingface.co/spaces/$SPACE_REPO_NAME"

# Wipe non-.git tracked content; rsync the selective subset
git rm -rf --quiet . || true

cd $GITHUB_WORKSPACE
rsync -av --delete \
  --include='inspector/***' --exclude='inspector/frontend/src/' \
  --exclude='inspector/frontend/node_modules/' --exclude='inspector/tests/' \
  --include='validators/***' \
  --include='scripts/__init__.py' --include='scripts/lib/***' \
  --include='data/surah_info.json' --include='data/qpc_hafs.json' \
  --include='data/digital_khatt_v2_script.json' --include='data/phoneme_sub_costs.json' \
  --include='data/reciters_index.json' \
  --include='data/riwayat.json' --include='data/sources.json' --include='data/styles.json' \
  --include='data/.audio_meta.json' --include='data/.audio_durations.json' \
  --include='data/audio_catalog.json.gz' \
  --include='data/inspector_owners.json' --include='data/inspector_maintainers.json' \
  --include='inspector/Dockerfile' --include='.dockerignore' --include='README.md' \
  --include='*/' --exclude='*' \
  ./ "$SPACE_REPO_DIR/"

cd "$SPACE_REPO_DIR"
mv inspector/Dockerfile Dockerfile
git add -A
git commit -m "deploy from $(git -C $GITHUB_WORKSPACE rev-parse HEAD)" || echo "no changes"
git push origin main
```

For local dev / manual one-off uploads (not via CI), the same script works invoked directly.

### `.dockerignore` placement

`docker build` uses the `.dockerignore` at the **build context root**. With this upload pipeline, the Space repo root is the build context, so `.dockerignore` lives at the Space repo root. The repo's `inspector/.dockerignore` is dead weight in deploy mode.

For local `docker-compose.yml` builds: the **main repo root** also needs a `.dockerignore` for local-build hygiene. Both `.dockerignore` files contain the same rules — keep in sync, or symlink in the upload pipeline.

## 5. Test environment conventions

Dev Space writes to the **same monorepo as prod** for catalog/code, but its own bucket for state and in-flight data. Discipline-based isolation:

| Convention | Enforcement |
|---|---|
| Test reciter slugs prefixed `_test_` | `INSPECTOR_ALLOWED_SLUGS_REGEX=^_test_` in dev Space rejects writes to non-test slugs |
| Test contributor accounts | HF accounts; no special setup. Sign in normally. |
| Test reciters never appear in `data/reciters_index.json` for prod | `list_reciters.py` filters by slug regex; `RECITERS.md` excludes them |

To create a test reciter:
1. Add `_test_<purpose>` to `data/reciter_catalog.json` (catalog file on GitHub).
2. Run `process_requests.py` to scaffold the alignment job (or manually push a minimal `data/recitation_segments/_test_<purpose>/` tree to the dev bucket).
3. Open the dev Space; the slug should appear in the reciter list.
4. Test the claim → edit → mark-ready → publish flow against the dev Space, signed in as a test HF account.
5. **Do NOT publish** test reciters' data to the prod dataset. The test Space's bucket is namespaced and writes go to the dev dataset (or a `_test_` prefix on the prod dataset, gated by the same regex).

## 6. Smoke tests per phase

Run after every phase deploy to dev Space, then prod Space.

### Phase 1 — Read-only deploy

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Health
curl -fsS $SPACE/healthz | jq

# Anonymous reciter list
curl -fsS $SPACE/api/reciter-task/saad_al_ghamdi | jq '.state'  # expect "completed"

# HF CDN read path (browser-direct; verify URL the frontend would generate)
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
- gunicorn process visible (not werkzeug)
- Bucket mount visible at `/data/inspector-bucket`; `state/reciter_state.json` readable

### Phase 2 — Bucket reads for in-flight

```bash
# Pick an in-flight slug (state == under_review or awaiting_review)
SLUG=$(curl -fsS $SPACE/api/reciters | jq -r '.[] | select(.state == "awaiting_review") | .slug' | head -1)

# Backend serves in-flight data from bucket
curl -fsS $SPACE/api/seg/data/$SLUG/1 | jq '.segments | length'

# Concurrent burst (NFS local cache absorbs)
for i in {1..10}; do curl -fsS "$SPACE/api/seg/data/$SLUG/1" >/dev/null & done; wait
# All 10 should complete in <1s total once the first hits warm cache
```

**Acceptance:**
- In-flight reciter p99 ≤ 1.5 s cold via bucket mount, ≤ 50 ms warm
- 10 concurrent same-file requests don't degrade the 95th percentile
- A bucket-side write made externally via CLI (`hf buckets cp` to update the file) is visible to backend reads within 30 s (mount flush bound on the writer side; mount cache eviction on the reader side)

### Phase 3 — HF OAuth + claim flow

```
1. Sign in to dev Space with a test HF account
2. Click Claim on an _test_* available reciter
3. Verify:
   - Sign-in modal appears, then HF OAuth screen (or skipped if already signed in)
   - After authorize, page returns with claim active (banner: "You're reviewing X. [Mark ready] [Release]")
   - <bucket>/state/reciter_state.json shows your login as assignee
   - <bucket>/state/audit.jsonl appended with claim event
4. Open the same reciter in another browser/incognito → see lock banner: "Currently claimed by <login>"
5. Try to claim → 409 with toast "Already claimed by @<other>"
```

**Acceptance:**
- Claim flow ≤ 3 clicks for new contributors (Claim → Continue → HF authorize)
- 1 click for returning users with active session
- State written to bucket within 100 ms (no propagation lag)
- Concurrent claim attempts: only first succeeds

### Phase 5 — Writes

```
1. Logged in as the assigned reviewer for an _test_* reciter
2. Make a small edit (trim a segment), verify:
   - Save POST returns 200
   - <bucket>/inspector-wip/_test_*/data/recitation_segments/_test_*/{detailed,segments,edit_history}.{json,jsonl} updated within 30 s
   - Local backend's parsed cache reflects the new state immediately
   - A second browser session loading the same reciter sees the new state within 30 s
```

**Acceptance:**
- Edit → bucket flush ≤ 30 s
- Backend restart mid-session: bucket has the last-flushed state intact; first save after restart works
- Save during `ready_for_merge`: 410 with clear message

### Phase 6 — Publish pipeline

```
1. Logged in as a maintainer
2. Pick a _test_* reciter in ready_for_merge state
3. Click Publish in the admin dashboard
4. Verify:
   - State transitions ready_for_merge → awaiting_timestamps within 100 ms
   - Three HF Jobs spawn (visible in dashboard's "Active Publish Operations")
     - snapshot-bucket-to-dataset (~30 s)
     - timestamps-refresh (~5-10 min)
     - build-per-verse-audio-dataset (~5 min)
   - GH Actions: update-reciters.yml + release.yml fire (visible in repo's Actions tab)
5. After ~15 min:
   - HF dataset has inspector/segments/_test_*/...
   - HF dataset has timestamps/_test_*/...
   - GitHub Release for _test_*-vX.Y.Z exists
   - RECITERS.md auto-PR opened
   - State transitions awaiting_timestamps → completed
   - Bucket entry archived to <bucket>/_archive/_test_*/...
```

**Acceptance:**
- Publish event end-to-end ≤ 15 minutes (typical), ≤ 30 minutes (worst-case with MFA Aligner cold start)
- Audit log entries for `published` + each subordinate Job's completion
- Failed Job is recoverable via `POST /api/admin/rerun-job`

## 7. Rollback procedure

### Quick rollback (revert to a prior Space build)

```bash
cd ~/.local/spaces/inspector-prod   # local clone of the Space repo
git log --oneline | head -5         # find the SHA to roll back to
git reset --hard <prior-sha>
git push --force origin main        # triggers a new build with the old contents
```

Rebuild ~1–5 min; users see 503 during. Bucket is unaffected — state and in-flight data persist.

### Kill switch (disable writes immediately)

```
Space settings → Variables and secrets → set INSPECTOR_ALLOWED_SLUGS_REGEX=^$
Restart Space (Settings → Restart)
```

All write endpoints now 403; reads continue. Faster than a rollback.

### Full disable (take Inspector offline)

```
Space settings → Pause Space
```

Returns 503 to everyone. Use when bug is severe. Don't forget to unpause; pre-warn users via Discord/issue if outage will be long.

### HF token revoke (emergency)

If the bucket-write token is compromised:

```
1. Generate a new HF token in https://huggingface.co/settings/tokens (write scope on the bucket namespace)
2. Update INSPECTOR_HF_TOKEN in Space secrets
3. Restart Space (writes resume with new token)
4. Revoke the old token in HF settings
```

While the old token is still valid (between rotation and revoke), Inspector continues to function with the new token. Bucket writes from the old token (if anyone has it) still succeed but log them via HF's audit. Once revoked, old token is dead.

### Bucket access removed (emergency, last resort)

If something goes very wrong and the bucket needs to be sealed:

```
hf buckets list   # find the bucket
# In the Hub UI: Bucket settings → Access → mark private OR remove the Space's mount
```

This breaks the Inspector entirely until a maintainer re-attaches. Use only for an active incident.

## 8. Concrete file structures

### HF dataset (`hetchyy/quranic-universal-ayahs`)

```
hetchyy/quranic-universal-ayahs/
├── manifest.json.gz                          # extended with inspector_shard_hashes per reciter
├── data/...                                  # per-verse audio + word timestamps (existing)
├── timestamps/<slug>/<chapter>.json.gz       # TS chapter shards
├── segments/<slug>/<chapter>.json.gz         # slim shards for Aligner preload (existing)
├── _resources/
│   ├── qpc_hafs.json.gz                      # also baked into Inspector image
│   ├── digital_khatt_v2_script.json.gz       # also baked into Inspector image
│   └── DigitalKhattV2.otf                    # also baked into Inspector image
└── inspector/                                # NEW namespace — Inspector full-fidelity reads
    └── segments/<slug>/
        ├── segments.json.gz
        ├── detailed.json.gz
        ├── edit_history.jsonl.gz
        ├── edit_history_peaks.jsonl.gz
        └── low_confidence_v2.json.gz
```

**Storage budget:** ~300 completed reciters × ~3-5 MB gz/reciter ≈ 1-2 GB added.

### HF Bucket (`hetchyy/quranic-inspector-wip{,-dev}`)

```
hetchyy/quranic-inspector-wip/
├── inspector-wip/                            # one subtree per in-flight reciter
│   └── <slug>/data/recitation_segments/<slug>/
│       ├── segments.json
│       ├── detailed.json
│       ├── edit_history.jsonl
│       ├── edit_history_peaks.jsonl
│       └── low_confidence_v2.json
├── state/
│   ├── reciter_state.json                    # source of truth, Inspector is sole writer
│   └── audit.jsonl                           # append-only state event log
└── _archive/                                 # post-publish snapshots (or empty if archive policy = delete)
    └── <slug>/<published_at>/...
```

**Storage budget:** ~20 in-flight × ~15 MB ≈ 300 MB sustained working set; archive grows by ~15 MB per published reciter (delete after first month if storage cost matters).

### HF Space repo (`hetchyy/quranic-inspector{,-dev}`)

What lands via the upload pipeline (§4):

```
hetchyy/quranic-inspector/
├── README.md                          # Space frontmatter + hf_oauth: true
├── Dockerfile                         # repo's inspector/Dockerfile, copied to root
├── .dockerignore                      # at Space repo root
├── inspector/
│   ├── app.py  config.py  constants.py
│   ├── adapters/  domain/  routes/  services/  utils/
│   └── frontend/dist/                 # PRE-BUILT
├── validators/
├── scripts/
│   ├── __init__.py
│   └── lib/
└── data/                              # static reference only (~89 MB)
    ├── surah_info.json  qpc_hafs.json  ...
    └── audio_catalog.json.gz
```

Secrets live in HF Space settings, not in the pushed tree.

### `/tmp` on the running container

Ephemeral filesystem, lost on rebuild/restart.

```
/tmp/
└── inspector-cache/                   # peak/canonical-phoneme cache (INSPECTOR_CACHE_DIR)
    └── <slug>/
        ├── peaks/                     # disk-backed peaks cache for warm-rescue
        └── canonical_phonemes.json    # was .pkl in local mode; JSON in deployed
```

The v1 `inspector-scratch/` is gone — bucket mount is the working surface, no separate scratch concept.

## 9. Maintenance procedures

### Rotating the Space's `INSPECTOR_HF_TOKEN`

1. Generate a new token in https://huggingface.co/settings/tokens with **write** scope on the bucket namespace.
2. Update `INSPECTOR_HF_TOKEN` in dev Space settings first; restart dev Space; verify auth via `/healthz` (should show `bucket_mounted: true`) and a test claim.
3. Update prod Space; restart; verify.
4. Revoke the old token in HF settings.

Don't rotate dev and prod simultaneously — keep one as a known-good reference during the swap.

### Rotating the dispatch token

1. Generate a new GitHub PAT with `repo` scope on the project repo.
2. Update `INSPECTOR_GITHUB_DISPATCH_TOKEN` in dev Space first; restart; verify by triggering a publish on a test reciter and checking `update-reciters.yml` actually runs.
3. Update prod Space; verify.
4. Delete the old PAT in GitHub settings.

### Forcing a Space rebuild

```bash
cd ~/.local/spaces/inspector-prod
git commit --allow-empty -m "force rebuild"
git push origin main
```

Or via HF UI: Settings → Factory rebuild (clears HF-side build cache too).

### Reading the audit log

```bash
hf buckets cp \
  hf://buckets/hetchyy/quranic-inspector-wip/state/audit.jsonl - \
  | tail -100 | jq
```

Or via the admin dashboard's Recent Events panel.

### Diagnosing slow requests

1. Space → Logs panel — search for slow request log lines (gunicorn logs request durations by default).
2. Most likely culprits in order:
   - ffmpeg fork on cold peaks (mitigation: ensure CDN headers are set; eventually CDN-front)
   - Cold validator run on first request (mitigation: gate `/api/seg/trigger-validation` to maintainers)
   - Cold `detailed.json` parse (parsed cache should warm; if not, check cache hit rate)
   - Bucket mount cold fetch (NFS lazy fetch on first access; warm cache after)
3. Verify cache health: `GET /api/admin/health` returns hit/miss ratios per layer.

### Manually running a publish HF Job

If a Job fails and the maintainer dashboard isn't responsive:

```bash
hf jobs run \
  --image hetchyy/inspector-jobs:latest \
  -v "hf://buckets/hetchyy/quranic-inspector-wip:/data/bucket" \
  -e "SLUG=<slug>" \
  -- python scripts/jobs/snapshot_bucket_to_dataset.py
```

Same image as the auto-fired Job, just invoked directly via CLI.

## 10. Phase-by-phase checklist

- [ ] **Phase 0** — Buckets created (dev + prod); state file pre-seeded; `services/state.py` + `services/hf_bucket.py` landed; `inspector_owners.json` + optional `inspector_maintainers.json` created.
- [ ] **Phase 1** — Dev Space deployed; gunicorn (not werkzeug); `audio_catalog.json.gz` baked in; HF dataset has `inspector/segments/<slug>/...` for currently-eligible reciters; smoke tests pass.
- [ ] **Phase 2** — Bucket mount working; in-flight reciter renders via bucket; concurrent reads don't degrade.
- [ ] **Phase 3** — HF OAuth + claim flow live; ≤ 3 clicks for new contributors, 1 for returning; state writes synchronous; audit log appended.
- [ ] **Phase 5** — Volunteer round-trips an edit on `_test_*` reciter; bucket flush ≤ 30 s; publish endpoint live.
- [ ] **Phase 6** — Publish pipeline end-to-end: bucket → dataset, timestamps refreshed, GitHub Release created, RECITERS.md auto-PR'd; v1 workflows decommissioned; `find_segments_pr.py` deleted; contributor docs point at the website.
