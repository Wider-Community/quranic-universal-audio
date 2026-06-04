---
paths:
  - "inspector/tests/**/*.py"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
---

# Tests — skip / xfail

- Every skip carries a reason string: `@pytest.mark.skip(reason="...")`, `pytest.skip("...")`, `describe.skipIf(cond, '...')`.
- `describe.skipIf(!module)` (FE) is a phase gate — only valid for build-ahead-of-implementation. The moment the gated module lands, convert the dynamic import to a static one and drop the `skipIf`.
- `loadOptional<X>('path')` exists only to support phase gates. Same removal trigger.
- Never commit `.only` / `it.only` / `describe.only` / `test.only`. CI doesn't catch them; they silently skip every sibling test in the file.
- `xfail` only with a linked tracking issue or doc reference. No silent xfail.
- `if False:` and `return  # skip` are deletion candidates — not legitimate skip mechanisms.
- A skip outliving its reason is dead code. When the gating condition no longer applies, delete the skip and run the test.

## Anti-patterns

- `@pytest.mark.skip` with no reason → either justify in-place or delete.
- `describe.skipIf(!applyCommand)` where `applyCommand` is exported by a module that shipped → static import, drop the gate.
- File-level `pytestmark = pytest.mark.skip(...)` muting an entire file with no tracking → either fix or delete the file.
- `vi.skipIf` / `it.todo` left after the feature lands → run it.
- `pytest.skip("flaky on CI")` → flakiness is a bug to fix, not a skip reason.
