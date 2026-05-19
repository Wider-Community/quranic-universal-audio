# Inspector configuration — env vars, Space secrets, and variables

Reference for every knob the Inspector reads at runtime: environment
variables consumed by `inspector/`, secrets stored on the deployed
Hugging Face Space, and the Space variables the container sees as plain
env. Local-mode defaults are baked into `inspector/config.py` and
`inspector/Dockerfile`; deployed-mode values come from the Space's
secrets/variables panels (provisioned by `scripts/inspector_v2_seed/
setup_space.py`).

## Spaces

| Env  | Repo                             | Bucket attached at `/data/inspector-bucket` |
|------|----------------------------------|---------------------------------------------|
| dev  | `hetchyy/quranic-inspector-dev`  | `hetchyy/quranic-inspector-bucket-dev`      |
| prod | `hetchyy/quranic-universal-audio` | `hetchyy/quranic-inspector-bucket`          |

Both Spaces ship the Docker SDK, bind to port 7860, and use the same
image (the only diff is the `INSPECTOR_BUCKET_REPO` variable and the
attached bucket).

## Storage backend

The bucket is the persistence layer. The container has no other writable
state — `/tmp/inspector-cache` survives only as long as the container.

| Variable                       | Default                              | Purpose                                                                 |
|--------------------------------|--------------------------------------|-------------------------------------------------------------------------|
| `INSPECTOR_BACKEND`            | `bucket`                             | `bucket` (HF storage) or `filesystem` (tests / offline maintainer)      |
| `INSPECTOR_BUCKET_REPO`        | `hetchyy/quranic-inspector-bucket` | HF bucket repo id; dev Space overrides to `…-bucket-dev`                  |
| `INSPECTOR_BUCKET_MOUNT`       | unset locally; `/data/inspector-bucket` on Space | Mount path inside the container. When unset, the backend falls back to per-call HF API reads. |
| `INSPECTOR_FILESYSTEM_ROOT`    | unset                                | Required only when `INSPECTOR_BACKEND=filesystem`                       |

## Data locations

| Variable                  | Default               | Purpose                                                                         |
|---------------------------|-----------------------|---------------------------------------------------------------------------------|
| `INSPECTOR_DATA_DIR`      | `/app/data` (Space) / `<repo>/data` (local) | Root for static data baked into the image (surah_info + linguistic JSONs) |
| `INSPECTOR_QUA_DATA_PATH` | mirrors `INSPECTOR_DATA_DIR`               | Path containing `qpc_hafs.json`, `digital_khatt_v2_script.json`, `phoneme_sub_costs.json` |
| `INSPECTOR_PARSED_CACHE_BYTES` | `134217728` (128 MB) | Soft cap on the in-memory parsed-segments LRU                                   |

## Timestamps tab

| Variable                          | Default | Purpose                                                                              |
|-----------------------------------|---------|--------------------------------------------------------------------------------------|
| `INSPECTOR_TS_SOURCE`             | `bucket` (Space) / `local` (compose) | `local` slices `data/timestamps/by_*/*/timestamps_full.json` on disk; `bucket` reads `<bucket>/published/<slug>/timestamps/<chapter>.json`. The legacy `huggingface` value (FE→HF dataset CDN direct) is removed. |

## Authentication

OAuth client credentials are auto-injected by Hugging Face whenever the
Space README frontmatter sets `hf_oauth: true`. The Inspector backend
reads them but never persists user tokens.

| Variable / secret       | Source             | Purpose                                                                                                                 |
|-------------------------|--------------------|-------------------------------------------------------------------------------------------------------------------------|
| `OAUTH_CLIENT_ID`       | injected by HF     | OAuth client id (auto-managed)                                                                                          |
| `OAUTH_CLIENT_SECRET`   | injected by HF     | OAuth client secret (auto-managed)                                                                                      |
| `OPENID_PROVIDER_URL`   | injected by HF     | OIDC discovery endpoint (auto-managed)                                                                                  |
| `INSPECTOR_SESSION_SECRET` | Space secret (auto-generated, 32-byte hex) | Signs the self-contained cookie that carries `{login, hf_user_id, role, expires_at, csrf}`. Rotating logs every user out. |

