# Inspector Deploy Runbook (v2)

Operational companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). Those are decision docs; this is the action doc — what to actually do, in order, when standing up the deployed Inspector.

Audience: anyone executing a deploy phase or maintaining the live Spaces. Does not duplicate architectural rationale.

## 1. Hosting target — HF Spaces, free tier, with one HF Bucket per env

The Inspector deploys as a Hugging Face Space using the Docker SDK on free **CPU-basic** tier (2 vCPU shared, 16 GB RAM, ephemeral disk). Each Space mounts **one private HF Storage Bucket**. All in-flight + completed reciter data, the catalog, the state file, and the audit log live in that single bucket — different folders inside it (`wip/`, `published/`, `catalog/`, `state/`, `audit/`, `_archive/`).

### Topology

| Purpose | Space | Visibility | Bucket | Branch trigger |
|---|---|---|---|---|
| **Production** | `hetchyy/quranic-inspector` | Public | `hetchyy/quranic-inspector-bucket` (private) | push to `main` |
| **Development** | `hetchyy/quranic-inspector-dev` | Private (`hf_oauth_authorized_org: hetchyy`) | `hetchyy/quranic-inspector-bucket-dev` (private) | push to `dev` |

URLs:

- prod: `https://hetchyy-quranic-inspector.hf.space`
- dev: `https://hetchyy-quranic-inspector-dev.hf.space`

URLs are stable across rebuilds, sleep/wake, restarts, and config changes.

### One private bucket per env (D5)

| Bucket | Mount path | Visibility | Contents |
|---|---|---|---|
| `quranic-inspector-bucket{,-dev}` | `/data/inspector-bucket` | **Private** | `state/reciter_state.json`, `audit/<YYYY>-<MM>.jsonl`, `catalog/reciter_catalog.json`, `catalog/audio_meta.json`, `catalog/audio_durations.json`, `wip/<slug>/...`, `published/<slug>/...`, `_archive/<slug>/<published_at>/...` |

Both browser reads and writes for in-flight + completed reciter data flow through the Inspector backend (which is already in the read path for auth/state/lock). No public bucket — the bucket is private and the backend is the only consumer of `INSPECTOR_HF_TOKEN`. External tools that legitimately need to read state (`update-reciters.yml`, `release.yml`, `bucket-data-hygiene.yml`, the timestamps-refresh HF Job) authenticate with the same token and read via `huggingface_hub`.

This collapses the previous "public data bucket + private metadata bucket" split: every byte is sensitive enough to keep behind a token. The PII-in-audit justification for two buckets is moot now.

### Test reciter discipline (dev only)

Dev and prod are **completely independent**: separate Spaces, separate buckets, separate catalogs (each catalog is in its own bucket). So:

- Test reciters live only in the dev bucket's catalog. Prod bucket's catalog never sees them — **no cross-contamination is possible**, no `_test_*` filter needed in `list_reciters.py` (which reads from prod bucket when generating prod `RECITERS.md`).
- Slug naming for test reciters: any naming works; `_test_*` is just a convention to make them visually obvious in the dev UI.
- Audio sources for test reciters: tiny verses or even synthetic silence files for fast iteration.
- The dev bucket can be wiped/reseeded freely; nothing in dev affects prod data.

`INSPECTOR_ALLOWED_SLUGS_REGEX` is **dropped** — it existed to defend a shared-data model that v2 doesn't have. Independent buckets are the isolation.

### Bot HF account discipline

`INSPECTOR_HF_TOKEN` and `INSPECTOR_GITHUB_DISPATCH_TOKEN` are minted from a **dedicated bot account** (`hetchyy-bot` or similar), not from a maintainer's personal HF account. Reasons:

- Token leak blast-radius confined to the bot account, not a person's whole Hub presence.
- Easier to rotate (no entanglement with personal subscriptions).
- The audit log shows `actor.login_at_time = bot-account` for system-fired events, which is clearer than seeing a maintainer's personal login on automated transitions.

Token scope: when HF supports fine-grained tokens scoped to specific buckets (or via Resource Groups on Team/Enterprise plans), use that. Until then, the bot-account containment is the practical mitigation.

**Sleep behaviour on free tier:** 48-hour idle timeout, not configurable. Wake-up: 30–60 s for sleep state. For an active project, sleep is effectively never reached.

