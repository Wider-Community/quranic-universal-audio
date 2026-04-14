# Stage 2 — Orchestrator Handoff (for fresh Claude Code session)

**Date**: 2026-04-14
**Branch**: `worktree-refactor+inspector-modularize` (WSL worktree)
**Working directory**: `/mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/`
**Current HEAD**: `9ed6def` (orchestrator doc catch-up after 2 S2-B07 fix commits)
**Project CLAUDE.md**: `inspector/CLAUDE.md` (gitignored — locally edited by prior agents; frontend tree section may drift slightly)

## TL;DR for the incoming orchestrator

You are taking over a multi-wave refactor driven by the `/refactor` skill. Stage 2 migrates the inspector frontend from vanilla-TS-imperative-DOM to Svelte 4, plus backend polish + Docker distribution. Waves 0.5, 1, 2, 3, 3-followup, and 4 are complete. You are currently at **STOP-POINT 1** — the user's first declared pause — which the user was smoking when a Wave-3 regression (S2-B07) surfaced. The bug is fixed (SHA `015556b`); user has not yet confirmed the post-fix smoke. Resume there.

Next waves queued: **5 → 6 → 7 → [stop-point 2] → 10 → 11**. Waves 8 and 9 were missing in the quick recap; they go between 7 and the stop-point. Full order: **5, 6, 7, 8, 9, [stop 2], 10, 11**.

## State snapshot

### What's DONE

| Wave | Scope | Exit SHA | Notes |
|------|-------|----------|-------|
| 0.5 | Focused exploration of `segments/history/rendering.ts` | n/a (read-only) | Output: `.refactor/stage2-wave-0.5-handoff.md` |
| 1 | B02 fix + timestamps registry + cache.py + keyboard-guard | `fe60c35` | 9 commits + orchestrator chore `7961bae` |
| 2a | `config.py` INSPECTOR_DATA_DIR + vendor validators + Dockerfile+compose+.dockerignore + requirements-dev | `8d6e448` | 6 commits |
| 2-mid | Docker files moved from repo root → `inspector/` | `e98fb20` | 1 commit |
| 2b | `app.py` structured logging + 3 thin-routes + `save_seg_data` extract-method + magic-number sweep | `1a15c71` | 7 commits |
| 2-review | Sonnet + Opus + Haiku reviews | `46e1103` | follow-up commit only |
| 3 | Svelte 4 install + App.svelte + shared→lib migration + 6 shared primitives + CSS map | `566bb68` | 12 commits |
| 3-followup | `keyboard-guard` helper + `<AudioElement>` primitive + `<WaveformCanvas>` sub-ranging | `3e301f8` | 4 commits |
| 4 | Timestamps tab Svelte conversion (stores + 5 components) + 9 `timestamps/*.ts` deleted | `66f62d6` | 10 commits |
| 4-review | Sonnet + Opus reviews (both APPROVE) | `dd4c5c9` | follow-up commit only |
| stop-point-1 hotfix | Fix S2-B07 (audio/index.ts module-top-level DOM access) | `015556b` | 2 commits + 1 bug-log commit + 1 plan catch-up |

### What's IN PROGRESS

**STOP-POINT 1 — user smoke** is live but incomplete:
- User ran `npm run build && python3 app.py`, loaded the app, saw blank page.
- Diagnosed + fixed S2-B07: `audio/index.ts` had 8 module-top-level `mustGet<T>()` calls + 5 module-top-level `<elem>.addEventListener(...)` calls. Both Wave-3 reviewers missed them (focused on DOMContentLoaded handler timing, not module-top access). Fix in 2 commits (`0d2a4c6` + `015556b`); now zero module-top-level DOM access in `audio/index.ts`.
- Orchestrator told user to reload. **User has not confirmed post-fix smoke passes.** That's where the previous session ended.

### What's NEXT

- **Confirm post-fix smoke** with user (they reload the built app and walk the 10-point smoke checklist in `stage2-wave-4-handoff.md` §8 or similar).
- On green smoke → **fire Wave 5** (Segments tab shell + filters + rendering + SegmentRow).
- Wave 5 prework: generate `.refactor/stage2-store-bindings.md` (component↔store subscription matrix — per plan §4 Wave 5 and Opus review of Wave 4).

## User preferences discovered this session

