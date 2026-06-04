---
paths:
  - "inspector/tests/**/*.py"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
---

# Tests — assertions

- Pick the expected outcome and assert it strictly. **Never** `assert status in (200, 404)` — a 404 is a fixture-install regression that you want to fail. Same for `body in ({...}, None)` envelopes.
- Both sides of an `==` assertion must not normalize identically. `normalize("")  == normalize("")` always holds. Choose distinct inputs that produce distinct expected outputs.
- `repo_transitions.for_slug(slug)` returns `list[dict]`. Use `t["event"]`, not `t.event`. Check the repo function's return type before reaching for `.attr`.
- Don't use `is` / `is not` on potentially-interned values: empty `()`, empty `""`, small ints (-5..256), `None`, `True`, `False`. CPython interns these and identity flips silently. Use `==`, `cache_info()`, or inspect ids of values you constructed yourself.
- A test with setup and no assertion is decorative. If you mutate state, assert on it.
- Verify the durability boundary, not the call. The transition row in `repo_transitions` proves the event landed; a captured `audit.append(...)` call only proves the spy was invoked.
- When the test name says "X happened", read the source of truth (DB row, file content, store snapshot) and assert X. The function-under-test's return value is not authoritative.
- Tests should fail loudly. If a precondition isn't met, `pytest.fail` / `expect.fail` with a clear message — don't silently `return`.

## Anti-patterns

- `assert res.status_code == 200 or res.status_code == 404`
- `assert a == a`
- `assert () is not ()` (empty-tuple identity is True)
- `assert "" is ""` (interned)
- `events = {t.event for t in repo_transitions.for_slug(...)}` (dict has no `.event`)
- `assert mock.called` as the only assertion
- A test whose body is half setup + half logging, no `assert`
