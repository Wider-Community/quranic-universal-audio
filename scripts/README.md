# scripts/ (root)

Repo-wide operational CLIs — a script earns a place here **only if its unit of
work is the entire repo**. Today that's exactly one resident:

- `upload_inspector.py` — stage every git-tracked file and deploy the whole repo
  to the canonical dev/prod HF Space (invoked by `inspector-deploy.yml`).

Everything else lives closer to what it serves:
- **Inspector-coupled** ops (import `services.*`) → [`inspector/scripts/`](../inspector/scripts/)
- **CI-only** glue → [`.github/scripts/`](../.github/scripts/)
- **Shared runtime code** (imported, shipped) is a package, not a script →
  `qua_shared/` (library + schemas) or `qua_jobs/` (HF-Job entrypoints)

See [`inspector/scripts/README.md`](../inspector/scripts/README.md) for the full
"where does a new script go?" decision rule.
