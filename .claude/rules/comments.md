---
paths:
  - "inspector/**/*"
---

# Comments

- No dead / legacy comments mentioning things that do not exist anymore
- No comments mentioning refactors / cleanups  - "no longer", "phase", "removed", "deleted", "deprecated", "legacy", "old", "new", "will change/be" etc. are red flags, don't include and clean them up if you come across them
- No essay comments - concise and to the point, not long explanations or justifications. Don't write detailed analyses/findings/decisions/adrs.
- Avoid unnecessary details such as numbers or grnularities. If you are writing about storage MB, latency ms or anything similar that does not provide value as a comment, skip it, or add it to the relevant reference doc if is actually important
- docstrings: medium length, up to date, self-contained and helps familiarize for agents. Always make sure to read a file's docstring before writing to it, and update it after significant changes. If you find a docstring that is outdated or inaccurate, update it. Useful for quick overview of a file, and potentially what other files it relates to