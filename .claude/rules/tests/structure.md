---
description: Where tests live, what they're called, when to rename or move
globs:
  - "inspector/tests/**"
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
  - "scripts/diagnostics/**"
  - "scripts/codegen/**"
---

# Tests — structure + naming

## Foldering

- BE: one subdirectory per subsystem under `inspector/tests/`. Subsystems mirror `services/`, `routes/`, `admin/`, `db/`, `persistence/`, `classifier/`, `command/`, `identity/`, `registry/`, `undo/`, `utils/`, `scripts/`.
- BE root `inspector/tests/test_*.py` is reserved for genuine cross-app smokes (e.g. `test_app_smoke.py`). A test that fits a subsystem belongs in that subsystem's subdir — move it with `git mv`.
- Operational scripts disguised as tests live in `scripts/diagnostics/` (`bucket_smoke.py`, `services_smoke.py`, …). Never `inspector/tests/smoke/`.
- Baseline regenerators live in `scripts/codegen/regen_*_baselines.py`. Never `inspector/tests/parity/snapshot_*.py`.
- FE: component tests colocated with `<Module>.svelte` as `<Module>.test.ts`. Util/domain tests under `<dir>/__tests__/<feature>.test.ts`. Tab-internal tests under `tabs/<tab>/__tests__/<area>/<feature>.test.ts`.

## Naming

- Test file name describes WHAT is tested. If `SegmentsList.test.ts` actually exercises `virtualization.ts`, rename to `virtualization.test.ts` (`git mv`).
- Test function / `it` block name describes the **assertion outcome**, not the setup. `test_supersede_marks_zero_prior_rows` (asserts `n == 0`), not `test_supersede_marks_prior_rows`.
- `describe('X', …)` block name = the module under test. Not a sibling component.
- Split tests when the name conflates concerns (`test_grant_missing_origin_returns_403` vs `test_grant_cross_origin_returns_403` are two different assertions, two tests).

## Anti-patterns

- `test_1`, `test_basic`, `test_works`, `test_smoke`, `it('it works')`, `it('renders')` with no assertion specifics.
- File at `inspector/tests/test_audio_meta.py` when `inspector/tests/services/test_audio_meta.py` is the convention.
- `tests/smoke/`, `tests/parity/`, `tests/integration/` — none of those belong under `tests/`.
- A test name that's a lie about what the body does → rename or rewrite.
