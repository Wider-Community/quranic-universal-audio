# Lint

Lint is gated by the pre-commit hook — lint-staged runs `eslint --fix` on staged FE files and `ruff check --fix` + `ruff format` on staged Python, then re-stages the fixes. Don't run a separate full `npm run lint` / `ruff` pass while iterating; let the hook fix and gate on commit, and only invoke lint manually to diagnose a specific failure it surfaced.
