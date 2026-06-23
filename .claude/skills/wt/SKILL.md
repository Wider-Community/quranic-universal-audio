---
name: wt
description: How to use worktrees.
---

# WT

Start/continue work in a worktree under `.worktrees/` (NOT `.claude/worktrees/`!) with sensible worktree + branch names related to the task. Checkout from the main or current worktree/branch depending on the context and situation, unless specified otherwise. Run `scripts/setup.py` in the background (non-blocking) to setup the environment, which copies `.env` and `node_modules`. 