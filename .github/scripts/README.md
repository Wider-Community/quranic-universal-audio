# .github/scripts/

CI-only Python — invoked by GitHub Actions workflows, never by humans and never
importing inspector internals. Co-located with the `workflows/*.yml` that call
them; excluded from the image via `.dockerignore`'s `.github/*`.

- `update_readme_badges.py` — refresh the root README stats badges from the prod
  bucket DB (`update-badges.yml`, daily cron)
- `package_release.py` — build per-reciter `.zip` GitHub-Release assets from the
  `data/` tree (`release.yml`, manual dispatch)
- `build_reciter.py` — **stale v1 dataset builder** (its driving `sync-dataset.yml`
  was removed and it imports a deleted helper). Kept pending a decision on whether
  the v1 HF parquet dataset still needs a manual rebuild; see the repo TODO.

For where a new script belongs, see
[`inspector/scripts/README.md`](../../inspector/scripts/README.md).
