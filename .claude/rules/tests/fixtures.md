---
paths:
  - "inspector/tests/conftest.py"
  - "inspector/tests/**/conftest.py"
  - "qua_shared/tests/conftest.py"
  - "inspector/frontend/src/lib/test-helpers/**"
  - "inspector/frontend/src/**/__tests__/helpers/**"
  - "inspector/frontend/vitest.setup.ts"
---

# Tests — fixtures + conftest

- One helper used in >1 test file lives in conftest. Duplication = promote, not copy.
- BE conftest is sectioned: `# === Helpers ===` / `# === Factories ===` / `# === Fixtures ===` / `# === Autouse ===`. Preserve when editing.
- Every fixture has a one-line docstring (scope + what it yields).
- Autouse fixtures must reset every mutation they make. Register new module-level caches in `_SEG_CACHE_NAMES` so `_invalidate_seg_caches` clears them.
- `qua_shared/tests/conftest.py` handles `sys.path` bootstrap; no per-file `sys.path.insert`.
- FE helpers: cross-tab → `inspector/frontend/src/lib/test-helpers/<name>.ts`. Tab-local → `tabs/<tab>/__tests__/helpers/<name>.ts`.

## Anti-patterns

- `scope="session"` fixture that mutates SQLite, bucket, or the access store → leaks across tests.
- `autouse=True` fixture with wide blast radius (touches >1 subsystem, hidden try/finally side effects).
- Fixture that yields `(svc, backend)` when no caller uses `backend` → yield just `svc`.
- Fixture that `monkeypatch.setenv`s vars the module under test never reads → strip.
- `_isolated_backend` / `fs_backend` / `state_persistence` redefined per file with subtle drift → use the shared one.
- `vitest.setup.ts` patching beyond the bare minimum — prefer per-test `vi.spyOn(window, 'fetch')` with a specific response.
