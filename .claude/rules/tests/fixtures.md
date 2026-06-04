---
description: Conftest + shared-helper discipline (BE + FE)
globs:
  - "inspector/tests/conftest.py"
  - "inspector/tests/**/conftest.py"
  - "qua_shared/tests/conftest.py"
  - "inspector/frontend/src/lib/test-helpers/**"
  - "inspector/frontend/src/**/__tests__/helpers/**"
  - "inspector/frontend/vitest.setup.ts"
---

# Tests — fixtures + conftest

- One helper used by >1 test file lives in conftest. Duplication = promote, not copy.
- BE conftest is sectioned: `# === Helpers ===` / `# === Factories ===` / `# === Fixtures ===` / `# === Autouse ===`. Keep it that way when editing.
- Single source of truth fixtures: `signed_in_client`, `tmp_reciter_dir`, `seed_state`, `seed_role`, `flask_client`, `load_fixture`, `state_persistence`, `row_spec`, `seed_rows`, `hf_user_factory`, `stub_hf_users`, `make_actor`, `patch_whoami`, `clean_validation`, `seed_transition`, `seed_request`, `intake_fs_backend`. Don't redefine.
- Every fixture has a one-line docstring describing scope + what it yields.
- Autouse fixtures must reset every mutation they make. Register new module-level caches in `_SEG_CACHE_NAMES` so `_invalidate_seg_caches` clears them.
- `qua_shared/tests/conftest.py` handles `sys.path` bootstrap for the package; no per-file `sys.path.insert`.
- FE helpers: cross-tab → `inspector/frontend/src/lib/test-helpers/<name>.ts`; tab-local → `tabs/<tab>/__tests__/helpers/<name>.ts`.

## Anti-patterns

- `scope="session"` fixture that mutates SQLite, bucket, or the access store → leaks across tests.
- `autouse=True` fixture with wide blast radius — touches >1 subsystem or wraps every test in a try/finally with hidden side effects.
- A fixture that yields `(svc, backend)` when callers only use `svc` → drop the unused field.
- Fixture that monkeypatches env vars the module under test never reads (e.g. `fresh_state` setting 3 vars `activity_state` ignores) → strip.
- `_isolated_backend` / `fs_backend` / `state_persistence` redefined per file with subtle differences → use the shared one.
- `vitest.setup.ts` patching beyond the bare minimum — every new global mock is an invisible coupling. Prefer per-test `vi.spyOn`.