## Inter-service auth

| Secret                                | Purpose                                                                                                                                              |
|---------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| `INSPECTOR_HF_TOKEN` (alias: `HF_TOKEN`) | Token Inspector uses to read + write the bucket. Needs write scope on the bucket repo. Prod should mint a dedicated bot account token, not a personal token. |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN`     | Fine-grained GitHub PAT (repo: `Wider-Community/quranic-universal-audio`, scope: `actions: write`). Fires `repository_dispatch reciter.completed` after publish so `update-reciters.yml` and `release.yml` rerun. `services/auth/secrets_guard.py::get_dispatch_token` raises if the slot still holds the seed placeholder. |
| `INSPECTOR_JOB_CALLBACK_SECRET`       | Bearer token Inspector validates on `POST /api/internal/job-completed` (HF Job → Inspector webhook). 32-byte hex auto-generated on first Space setup. |

## Image build / runtime

| Variable           | Default | Purpose                                                                                                                                |
|--------------------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| `GUNICORN_WORKERS` | `1`     | Asserted at boot. Multi-worker scale-out requires a shared coordinator that the codebase doesn't include; Inspector refuses to start otherwise. |
| `INSPECTOR_HOST`   | `0.0.0.0` | Bind host                                                                                                                            |
| `INSPECTOR_COMMIT_SHA` | `unknown` | Reported by `/healthz` so deploys are identifiable                                                                                |
| `FLASK_ENV`        | unset   | Set to `development` to enable Flask debug + reloader (local only)                                                                     |

## Idempotency markers

| Variable                    | Value | Purpose                                                                                                              |
|-----------------------------|-------|----------------------------------------------------------------------------------------------------------------------|
| `INSPECTOR_SECRETS_SEEDED`  | `1`   | Written by `setup_space.py` after first successful auto-generation of `INSPECTOR_SESSION_SECRET` + `INSPECTOR_JOB_CALLBACK_SECRET`. Subsequent `--apply` runs preserve those secret slots instead of rotating. |

## Provisioning

`scripts/inspector_v2_seed/setup_space.py` is the single entry point for
Space configuration. Idempotent; dry-run by default.

```
python -m scripts.inspector_v2_seed.setup_space dev --apply
python -m scripts.inspector_v2_seed.setup_space prod --apply
```

It creates the Space (private, Docker SDK), writes the README frontmatter
(`hf_oauth: true`, `hf_oauth_expiration_minutes: 480`), attaches the
bucket volume, sets every variable above, seeds the secrets, and
factory-reboots. Re-runs preserve auto-generated secrets via the
`INSPECTOR_SECRETS_SEEDED` marker.

## Rotation

- `INSPECTOR_HF_TOKEN` — generate a new token, update the Space secret, restart. Old token revocation can wait until rotation is verified.
- `INSPECTOR_SESSION_SECRET` — delete the Space secret slot, re-run `setup_space.py --apply`. A fresh value is generated and printed once. **All in-flight signed cookies invalidate** — every user is logged out.
- `INSPECTOR_JOB_CALLBACK_SECRET` — same as session secret. Any HF Job in flight that hasn't called back yet will 401 on its callback.
- `INSPECTOR_GITHUB_DISPATCH_TOKEN` — mint a new PAT, update the Space secret, restart.

## Health

`GET /healthz` returns the resolved configuration so a smoke test can
catch misconfiguration:

```json
{
  "status": "ok | degraded",
  "mode": "deployed | local",
  "bucket_mounted": true,
  "state_loaded": true,
  "reciters_count": 14,
  "commit": "<sha-or-unknown>"
}
```

Returns HTTP 503 in deployed mode when `bucket_mounted` or `state_loaded`
is false so an external probe can detect the degradation without parsing
the body.

`GET /livez` is the tiny always-200 liveness probe.
