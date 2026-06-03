# Scripts refactor — regression surfaces & rollback runbook

Deploy-risk assessment for the `scripts/` refactor PR (branch
`hetchy/funny-proskuriakova-6fe2f1`). Read before merging to `main` / deploying
prod. Delete once the deploy has settled.

## What changed (commit map)

| Commit | Change | Highest-risk surface |
|---|---|---|
| `19a162e0` | `scripts/lib`→**`qua_shared`**, `scripts/jobs`→**`qua_jobs`** (root packages) | **app runtime + HF jobs** |
| `276d49cb` | CI hygiene; wire `qua_shared/tests` into CI | CI |
| `f7c0262a` | freeze migrations under `scripts/migrations/`; drop dead code | ops scripts |
| `dd4ef681` | per-home READMEs + decision rule | — (docs) |
| `8b3e76e6` | collapse all ops CLIs into one `scripts/<function>/` home | **CI + deploy + ops** |
| `a4c8a7d9` | repoint stale refs the sweep missed (`.js`/`.txt`/`.md`) | — (docs) |

**Risk ranking:** (1) HF jobs — fails at *runtime*, not CI. (2) Deploy/image. (3) CI gates. (4) Ops CLIs. App runtime is low-risk (covered by the 986-test suite that exercises ~120 `qua_shared` import sites).

## Pre-merge: what CI already proves

The PR's CI (`docker-publish` → `inspector-checks`) gates:
- `backend-checks` — 986 pytest (every `qua_shared` import site) **+** `qua_shared/tests` (newly wired).
- `schema-codegen-check` — regenerates `schemas.ts` from `qua_shared.schemas.fe_types`; fails on drift (verified the banner matches).
- `frontend-checks` — eslint + tsc + vitest + build.
- the image build (`context: .`, `inspector/Dockerfile`) — proves `COPY qua_shared/ qua_jobs/` resolve.

**Green CI ⇒ app boot, FE types, and image build are safe.** The two things CI does **not** prove: a live HF-job run, and a live Space deploy. Those are §1 and §2 below.

---

## 1. HF Jobs (`qua_jobs/*`) — HIGHEST residual risk

Jobs run *remotely* and import `qua_shared`; CI can't exercise a real run. The launcher (`services/admin/jobs/base.py`, `services/admin/timestamps_jobs.py`) runs **inside the deployed Space**, so this is only exercised after §2 deploys.

**Invariant chain (must all agree):**
- staging walk uploads `("qua_shared", "qua_jobs")` → `aligner-bucket/code/qua_shared/…`, `code/qua_jobs/…`
- entrypoints run `python /aux/code/qua_jobs/{cut_release,publish_hf,generate_timestamps}.py`
- `PYTHONPATH=/aux/code` → remote `import qua_shared` resolves at `/aux/code/qua_shared`
- `cut_release.py` reads `_code_root()/qua_jobs/shard.py`

**Built-in early detection:** `stage_job_code()` preflights `REQUIRED_ENTRYPOINTS` (`qua_jobs/*.py`) and raises `JobStagingError` **before** `run_job` if any are missing — so a path mistake surfaces as a clear operator error at launch, not a silent hang.

| Symptom | Likely cause | Quick fix |
|---|---|---|
| `JobStagingError: required files missing … qua_jobs/*.py` at launch | walk/entrypoint list out of sync, or Space deployed without `qua_jobs/` | confirm `inspector/Dockerfile` COPYs `qua_jobs/`; redeploy Space |
| Job container: `ModuleNotFoundError: qua_shared` | `PYTHONPATH` ≠ `/aux/code`, or `code/qua_shared/` not staged | check `env["PYTHONPATH"]` in the launcher; re-run (staging is idempotent) |
| `cut_release` job: `FileNotFoundError … shard.py` | `_code_root()/qua_jobs/shard.py` path wrong | verify `qua_jobs/cut_release.py` reads `qua_jobs/shard.py` (not `scripts/jobs/`) |

**Mitigation / smoke:** after deploying dev, launch one **timestamps-gen** (cheapest) on a test reciter from the Reviews tab and confirm it reaches "succeeded". That single run exercises staging + entrypoint + `qua_shared` import end-to-end. Only then cut a dev release.

**Stale leftover (not a regression):** the old `aligner-bucket/code/scripts/lib`, `code/scripts/jobs` are not deleted by the new staging — harmless (jobs run from `code/qua_jobs/`). Optional cleanup later.

**`.local/cut_sim`** (local cut simulator) was swept on disk to `qua_jobs`/`qua_shared` but is uncommitted (private repo) — only affects local cut rehearsal, not prod.

---

## 2. Deploy / image (`scripts/deploy/upload_inspector.py`)

`upload_inspector.py` stages **every git-tracked file** to the Space; `.dockerignore` prunes; the Space builds via `inspector/Dockerfile`.

