---
paths:
  - "inspector/tests/**/*.py"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
---

# Tests — assertion anti-patterns

General assertion principles live in `common.md`. These are the concrete patterns we keep hitting.

## Anti-patterns

- `assert res.status_code == 200 or res.status_code == 404` — pick one, the other is a regression.
- `assert normalize("") == normalize("")` — both sides collapse to `""`; use distinct inputs.
- `assert () is not ()` — empty tuples are interned; identity is True. For cache-distinctness, read `cache_info()`.
- `assert "" is ""`, `assert None is None`, `assert 1 is 1` — interned; flips silently when the implementation changes.
- `events = {t.event for t in repo_transitions.for_slug(...)}` — `for_slug` returns `list[dict]`, use `t["event"]`.
- `assert mock.called` as the only assertion — check the durability boundary (DB row, file content) instead.
- `assert audit_calls` when the code under test calls `repo_transitions.append` directly, bypassing `audit.append` — the spy never fires; verify by reading transitions back.
- A test that asserts an invariant a read-time gate alone satisfies (the test passes whether the write happened or not) → tighten to assert the write itself.
- `assert getAudioGraph(el) === null` after a suspended-ctx operation that creates the graph anyway → assert on `_ctxResume`, not the graph reference.