1. **Sonnet for impl agents by default**, even on intense waves. Already saved as user memory (`feedback_sonnet_impl_agents.md`). User may pre-emptively override to Opus per wave — did so for Wave 4 (first Svelte tab conversion) and explicitly said "opus" when I asked about Wave 4. Memory says "if Sonnet struggles, escalate to Opus" — user's Wave-4 override extends that to "preemptive Opus for intense frontend work at user's call."
2. **Reviewers stay per plan** (Opus for judgment, Sonnet for pattern, Haiku for mechanical). Not a token-cost target.
3. **User approves each wave before firing.** Minimal replies ("confirm", "approve", "opus", "yes") — take them at face value. When you ask a yes/no, expect one-word replies.
4. **No testing (pytest / Vitest / Playwright)** — user declined upfront (S2-D07). Re-check before adding any test infrastructure.
5. **No bundle-size tracking** (S2-D14).
6. **User's declared stop-points**: end of Wave 4 (DONE, in progress) and before Wave 10 (`history/rendering.ts` rewrite). Nowhere else unless user explicitly requests.
7. **User's escalation**: "pause only before highest-risk phases" — between Waves 5-9 run autonomously through review gates.
8. **Commit style**: no Co-Authored-By trailers in inspector commits. Match existing `refactor(inspector):`/`feat(inspector):`/`fix(inspector):`/`chore(inspector):`/`docs(inspector):` conventions. Use HEREDOC for commit messages.
9. **User does smoke tests themselves** (not agents) — reviewers rely on manual-smoke reasoning only; agents never start the dev server.
10. **Data files in working tree** (untracked `data/recitation_segments/*/` dirs, modified `inspector/README.md`, `inspector/frontend/src/styles/validation.css`) — leave alone; they're the user's ongoing reciter data work, not refactor scope.

## Pattern decisions locked for Waves 5-10

Read them verbatim in `.refactor/stage2-wave-4-handoff.md` (top-of-document "Pattern notes for Waves 5-10" section). 8 patterns, one-liners:

1. Plain `writable<T>()` / `derived` — no factory wrappers
2. Shallow derivation; `$:` for single-component computed values
3. Stores for tab-scoped state; props for parent→child; events for child→parent
4. No DOM caches in state — `bind:this` + `querySelectorAll` in imperative update functions
5. Module-scope `Map` for WebAudio-style caches (non-reactive, S2-D12)
6. CSS vars as `style:` directives on tab root div (NOT `:root` via JS)
7. Keyboard via `<svelte:window on:keydown>` inside each tab + `shouldHandleKey(e, tab)` guard
8. **Hybrid 60fps**: Svelte for structure + imperative `updateHighlights()` method via `bind:this` for per-frame class toggles (new in Wave 4)

**S2-D33 carry-forwards** (from Wave-4 reviewers, in decisions log): Wave 5 cleanup of 3 orphan derived stores in `verse.ts`; factor `createPlaybackStore()` if patterns collide; **before Wave 7** replace `document.getElementById('audio-player'|'seg-audio-player')` DOM-lookups with refs/callbacks; **before Wave 8** use `{#each}` over 11 categories with open-state persistence.

## Pitfalls + reviewer-prompt refinements (learned from S2-B07)

- **Wave-3 regression missed by reviewers**: both Wave-3 Sonnet and Opus reviewers audited mount timing but only inside `DOMContentLoaded` handler bodies — they did NOT grep for module-top-level `mustGet` / `element.addEventListener` calls. When auditing future tab conversions (Waves 5, 11), **add to reviewer prompts**: `grep -n "^[a-zA-Z].*\\.addEventListener\\|^[a-zA-Z].*mustGet" src/<tab>/index.ts` — any hits mean module-top-level DOM access that'll run before `new App()` mounts. Same root cause will bite segments/index.ts or audio/index.ts if either gets touched again before being deleted in Waves 5/11.
- **`segments/index.ts` has its mustGet inside DOMContentLoaded handler** (correct). But when Wave 5 starts converting segments, the interim state may have some new Svelte component + the old `segments/index.ts` both active — watch for the mount-before-access invariant.
- **`timestamps/*.ts` is fully deleted** — zero risk there.

## Useful commands

