---
paths:
  - "inspector/pyproject.toml"
  - "inspector/frontend/vitest.config.ts"
  - "inspector/frontend/package.json"
  - ".github/workflows/inspector-checks.yml"
  - ".coveragerc"
---

# Tests — coverage

- Coverage is **read-only**: pytest-cov + vitest v8 emit tables in CI job logs. No `--cov-fail-under`, no codecov, no PR comment.
- BE: `--cov` flags live in `inspector/pyproject.toml` `addopts`. Source = `.`. Exclusion via `[tool.coverage.run]` `omit`: `tests/*`, `frontend/*`, `.bucket/*`, `*/__init__.py`, `**/conftest.py`.
- FE: `@vitest/coverage-v8` with `all: true`, `include: ['src/**/*.{ts,svelte}']`, `exclude` for `**/*.test.ts`, `**/__tests__/**`, `src/lib/types/generated/**`, `**/*.d.ts`, `**/*.config.{ts,js,cjs,mjs}`, `vitest.setup.ts`.
- `qua_shared/tests` runs separately in CI with explicit `--cov=qua_shared`.
- Coverage artifacts (`.coverage*`, `coverage/`, `htmlcov/`) are gitignored at repo root.

## Anti-patterns

- Adding `--cov-fail-under=N` → turns coverage from observation into gate. Out of scope without an explicit decision.
- Including `frontend/src/lib/types/generated/**` in coverage → the file is 100% generated; coverage is meaningless and noisy.
- Including `inspector/tests/**` in coverage source → the test files themselves should not count.
- Wiring codecov / coveralls without an explicit ask → leaks repo state to third parties.
- `--cov` paths that don't survive a CWD change (FE coverage block must hold its own; BE `addopts` assumes `cd inspector`).
