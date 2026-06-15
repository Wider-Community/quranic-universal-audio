---
paths:
  - "inspector/tests/**"
  - "qua_shared/tests/**"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
---

# Tests — common

## TDD is the default

- Behaviour change in production code → write the failing test first, watch it fail, then make it pass. Refactor under green.
- New module / new branch / new error path = new test. Don't ship the change without one.
- Tactical exceptions (config tweaks, doc edits, mechanical renames): note in the commit, don't pretend.

## Running locally

- Run only the tests relevant to the change (touched files/dirs), never the full suite — CI runs the full matrix.
- Parallelise independent commands (codegen + targeted tests + typecheck) — issue them together or in the background, don't wait on each in sequence.

## Universal assertion principles

- Pick the expected outcome and assert it strictly. Never `status in (200, 404)` or `body in ({...}, None)` — a regression must fail loudly, not slip through a disjunction.
- Both sides of `==` must produce distinct values from distinct inputs. Identity normalisations on both sides = tautology.
- Verify the durability boundary, not the call. A DB row, file content, store snapshot proves the effect; `mock.called` does not.
- Don't use `is` / `is not` on interned values: empty `()`, `""`, `None`, `True`, `False`, small ints (-5..256). Use `==` or `cache_info()`.
- A test with setup but no assertion is decorative — delete or finish it.
- If a precondition isn't met, `pytest.fail` / `expect.fail` with a clear message. Never silent `return`.

## Structure

- BE: one subdirectory per subsystem under `inspector/tests/`. Cross-app smokes only at the root (rare).
- FE: component tests colocated as `<Module>.test.ts`. Util/domain tests under `<dir>/__tests__/<feature>.test.ts`.
- Operational scripts disguised as tests → `scripts/diagnostics/`. Baseline regenerators → `scripts/codegen/regen_*_baselines.py`. Neither belongs under `tests/`.

## Naming

- Test file name describes WHAT is tested. Drift = rename with `git mv`.
- Test function / `it` name describes the **assertion outcome**, not the setup (`…_zero_prior_rows` if the assert is `n == 0`).
- `describe('X', …)` names the module under test, not a sibling.
- No `test_1`, `test_basic`, `test_works`, `it('it works')`.

## Skip / xfail

- Every skip carries a reason: `@pytest.mark.skip(reason="…")`, `pytest.skip("…")`, `describe.skipIf(cond, '…')`.
- Never commit `.only` / `it.only` / `describe.only` / `test.only`. CI doesn't catch them; they silently mute every sibling.
- A skip outliving its reason is dead code — delete and run the test.

## Isolation

- Tests run in any order. No module-load side effects. No `test_01_*`.
- Mutations must be restored: `monkeypatch.setenv` (BE), `vi.stubEnv` or `afterEach` (FE). Never raw `os.environ[...] =` or unrestored store `.set(...)`.

## See also

- `be.md` — BE pytest runtime specifics
- `fe.md` — FE vitest runtime specifics
- `fixtures.md` — conftest + shared-helper authoring
- `mocking.md` — mock boundary table + spy discipline
- `assertions.md` — concrete assertion anti-patterns
- `schema-parity.md` — schema round-trip + FE codegen
- `coverage.md` — coverage tooling
