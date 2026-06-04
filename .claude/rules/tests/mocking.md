---
description: Mocking boundary table — what to mock, what NOT to mock (BE + FE)
globs:
  - "inspector/tests/**/*.py"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
---

# Tests — mocking boundaries

| Boundary | Use | Don't |
|---|---|---|
| BE bucket / data dir | `tmp_reciter_dir`, `state_persistence` (FilesystemBackend) | patch `Path.read_text` / `hf_bucket` internals |
| BE env vars | `monkeypatch.setenv` | raw `os.environ[...] =`, module-level setdefault |
| BE OAuth / identity | `signed_in_client(role=…)` | mock `auth_service.encode_session` |
| BE external HTTP (QF, HF, GH) | monkeypatch the specific service fn (`hf_users.lookup`, …) | mock `requests.get` |
| BE caches | autouse teardown; new caches → `_SEG_CACHE_NAMES` | mock cache primitives |
| BE audit / transitions | record-and-call-through OR read `repo_transitions.for_slug(slug)` back | `lambda *a, **kw: None` (loses durability check) |
| BE time | leave real | mock `datetime.now` globally |
| FE modules | real imports + props | `vi.mock(...)` on non-ambient modules |
| FE fetch | `vi.spyOn(window, 'fetch')` per test | blanket `vitest.setup.ts` mock as production code |
| FE stores | real store + `.set()`, restore in `afterEach` | mock the store module |
| FE audio elements | `audio._fireEvent('canplay')` from `makeAudioStub` | hand-roll the stub, dispatch raw events |

## Rules

- Spy signatures MUST match the real function — grep `def foo(` / `function foo(` first. Wrong arity blows up at runtime with `takes N but M given`.
- Spies that acquire a lock the real function ALSO acquires inside → deadlock. Release before delegating, or remove the spy.
- Don't mock the function whose effect you want to verify — assert against the durability boundary (DB row, file content, store state), not the call.
- `state.py` calls `repo_transitions.append(...)` directly, NOT `audit.append(...)`. Spying on `services.audit.append` for a state-machine test catches nothing.
- A pass-through spy that captures kwargs is fine — but the call-list assertion is weaker than reading the persisted row back.