| Symptom | Likely cause | Quick fix |
|---|---|---|
| Space build `BUILD_ERROR: COPY qua_shared failed` | `qua_shared/`/`qua_jobs/` excluded by `.dockerignore` or not staged | confirm root `.dockerignore` doesn't exclude them (it doesn't); they're tracked so they stage |
| `inspector-deploy.yml` step "command not found" | workflow still calls old path | it calls `scripts/deploy/{upload_inspector,smoke_boot}.py` — verified present |
| Deploy didn't trigger on a `qua_jobs/` change | path filter | `inspector-deploy.yml` now includes `qua_jobs/**` (added) |
| `upload_inspector` import error on `qua_shared._env` | its repo-root insert is `parent.parent.parent` (it's 3-deep at `scripts/deploy/`) | verified |

**Mitigation:** `python scripts/deploy/upload_inspector.py dev --verify-boot` builds + boots the staged image offline (`/healthz`) before uploading — run it for the first prod deploy.

---

## 3. CI gates

| Workflow | Risk | Detection |
|---|---|---|
| `inspector-checks` (pytest/codegen/frontend) | a missed import/path ref | the job itself; all verified locally (986+30) |
| `docker-publish` | `paths:` filter `scripts/lib/**`→`qua_shared/**` etc. | builds image; path filters updated |
| `inspector-deploy` | `paths:` + script paths | updated (`qua_shared/**`, `qua_jobs/**`, `scripts/deploy/upload_inspector.py`) |
| `release.yml` | `package_release.py` (unmoved) + its `sys.path` insert `ROOT/"qua_shared"` | updated; **deferred to-do**: move to `scripts/release/` |
| `update-badges.yml` | `update_readme_badges.py` (unmoved) | unaffected |

There is **no Python-lint CI gate**, so the pre-existing `ruff` debt (unused imports, the `DEFAULT_BEAM` CLI bug) does **not** fail CI.

---

## 4. App runtime — LOW risk

~120 `qua_shared` import sites; the capability registry, FE-type source, and timestamps/segments read-paths all import it. **Covered by the 986-test suite** (collection alone would fail on any broken import). Boot also re-checked: `app.py` inserts repo root → `import qua_shared` resolves; same in the image (`/app` on `sys.path[0]`).

| Symptom | Likely cause | Quick fix |
|---|---|---|
| App 500s on boot, `ModuleNotFoundError: qua_shared` | repo root not on `sys.path` | `app.py:_REPO_ROOT` insert intact; check image COPY |
| `/healthz` 503 | unrelated (bucket/state) — not import | see `config-deploy.md` |

---

## 5. Ops CLIs (`scripts/<function>/`)

Moves are same-depth (`inspector/scripts/X`→`scripts/<sub>/X`, both 2-deep) so `parents[2]` repo-root anchors stayed valid. Fixed depth-sensitive cases: the two `migrations/` files, `upload_inspector`, `smoke_boot`→`seed_fixtures` (cross-folder sibling), `bootstrap_dev_env`→`deploy_space` shell-out, `bucket/_bootstrap`. Made `purge_*`/`bench_storage`/`check_eligibility_parity` self-sufficient on `sys.path`.

| Symptom | Likely cause | Quick fix |
|---|---|---|
| a CLI: `ModuleNotFoundError: services`/`qua_shared` | script doesn't self-insert both paths | the touched ones now do; pattern: insert `repo` **and** `repo/"inspector"` |
| `test_migration` / `test_make_fixtures` fail | loader path | updated to `parents[3]/"scripts"/…` (migrations moved out of `inspector/`) |
| `smoke_boot` can't import `seed_fixtures` | sibling moved to `devenv/` | inserts `parent.parent/"devenv"` |

---

## Rollback / revert

The change is **commit-isolated on a branch; nothing is on `main` or deployed yet.**

**Full rollback (preferred if app/jobs break post-merge):**
```
git revert --no-edit <merge-commit>     # or: gh pr revert <N>
# redeploy: push to dev/main re-triggers inspector-deploy → upload_inspector
```
Reverting restores `scripts/lib`/`scripts/jobs` and all old paths atomically. The HF-job staging in the *reverted* image re-uploads `code/scripts/{lib,jobs}` on the next launch — self-healing.

**Targeted fixes are usually faster than revert** (the riskiest failures are one-liners):
- job entrypoint/staging wrong → edit `services/admin/jobs/base.py` (walk tuple + `REQUIRED_ENTRYPOINTS`) or the per-kind `_ENTRYPOINT`, redeploy Space.
- deploy path filter → edit `inspector-deploy.yml`.
- a CLI path → fix that file's `parents[N]`/`sys.path` insert.

**Do NOT** partially revert only `19a162e0` (the rename) — commits 3/5 depend on it. Revert the whole PR or fix forward.

## Post-deploy smoke checklist (dev first, then prod)

1. Space builds & `/healthz` 200 (`upload_inspector … --verify-boot` for prod).
2. App: load Timestamps + Segments for a published reciter (exercises `qua_shared` read-paths).
3. Jobs: launch one **timestamps-gen** → reaches "succeeded" (exercises staging + `qua_jobs` + `qua_shared` remotely).
4. Releases: dry-run / cut a **dev** release (exercises `qua_jobs/cut_release` + `shard.py` read).
5. `regen_fe_types` + `schema-codegen-check` green on the merge commit.
