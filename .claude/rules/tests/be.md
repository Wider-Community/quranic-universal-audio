---
paths:
  - "inspector/tests/**/*.py"
  - "qua_shared/tests/**/*.py"
---

# Tests — BE pytest

- Use shared fixtures from `inspector/tests/conftest.py`: `signed_in_client`, `tmp_reciter_dir`, `seed_state`, `seed_role`, `flask_client`, `load_fixture`, `state_persistence`. Don't redefine.
- One subdir per subsystem under `inspector/tests/`. Cross-app smokes only at the root (rare). Operational scripts go to `scripts/diagnostics/`, not `tests/smoke/`.
- Module-top imports only. No function-local `from datetime import …` or `from services.db import get_conn`.
- `monkeypatch.setenv` for every env mutation. Never `os.environ[...] =` or module-level `os.environ.setdefault`.
- Hand-INSERTing delivery / claim / role rows is forbidden — go through repo helpers (`_seed_delivery_chain`, `repo_claims.*`, `repo_state.*`).
- `pytest --strict-markers`. Don't add a marker without registering it.
- Tests run in any order — no `test_01_*`, no module-load side effects, no shared mutable globals.
- `qua_shared/tests/` has its own `conftest.py` for `sys.path` bootstrap. Don't `sys.path.insert(...)` at file top.

## Anti-patterns

- `os.environ.setdefault('INSPECTOR_SESSION_SECRET', '0'*64)` at module top → central in conftest, drop per-file copies.
- `from tests.conftest import _seed_state` inside a function → take the fixture as a parameter.
- Local `_row(...)` / `_replace_state(...)` / `_hf_user(...)` / `_stub_hf_users(...)` factories → use the conftest-promoted `row_spec`, `seed_rows`, `hf_user_factory`, `stub_hf_users`.
- Synthesising a pre-version DB without every column downstream migrations read (e.g. forgot `role_assignments` or `requests.submitted_at`) → fail with `no such table/column`. Mirror `0001_init.sql` for the columns 0003 reads.
- Mocking `state.transition()` / `repo_transitions.append()` in a test that's supposed to verify state changed → read the transition rows back instead.
