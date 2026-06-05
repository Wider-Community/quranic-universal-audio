---
paths:
  - "inspector/tests/**/*.py"
  - "qua_shared/tests/**/*.py"
---

# Tests — BE pytest

- Shared fixtures from `inspector/tests/conftest.py` are the API: `signed_in_client`, `tmp_reciter_dir`, `seed_state`, `seed_role`, `flask_client`, `load_fixture`, `state_persistence`, `row_spec`, `seed_rows`, `hf_user_factory`, `stub_hf_users`, `make_actor`. Don't redefine.
- Module-top imports only. No function-local `from datetime import …` or `from services.db import get_conn`.
- `monkeypatch.setenv` for every env mutation. Never `os.environ[...] =` or module-level `os.environ.setdefault`.
- Hand-INSERTing delivery / claim / role rows is forbidden — go through `_seed_delivery_chain`, `repo_claims.*`, `repo_state.*`.
- `pytest --strict-markers`. Don't add a marker without registering it in `pyproject.toml`.
- `qua_shared/tests/conftest.py` handles `sys.path` bootstrap for the shared package. No per-file `sys.path.insert`.

## Anti-patterns

- `os.environ.setdefault('INSPECTOR_SESSION_SECRET', '0'*64)` at module top → centralized in conftest, drop per-file.
- `from tests.conftest import _seed_state` inside a function → take the fixture as a parameter.
- Local `_row()` / `_replace_state()` / `_hf_user()` / `_stub_hf_users()` factories → use the conftest-promoted equivalents.
- Pre-version DB simulation without every column downstream migrations read (e.g. forgot `role_assignments` or `requests.submitted_at`) → mirror `0001_init.sql`.
- `repo_transitions.for_slug(...)` returns `list[dict]` — `t["event"]`, not `t.event`.
