---
name: wt
description: How to use worktrees.
---

# WT

Start/continue work in a worktree under `.worktrees/` (NOT `.claude/worktrees/`!) with sensible worktree + branch names related to the task. Checkout from the main or current worktree/branch depending on the context and situation, unless specified otherwise.

Then bootstrap the environment: run `python scripts/devenv/setup_worktree.py` (non-blocking) from inside the new worktree. It mirrors `.env` + `node_modules` (root, for git hooks, and `inspector/frontend`, for the SPA toolchain) from the main checkout — fast and idempotent — so `npm run check`/`build`/`test` and `/launch` work immediately. If the main checkout has no `node_modules` to copy, it falls back to `scripts/devenv/setup.sh frontend`. A fresh worktree WILL fail with "svelte-check is not recognized" until this runs.