```bash
# Enter the worktree
cd /mnt/c/Users/ahmed/Documents/Uni/Thesis/Code/quranic-universal-audio/.claude/worktrees/refactor+inspector-modularize/

# Git state
git log --oneline -20
git status --short

# Pre-flight gates (7 gates incl. cycle ceiling, typecheck, lint, build, global leak checks)
bash .refactor/stage2-checks.sh

# Build for smoke test
cd inspector/frontend && npm run build && cd ..
python3 app.py  # serves at localhost:5000

# Inspector production-mode uses debug=False by default; FLASK_ENV=development re-enables it
```

## File reading order (fresh orchestrator)

Minimum to be operational:

1. `.refactor/stage2-plan.md` — full plan (v3, post 3-model review). **Read in full.** Especially §2 invariants, §4 scope per wave, §5 target structure, §6 wave ordering, §9 stop-points, §10 decisions.
2. `.refactor/stage2-wave-4-handoff.md` — **the pattern-setter**. Top-of-document pattern notes are load-bearing for Waves 5-10.
3. `.refactor/stage2-decisions.md` — 33 decisions (S2-D01 through S2-D33); scan the full list.
4. `.refactor/stage2-bugs.md` — 4 OPEN (B01/B04/B05 Stage-1 carry-overs + S2-B06 deferred cycles); S2-B02 and S2-B07 CLOSED.
5. `.refactor/stage2-orchestration-log.md` — per-agent budget + verdicts history.

Skim:
- `.refactor/stage2-css-migration-map.md` (load-bearing for Wave 11 cleanup)
- `.refactor/stage2-wave-{0.5, 1, 2, 3}-handoff.md` (later waves can look up as needed)
- `inspector/CLAUDE.md` (architecture principles — gitignored; frontend tree section may lag)

## Brief on the `/refactor` skill

The skill is at `~/.claude/skills/refactor/`. Key mechanics:

- **One implementation agent per wave** (max 3 sub-waves if a wave is genuinely large)
- **Reviewers at wave boundaries**: Sonnet always, Opus for heavy waves (per plan §6.2 table), Haiku for mechanical (Wave 2/3/11 primarily)
- **Stop-points**: declared in plan §9 (2 user-declared + systemic triggers like context ≥75%)
- **Shared docs**: orchestrator maintains 3 append-only `.refactor/stage2-*.md` files (bugs, decisions, orchestration-log) — agents append, never rewrite history
- **Plan-vs-delivery reconciliation** at every wave boundary via the handoff §6.3 template (11 sections, Wave 3 briefly drifted, Wave 4 restored conformity)
- **Pre-flight gate** `bash .refactor/stage2-checks.sh` runs 7 checks; must pass at every wave boundary
- **Cycle ceiling 23** (S2-B06 deferral): `CYCLE_CEILING` env var in `stage2-checks.sh`. Decrements per wave as segments cycles dissolve; set to 0 at Wave 11 re-promote.

## Immediate next actions for the fresh orchestrator

1. **Read** the 5 files listed above (plan, wave-4 handoff, decisions, bugs, orchestration log).
2. **Do NOT re-fire Waves 0.5/1/2/3/4** — they're done.
3. **Confirm with user** whether post-fix smoke is now green (they may respond "ok" / "works" / "broken again"). If silent, prompt them explicitly.
4. If smoke is green: **fire Wave 5** (Segments tab shell + filters + rendering + SegmentRow with history-mode props per S2-D23). First sub-task: generate `.refactor/stage2-store-bindings.md` component↔store subscription matrix. Brief the impl agent with scope from plan §4 Wave 5 + pattern notes from Wave 4 handoff + carry-forward items from S2-D33. Use Sonnet by default; user may say "opus" for this wave too (it's store-design foundation).
5. If smoke surfaces a new regression: diagnose like S2-B07 was — browser console first, grep for module-top-level DOM access, minimal file edit + rebuild + commit under `fix(inspector):`. Log as S2-B08 etc. in `stage2-bugs.md` Section 4/5.

## Known clean state

- 7/7 pre-flight gates green at HEAD `9ed6def`
- Cycle count 23 (= ceiling)
- Zero `// NOTE: circular dependency` comments
- Zero `global` keyword outside `services/cache.py`
- Zero orphan `_URL_AUDIO_META` / `_phonemizer` references
- Build: 480KB JS, 31KB CSS
- Timestamps tab: pure Svelte (5 components + 3 stores + 1 util)
- Segments + Audio tabs: unchanged Stage-1 imperative (still work via App.svelte hidden-div mount pattern)
- Backend: Docker-ready, structured logging, thin routes, `save_seg_data` decomposed