**Rebuild behaviour:** push to the Space repo → HF queues build → ~1–5 min build time → swap to new container. **No zero-downtime swap on free tier.** Active users get 503s during the build window. Active reviewer mid-edit: their next save POST returns 503 until rebuild completes; bucket persists across rebuilds (that's the whole point), so re-fetching the page after rebuild picks up where they left off.

**When to leave free tier:** see [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers. Migration target: HF CPU-upgrade ($0.03/h) or Fly.io shared-cpu-2x@2GB.

## 2. HF Space + Bucket setup

### Per environment (do twice — dev first, then prod)

#### Step 1: Create the Bucket

```bash
hf buckets create hetchyy/quranic-inspector-bucket-dev --private   # dev
hf buckets create hetchyy/quranic-inspector-bucket --private       # prod
```

Or via the Hub UI: `https://huggingface.co/new-bucket` (set visibility to **private**).

The bucket holds all in-flight + completed reciter data, catalog, state, and audit. Browsers reach it only through the Inspector backend, which authenticates with `INSPECTOR_HF_TOKEN`.

#### Step 2: Manually seed the bucket

One-time, ~15 reciters at v2 cutover. Author the initial files locally then upload via `hf buckets cp`:

```bash
# State (single source of truth in the bucket)
hf buckets cp ./bootstrap/state/reciter_state.json \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json

# Audit (current-month partition seeded with one bootstrap entry)
hf buckets cp ./bootstrap/audit/2026-05.jsonl \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/2026-05.jsonl
hf buckets cp ./bootstrap/audit/_meta.json \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/_meta.json

# Catalog (one consolidated file with vocab + reciters + aliases)
hf buckets cp ./bootstrap/catalog/reciter_catalog.json \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/catalog/reciter_catalog.json

# Optional sidecars (cache reseeded on first use otherwise)
hf buckets cp ./bootstrap/catalog/audio_meta.json \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/catalog/audio_meta.json
hf buckets cp ./bootstrap/catalog/audio_durations.json \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/catalog/audio_durations.json
```

Mapping rules for `reciter_state.json` are in [`inspector-state-management.md`](inspector-state-management.md) §3 "State seeding". The catalog `reciters[]` is migrated from the previous `data/reciters_index.json` + per-reciter manifest `_meta` blocks; `vocab.riwayat` / `vocab.styles` / `vocab.audio_sources` migrate from `data/riwayat.json` / `data/sources.json` / `data/styles.json`. After cutover, those `data/*.json` files are deleted from the repo (per cleanup-registry §2).

For the **prod** environment, do the same against `quranic-inspector-bucket`.

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
- Select `hetchyy/quranic-inspector-bucket-dev` (dev) or `quranic-inspector-bucket` (prod)
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
| `INSPECTOR_HF_TOKEN` | HF user token with **read+write** scope on the bucket's namespace | Used for all bucket reads/writes + HF Jobs API calls. **Different per Space** — dev Space has its own token; prod has another. Rotate quarterly. |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN` | GitHub PAT with `repo` scope on the project repo | Used to fire `repository_dispatch` events for `update-reciters.yml` and `release.yml`. Rotate quarterly. |
| `INSPECTOR_JOB_CALLBACK_SECRET` | Random 32-byte hex | Bearer secret for the timestamps-refresh job → Inspector callback. Separate per Space. |
| `INSPECTOR_SESSION_SECRET` | Random 32-byte hex | Signing key for self-contained signed-cookie sessions. Separate per Space. |
| `INSPECTOR_BUCKET_REPO` | `hetchyy/quranic-inspector-bucket-dev` (dev) or `hetchyy/quranic-inspector-bucket` (prod) | For audit log file paths and admin diagnostic UI |

(`INSPECTOR_FORWARD_SECRET` and any `_PREV` rotation slots are dropped — see canonical decisions D14 and D17.)

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

If `state_loaded: false`: bucket has no `state/reciter_state.json` — re-run the seeding step (§Step 2).

If 503 entirely: watch the Space's build log via Settings → Logs. Common causes: Dockerfile syntax error, missing static file in COPY list, gunicorn binding to wrong port.

## 3. HF OAuth — what's set up automatically

`hf_oauth: true` in the Space frontmatter is the only Hub-side setup needed. HF auto-injects four env vars at container runtime:

- `OAUTH_CLIENT_ID` — public client id
- `OAUTH_CLIENT_SECRET` — confidential client secret (used as HTTP Basic on token exchange)
- `OAUTH_SCOPES` — space-separated, defaults to `"openid profile"` (always includes these even if extra scopes added)
- `OPENID_PROVIDER_URL` — `https://huggingface.co` (OIDC discovery at `/.well-known/openid-configuration`)

**Redirect URL is freely configurable per-app** — HF doesn't whitelist; any URL targeting your Space (`https://{SPACE_HOST}/...`) works. We use `/api/auth/callback` (consistent with the rest of our API). The same exact URL must be passed to `/oauth/authorize` and to the token exchange.

### Endpoint inventory (HF side)

| Step | URL | Purpose |
|---|---|---|
| Authorize | `GET https://huggingface.co/oauth/authorize` | Redirect user here with `client_id`, `redirect_uri`, `scope=openid profile`, `state=<csrf>`, `response_type=code` |
| Token exchange | `POST https://huggingface.co/oauth/token` | Exchange `code` for tokens. HTTP Basic with `client_id:client_secret`. Body form: `grant_type=authorization_code&code=...&redirect_uri=...` |
| User identity | `GET https://huggingface.co/oauth/userinfo` | OIDC userinfo. `Authorization: Bearer <access_token>`. Returns `sub` (stable HF user id — what state-mgmt calls `hf_user_id`), `preferred_username` (the `login`), `name`, `picture`, `email_verified`, plus HF extensions (`is_pro`, `orgs[]`) |

`oauth/userinfo` is the canonical endpoint. The `whoami-v2` Hub-API endpoint also works with the OAuth access token but `oauth/userinfo` matches the OIDC standard and what `huggingface_hub`'s helpers use internally.

### Inspector backend implementation (Flask + `authlib`)

**`huggingface_hub.attach_huggingface_oauth` is FastAPI-only — not usable for our Flask app.** Use `authlib`:

```python
from authlib.integrations.flask_client import OAuth
oauth = OAuth(app)
oauth.register(
    "huggingface",
    client_id=os.environ["OAUTH_CLIENT_ID"],
    client_secret=os.environ["OAUTH_CLIENT_SECRET"],
    server_metadata_url=f"{os.environ['OPENID_PROVIDER_URL']}/.well-known/openid-configuration",
    client_kwargs={"scope": os.environ.get("OAUTH_SCOPES", "openid profile")},
)
```

Authlib auto-discovers all endpoints from the metadata URL.

Inspector routes:

- `GET /api/auth/login` — `oauth.huggingface.authorize_redirect(redirect_uri=...)`
- `GET /api/auth/callback` — `oauth.huggingface.authorize_access_token()` then `oauth.huggingface.userinfo()`; build a **self-contained signed cookie** carrying `{login, hf_user_id (sub), role, expires_at, csrf}` via Flask `itsdangerous` / Authlib (per D11)
- `POST /api/auth/logout` — clears the session cookie. **Does not** revoke the HF grant (HF has no revocation endpoint; users revoke at https://huggingface.co/settings/connected-applications)
- `GET /api/me` — returns the parsed session payload

**Session backing.** The signed cookie IS the session — there is no server-side session record (per D11). With `-w 1` this matters only for restart resilience: the cookie keeps working across container rebuilds. Cookie max-age = `hf_oauth_expiration_minutes` (default 480). On expiry, force re-auth (no refresh-token storage in Inspector — smaller blast radius if compromised).

**Authlib's OAuth state store** (used between authorize redirect and callback) does need short-lived server-side persistence for the CSRF state value — Flask-Session with a tmpfs filesystem backend at `/tmp/inspector-flask-sessions/`, ~30 s lifetime, survives within one container life which is enough.

### User POV (3 clicks first time, 1 click returning)

1. First click "Sign in with HF" → HF consent screen (lists `Read your profile (username, avatar)` for `openid profile`)
2. Click Authorize → redirected back to Inspector at `/api/auth/callback?code=...&state=...`
3. Inspector exchanges code, fetches userinfo, sets cookie, redirects to original page in edit mode

Returning user with active HF web session: HF auto-redirects through consent if scopes haven't changed → 1 click total.

### Multi-tab / multi-device

- Same browser, two tabs → same cookie, same identity.
- Two devices → independent OAuth grants, both valid simultaneously (HF allows concurrent grants per app per user).
- Logout in tab A clears that browser's cookie; tab B's cookie still works on disk (with self-contained signed-cookie design, B's cookie keeps working until expiry). Document this — for "sign out everywhere" we'd need a per-user `iat` cutoff stored in the bucket (out of v2 scope).

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
├── validators/                              # libraries; CLI wrappers retained for ad-hoc maintainer use
├── scripts/
│   ├── __init__.py
│   └── lib/
└── data/                                    # static reference only — slim per D8
    ├── surah_info.json
    ├── qpc_hafs.json
    ├── digital_khatt_v2_script.json
    ├── phoneme_sub_costs.json
    └── inspector_roles.json                 # baked-in fallback for role resolution
```

### What does NOT get pushed

- `inspector/frontend/src/`, `node_modules/`, `tests/`, vite config — frontend is built once during upload, only `dist/` ships
- `data/audio/` — deleted from the repo entirely in v2 cleanup; URL templates + `url_overrides` live in `<bucket>/catalog/reciter_catalog.json`
- `data/riwayat.json`, `data/sources.json`, `data/styles.json`, `data/reciters_index.json`, `data/.audio_meta.json`, `data/.audio_durations.json` — deleted from the repo (migrated to bucket per D6 + D8)
- `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/` — fetched at runtime (bucket via Inspector backend)
- `audio_catalog.json.gz` — no longer baked into the image (D7); audio info comes from bucket catalog
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
      - 'data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,inspector_roles}.json'
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

Dev Space writes to its own bucket; prod's bucket is untouched. Discipline-based isolation:

| Convention | Enforcement |
|---|---|
| Test reciters live only in the dev bucket's catalog | Independent buckets — prod bucket simply doesn't have them, no filter needed |
| Test contributor accounts | HF accounts; no special setup. Sign in normally. |
| Slug naming for test reciters | `_test_*` is a convention for visual clarity in the dev UI; not enforced |

To create a test reciter:
1. Add the new row to `<dev-bucket>/catalog/reciter_catalog.json` via the dev Space's admin endpoint `POST /api/admin/catalog/add` (or by hand `hf buckets cp`).
2. Use the maintainer admin path to seed the alignment job (until Inspector-native intake lands — see D17 / new deferred entry), or manually push a minimal `<dev-bucket>/wip/<slug>/` tree with a stub `detailed.json`.
3. Open the dev Space; the slug should appear in the reciter list.
4. Test the claim → edit → mark-ready → publish flow against the dev Space, signed in as a test HF account.
5. **Cross-environment isolation is automatic** — dev publish writes to the dev bucket's `published/<slug>/`; prod is unaffected.

## 6. Smoke tests per phase

Run after every phase deploy to dev Space, then prod Space.

### Phase 1 — Read-only deploy

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Health
curl -fsS $SPACE/healthz | jq

# Anonymous reciter list (browser → backend → bucket path is the only read path now)
curl -fsS $SPACE/api/reciter-task/saad_al_ghamdi | jq '.state'  # expect "completed"

# Browser → backend → bucket round-trip for a completed reciter's data shard
curl -fsSI $SPACE/api/seg/data/saad_al_ghamdi/1 | head -5

# Image discipline check
docker run --rm hetchyy/quranic-inspector:latest sh -c '
  find /app/data \( -path "*/recitation_segments/*" -o -path "*/timestamps/*" -o -name "audio_catalog.json.gz" -o -name "reciters_index.json" \) -print | head -1
' | grep -q . && echo "FAIL: image bloat" || echo "OK: image clean"
```

**Acceptance:**
- p99 cold-page-load for completed reciter ≤ 800 ms
- Image size ≤ 400 MB
- `data/recitation_segments/` empty in running container
- `audio_catalog.json.gz` absent (D7)
- `reciters_index.json`, `riwayat.json`, `sources.json`, `styles.json`, `audio/` all absent (D6 + D8)
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
   - <bucket>/state/reciter_state.json shows your hf_user_id as assignee_hf_id
   - <bucket>/audit/<YYYY>-<MM>.jsonl appended with claim event
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
   - <bucket>/wip/_test_*/{detailed,segments,edit_history}.{json,jsonl} updated within 30 s
   - Local backend's parsed cache reflects the new state immediately
   - A second browser session loading the same reciter sees the new state within 30 s
```

**Acceptance:**
- Edit → bucket flush ≤ 30 s
- Backend restart mid-session: bucket has the last-flushed state intact; first save after restart works
- Save during `marked_ready=1`: 410 with clear message

### Phase 6 — Publish pipeline

```
1. Logged in as a maintainer
2. Pick a _test_* reciter in (under_review, marked_ready=1)
3. Click Publish in the admin dashboard
4. Verify (synchronous response):
   - 200 returned with { state: "awaiting_timestamps", timestamps_job_id: "..." }
   - State transition under_review → awaiting_timestamps within 100 ms
   - <bucket>/published/_test_*/* populated (server-side copy/move from wip/)
   - <bucket>/wip/_test_*/* removed (or moved to <bucket>/_archive/_test_*/<ts>/ per archive policy)
5. ONE async HF Job spawned (visible in dashboard's "Active timestamps refresh"):
   - timestamps-refresh (~5-10 min)
6. GH Actions: update-reciters.yml + release.yml fire (visible in repo's Actions tab)
7. After ~10 min:
   - <bucket>/published/_test_*/timestamps/<chapter>.json shards exist
   - GitHub Release for _test_*-vX.Y.Z exists
   - RECITERS.md auto-PR opened
   - State transitions awaiting_timestamps → completed (driven by job-completion webhook)
```

**Acceptance:**
- Publish 200 response within 5 s (sync work: state + bucket move + dispatch + job-enqueue)
- timestamps-refresh end-to-end ≤ 10 minutes (typical), ≤ 30 minutes (worst-case with MFA Aligner cold start)
- Audit log entries for `published` + `timestamps_completed`
- Failed timestamps job: state stays in `awaiting_timestamps`; maintainer can manually re-enqueue from the dashboard

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
Space settings → Variables and secrets → set INSPECTOR_WRITES_DISABLED=1
Restart Space (Settings → Restart)
```

All write endpoints now 403; reads continue. Faster than a rollback. (Replaces the v1 `INSPECTOR_ALLOWED_SLUGS_REGEX=^$` trick — that var is dropped in v2.)

### Full disable (take Inspector offline)

```
Space settings → Pause Space
```

Returns 503 to everyone. Use when bug is severe. Don't forget to unpause; pre-warn users via Discord/issue if outage will be long.

### HF token revoke (emergency)

If the bucket token is compromised:

```
1. Generate a new HF token in https://huggingface.co/settings/tokens (read+write scope on the bucket namespace)
2. Update INSPECTOR_HF_TOKEN in Space secrets
3. Restart Space (writes resume with new token)
4. Revoke the old token in HF settings
```

While the old token is still valid (between rotation and revoke), Inspector continues to function with the new token. Bucket reads/writes from the old token (if anyone has it) still succeed but log them via HF's audit. Once revoked, old token is dead.

### Bucket access removed (emergency, last resort)

If something goes very wrong and the bucket needs to be sealed:

```
hf buckets list   # find the bucket
# In the Hub UI: Bucket settings → Access → remove the Space's mount
```

This breaks the Inspector entirely until a maintainer re-attaches. Use only for an active incident.

## 8. Concrete file structures

### HF Bucket (`hetchyy/quranic-inspector-bucket{,-dev}`) — single private bucket

```
hetchyy/quranic-inspector-bucket/                # private
├── state/
│   └── reciter_state.json                       # source of truth, Inspector is sole writer
├── audit/
│   ├── _meta.json                               # schema_version once per partition file
│   └── <YYYY>-<MM>.jsonl                        # append-only event log, partitioned monthly
├── catalog/
│   ├── reciter_catalog.json                     # vocab + reciters[] + aliases[]
│   ├── audio_meta.json                          # VBR cache (sidecar)
│   └── audio_durations.json                     # ffprobe duration cache (sidecar)
├── wip/                                         # one flat subtree per in-flight reciter
│   └── <slug>/
│       ├── segments.json
│       ├── detailed.json
│       ├── edit_history.jsonl
│       ├── edit_history_peaks.jsonl
│       └── low_confidence_v2.json
├── published/                                   # one flat subtree per completed reciter
│   └── <slug>/
│       ├── segments.json
│       ├── detailed.json
│       ├── edit_history.jsonl
│       ├── edit_history_peaks.jsonl
│       ├── low_confidence_v2.json
│       └── timestamps/<chapter>.json            # written by timestamps-refresh
└── _archive/                                    # post-publish snapshots (or empty if archive policy = delete)
    └── <slug>/<published_at>/...
```

**Storage budget:** ~20 in-flight × ~15 MB ≈ 300 MB working set in `wip/`; `published/` accumulates by ~25 MB per published reciter; archive grows by ~15 MB per published reciter (delete after first month if storage cost matters). The HF dataset (`hetchyy/quranic-universal-ayahs`) is no longer in Inspector's read path — it's downstream consumers only (training parquet, GitHub release zips).

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
├── validators/                        # libraries; CLI wrappers retained
├── scripts/
│   ├── __init__.py
│   └── lib/
└── data/                              # static reference only — slim
    ├── surah_info.json
    ├── qpc_hafs.json
    ├── digital_khatt_v2_script.json
    ├── phoneme_sub_costs.json
    └── inspector_roles.json
```

Secrets live in HF Space settings, not in the pushed tree.

### `/tmp` on the running container

Ephemeral filesystem, lost on rebuild/restart.

```
/tmp/
├── inspector-cache/                   # peak/canonical-phoneme cache (INSPECTOR_CACHE_DIR)
│   └── <slug>/
│       ├── peaks/                     # disk-backed peaks cache for warm-rescue
│       └── canonical_phonemes.json    # was .pkl in local mode; JSON in deployed
└── inspector-flask-sessions/          # ~30 s OAuth state store between authorize and callback
```

The v1 `inspector-scratch/` is gone — bucket mount is the working surface, no separate scratch concept.

## 9. Maintenance procedures

### Rotating the Space's `INSPECTOR_HF_TOKEN`

1. Generate a new token in https://huggingface.co/settings/tokens with **read+write** scope on the bucket namespace.
2. Update `INSPECTOR_HF_TOKEN` in dev Space settings first; restart dev Space; verify auth via `/healthz` (should show `bucket_mounted: true`) and a test claim.
3. Update prod Space; restart; verify.
4. Revoke the old token in HF settings.

Don't rotate dev and prod simultaneously — keep one as a known-good reference during the swap.

### Rotating `INSPECTOR_GITHUB_DISPATCH_TOKEN`

1. Generate a new GitHub PAT with `repo` scope on the project repo.
2. Update `INSPECTOR_GITHUB_DISPATCH_TOKEN` in dev Space first; restart; verify by triggering a publish on a test reciter and checking `update-reciters.yml` actually runs.
3. Update prod Space; verify.
4. Delete the old PAT in GitHub settings.

### Rotating `INSPECTOR_JOB_CALLBACK_SECRET`

The job-completion webhook is best-effort and the callback window is short (one timestamps-refresh job per publish). Single-secret rotation is fine; no `_PREV` slot.

1. Mint a fresh 32-byte hex value.
2. Update `INSPECTOR_JOB_CALLBACK_SECRET` in dev Space; restart.
3. Trigger a publish and confirm the job-completion webhook lands in the audit log (or use the manual "advance to completed" admin button if the callback is rejected during the brief overlap window).
4. Repeat for prod.

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
  hf://buckets/hetchyy/quranic-inspector-bucket/audit/2026-05.jsonl - \
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

### Manually running the timestamps-refresh job

If the job fails and the maintainer dashboard isn't responsive:

```bash
hf jobs run \
  --image hf://spaces/hetchyy/inspector-jobs-image:latest \
  -v "hf://buckets/hetchyy/quranic-inspector-bucket:/data/bucket" \
  -e "SLUG=<slug>" \
  -e "INSPECTOR_CALLBACK_URL=https://hetchyy-quranic-inspector.hf.space" \
  -e "INSPECTOR_JOB_CALLBACK_SECRET=$(read-from-secrets)" \
  -- python scripts/jobs/timestamps_refresh.py
```

Same image as the auto-fired Job, just invoked directly via CLI.

## 10. Phase-by-phase checklist

- [ ] **Phase 0** — One bucket per env created (dev + prod, both private); state file + audit + catalog seeded as JSON; `services/state.py` + `services/catalog.py` + `services/hf_bucket.py` + `services/access.py` landed; `<bucket>/access/inspector_roles.json` hand-seeded (first owner).
- [ ] **Phase 1** — Dev Space deployed; gunicorn (not werkzeug); slim `data/` baked (no `audio_catalog.json.gz`, no `reciters_index.json`); browser → backend → bucket path verified for completed reciters; smoke tests pass.
- [ ] **Phase 2** — Bucket mount working; in-flight reciter renders via bucket; concurrent reads don't degrade.
- [ ] **Phase 3** — HF OAuth + signed-cookie session live; ≤ 3 clicks for new contributors, 1 for returning; state writes synchronous; audit log appended.
- [ ] **Phase 5** — Volunteer round-trips an edit on `_test_*` reciter; bucket flush ≤ 30 s; publish endpoint live (state transition + in-bucket move + dispatch + 1 timestamps job).
- [ ] **Phase 6** — Publish pipeline end-to-end: bucket move complete, timestamps refreshed, GitHub Release created, RECITERS.md auto-PR'd; v1 workflows decommissioned; `find_segments_pr.py` deleted; `forward-to-inspector.yml` deleted; contributor docs point at the website.
